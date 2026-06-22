"""Example 4 (flagship) — Ingesting a complex German business-magazine PDF.

This is the most realistic ``runic.rag`` example. It ingests a slice of a real,
messy German business magazine (*Manager Magazin*, June 2026) and demonstrates
the single most impactful lever in Graph-RAG quality: **the ontology**.

What it shows
-------------
1. Loading a bounded page range from a large PDF with
   :mod:`runic.rag.adapters.documents` (``load_pdf`` / ``load_pdf_pages``).
2. Keeping a run *cheap and bounded* with a :class:`~runic.rag.config.RagSettings`
   cost budget (``max_llm_calls`` / ``max_tokens``) that the ingestion service
   turns into a :class:`~runic.rag.concurrency.BudgetGuard`.
3. **Ontology optimization (the headline):** the *same* text slice is ingested
   twice —
     * into graph ``mm_default`` with :meth:`Ontology.default` (generic types:
       Person, Organization, Location, Concept, Product, Event), and
     * into graph ``mm_tuned`` with a hand-tuned business/finance ontology
       (Company, Executive, Industry, FinancialMetric, Product, Market, Person,
       Location).
   The same business question is then answered against both graphs and the
   results are printed side by side (entity counts per type, typed coverage, and
   the answer + citations) so you can see the tuned ontology produce cleaner,
   better-typed extraction and a more grounded answer.

Running it
----------
Requires ``OPENAI_API_KEY`` (the default OpenAI provider) and a reachable
FalkorDB::

    docker compose -f docker-compose.test.yml up -d falkordb
    export OPENAI_API_KEY=sk-...           # or put it in .env
    uv run python examples/rag/04_manager_magazin_pdf.py

Cost is bounded by default: only a small page slice is ingested (see ``PAGE_*``)
and ``MAX_LLM_CALLS`` / ``MAX_TOKENS`` cap each ingest. Flip ``INGEST_WHOLE_DOC``
to ``True`` (and raise the budget) to ingest the entire magazine.

Tuning knobs can also be supplied via the environment, e.g.::

    MM_PAGE_FIRST=10 MM_PAGE_LAST=18 MM_MAX_LLM_CALLS=400 \\
        uv run python examples/rag/04_manager_magazin_pdf.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from runic.ogm.driver.factory import create_driver
from runic.rag import GraphRAG, Ontology, RagSettings, load_settings
from runic.rag.adapters import documents

if TYPE_CHECKING:
    from runic.ogm.driver import GraphDriver
    from runic.rag.domain import Answer

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _emit(line: str = "") -> None:
    """Write a line of the human-readable report to stdout.

    Examples are allowed to print; routing every report line through this single
    helper keeps the rest of the module free of bare ``print`` calls.
    """
    print(line)  # noqa: T201 - example report output


# ─────────────────────────────────────────────────────────────────────────────
# Constants & tunables (overridable via the environment)
# ─────────────────────────────────────────────────────────────────────────────

#: The complex German business magazine we ingest. Override with ``MM_PDF_PATH``.
#: The default resolves to the repo root (examples/rag/<file>.parents[2]) so the
#: documented ``uv run python examples/rag/04_...`` invocation works from any cwd.
_DEFAULT_PDF = Path(__file__).resolve().parents[2] / "BusinessMagazin.pdf"
PDF_PATH: str = os.getenv("MM_PDF_PATH", str(_DEFAULT_PDF))

#: Bounded page range (1-based, inclusive). A modest slice keeps a run cheap.
#: To ingest the WHOLE document instead, set ``INGEST_WHOLE_DOC = True`` below
#: (or export ``MM_INGEST_WHOLE_DOC=1``) and raise the budget caps accordingly.
PAGE_FIRST: int = int(os.getenv("MM_PAGE_FIRST", "1"))
PAGE_LAST: int = int(os.getenv("MM_PAGE_LAST", "8"))

#: Set True to ingest the ENTIRE magazine (ignores PAGE_FIRST/PAGE_LAST).
#: WARNING: this can issue thousands of LLM calls — raise the budget too.
INGEST_WHOLE_DOC: bool = os.getenv("MM_INGEST_WHOLE_DOC", "0") == "1"

#: Hard cost ceilings shared by BOTH ingests (0 == unlimited). These default to
#: comfortably cover an ~8-page slice while still failing fast on runaways.
MAX_LLM_CALLS: int = int(os.getenv("MM_MAX_LLM_CALLS", "300"))
MAX_TOKENS: int = int(os.getenv("MM_MAX_TOKENS", "0"))

#: Distinct FalkorDB graphs so the two ontologies never share state.
GRAPH_DEFAULT: str = "mm_default"
GRAPH_TUNED: str = "mm_tuned"

#: A finance-flavoured question both graphs must answer from the same slice.
QUESTION: str = (
    "Which companies and executives are discussed, and what financial figures "
    "or market developments are mentioned?"
)

#: The hand-tuned business/finance vocabulary. Hard entity types steer the
#: extractor toward the concepts that actually matter in a business magazine,
#: which yields cleaner, better-typed nodes than the generic defaults.
TUNED_TYPES: list[str] = [
    "Company",
    "Executive",
    "Industry",
    "FinancialMetric",
    "Product",
    "Market",
    "Person",
    "Location",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _require_openai_key() -> None:
    """Exit early with a clear message if no OpenAI key is configured."""
    if os.getenv("OPENAI_API_KEY"):
        return
    log.error(
        "OPENAI_API_KEY is not set. This example calls the OpenAI API for "
        "extraction, embedding, and answer synthesis."
    )
    log.error("Set it in your shell or .env, then re-run:")
    log.error("  export OPENAI_API_KEY=sk-...")
    log.error("  uv run python examples/rag/04_manager_magazin_pdf.py")
    sys.exit(1)


def _check_pdf_present() -> None:
    """Exit early with a clear message if the magazine PDF is missing."""
    if Path(PDF_PATH).is_file():
        return
    log.error("PDF not found at: %s", PDF_PATH)
    log.error("Point MM_PDF_PATH at a readable PDF and re-run, e.g.:")
    log.error('  MM_PDF_PATH="/path/to/magazine.pdf" \\')
    log.error("    uv run python examples/rag/04_manager_magazin_pdf.py")
    sys.exit(1)


def _load_slice() -> tuple[str, str]:
    """Return ``(text, label)`` for the configured page slice (or whole doc).

    The label is a short human-readable description of what was loaded, used in
    log lines and as the ingestion ``source`` so chunks stay attributable.
    """
    if INGEST_WHOLE_DOC:
        log.info("Loading the ENTIRE document (this can be large)...")
        text = documents.load_pdf(PDF_PATH)
        return text, "manager-magazin:all-pages"

    log.info("Loading pages %d-%d ...", PAGE_FIRST, PAGE_LAST)
    # load_pdf_pages keeps page boundaries so we can report how much we read; we
    # then join into one string for ingestion (the chunker re-splits anyway).
    pages = documents.load_pdf_pages(
        PDF_PATH, first_page=PAGE_FIRST, last_page=PAGE_LAST
    )
    text = "\n\n".join(page_text for _, page_text in pages)
    log.info("Loaded %d page(s), %d characters of text", len(pages), len(text))
    return text, f"manager-magazin:pages-{PAGE_FIRST}-{PAGE_LAST}"


def _make_settings(graph: str) -> RagSettings:
    """Build budget-capped settings pinned to a specific FalkorDB graph.

    Starts from the environment/.env (so the LLM/embedding model and credentials
    are honoured) and overrides only the graph name and the cost ceilings, so
    every run of this example is affordable by default.
    """
    base = load_settings()
    return base.model_copy(
        update={
            "falkordb_graph": graph,
            "max_llm_calls": MAX_LLM_CALLS,
            "max_tokens": MAX_TOKENS,
        }
    )


def _reset_graph(driver: GraphDriver) -> None:
    """Wipe a graph so repeated runs of this example start clean and comparable."""
    driver.execute("MATCH (n) DETACH DELETE n", {})


def _entity_counts_by_type(driver: GraphDriver) -> dict[str, int]:
    """Return a histogram of Entity nodes grouped by their ``type`` property."""
    result = driver.execute(
        "MATCH (e:Entity) RETURN coalesce(e.type, '') AS t, count(*) AS c", {}
    )
    counts: dict[str, int] = {}
    for row in result.rows:
        label = str(row[0]) if row[0] else "(untyped)"
        counts[label] = counts.get(label, 0) + int(row[1])
    return counts


def _typed_coverage(counts: dict[str, int], vocabulary: list[str]) -> float:
    """Fraction of entities whose ``type`` is a recognised ontology type [0, 1].

    Higher is better: it means the extractor placed entities into meaningful,
    queryable buckets instead of a generic catch-all (or no type at all).
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    vocab = set(vocabulary)
    typed = sum(n for label, n in counts.items() if label in vocab)
    return typed / total


def _ingest(rag: GraphRAG, text: str, source: str) -> None:
    """Bootstrap the schema then ingest *text*, logging the write report."""
    rag.bootstrap_schema()
    report = rag.ingest_text(text, source=source)
    log.info(
        "  ingested: %d chunks, %d entities, %d relations, %d mentions",
        report.chunks,
        report.entities,
        report.relations,
        report.mentions,
    )


def _build_rag(
    driver: GraphDriver, settings: RagSettings, ontology: Ontology
) -> GraphRAG:
    """Wire a production :class:`GraphRAG` over *driver* with *ontology*."""
    return GraphRAG.with_defaults(driver, settings=settings, ontology=ontology)


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────


def _print_histogram(title: str, counts: dict[str, int]) -> None:
    """Pretty-print an entity-type histogram, most frequent first."""
    _emit(f"\n  {title}")
    if not counts:
        _emit("    (no entities extracted)")
        return
    width = max(len(label) for label in counts)
    for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        bar = "#" * min(n, 40)
        _emit(f"    {label.ljust(width)}  {n:>4}  {bar}")


def _print_answer(title: str, answer: Answer) -> None:
    """Print an answer with a short citation summary."""
    _emit(f"\n  {title}")
    _emit(f"    {answer.text.strip()}")
    _emit(f"    citations: {len(answer.citations)}")
    for citation in answer.citations[:3]:
        snippet = citation.text.strip().replace("\n", " ")
        if len(snippet) > 100:
            snippet = snippet[:100] + "…"
        _emit(f"      - [{citation.source}] {snippet}")


def _print_comparison(
    *,
    default_counts: dict[str, int],
    tuned_counts: dict[str, int],
    default_answer: Answer,
    tuned_answer: Answer,
) -> None:
    """Render the full side-by-side comparison and the takeaways."""
    _emit("\n" + "=" * 78)
    _emit("ONTOLOGY OPTIMIZATION — side-by-side comparison")
    _emit("=" * 78)

    default_total = sum(default_counts.values())
    tuned_total = sum(tuned_counts.values())
    default_cov = _typed_coverage(default_counts, Ontology.default().entity_types())
    tuned_cov = _typed_coverage(tuned_counts, TUNED_TYPES)

    _emit("\nEntity extraction:")
    _emit(
        f"  generic ontology : {default_total:>4} entities, "
        f"typed coverage {default_cov:6.1%}, {len(default_counts)} distinct types"
    )
    _emit(
        f"  tuned ontology   : {tuned_total:>4} entities, "
        f"typed coverage {tuned_cov:6.1%}, {len(tuned_counts)} distinct types"
    )

    _print_histogram("generic ontology — entities by type:", default_counts)
    _print_histogram("tuned ontology — entities by type:", tuned_counts)

    _emit("\n" + "-" * 78)
    _emit(f"Question: {QUESTION}")
    _emit("-" * 78)
    _print_answer("generic ontology — answer:", default_answer)
    _print_answer("tuned ontology — answer:", tuned_answer)

    _emit("\n" + "=" * 78)
    _emit("TAKEAWAYS")
    _emit("=" * 78)
    _emit(
        "  - The generic ontology dumps most nodes into 'Organization'/'Concept';\n"
        "    the tuned ontology splits them into Company / Executive / Industry /\n"
        "    FinancialMetric / Market — buckets you can actually query and filter."
    )
    _emit(
        "  - Higher 'typed coverage' means more entities landed in meaningful,\n"
        "    domain-specific types instead of a catch-all, so graph traversal and\n"
        "    type-filtered retrieval return sharper neighbourhoods."
    )
    _emit(
        "  - Same text, same budget, same question — only the ontology changed.\n"
        "    Tuning the vocabulary is the cheapest, highest-leverage quality win\n"
        "    in Graph-RAG: no model change, no extra passes, just better types."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def _run_one(
    *, graph: str, ontology: Ontology, text: str, source: str, banner: str
) -> tuple[dict[str, int], Answer]:
    """Ingest *text* into *graph* under *ontology*, then answer QUESTION.

    Returns the per-type entity histogram and the synthesized answer so the
    caller can build the side-by-side comparison.
    """
    _emit("\n" + "=" * 78)
    _emit(banner)
    _emit("=" * 78)

    settings = _make_settings(graph)
    driver = create_driver(
        "falkordb",
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph=graph,
    )
    try:
        _reset_graph(driver)
        rag = _build_rag(driver, settings, ontology)
        _ingest(rag, text, source)
        counts = _entity_counts_by_type(driver)
        # 'hybrid' fans out across vector + fulltext + graph expansion — the best
        # mode for a broad, thematic business question like ours.
        answer = rag.query(QUESTION, mode="hybrid")
    finally:
        close = getattr(driver, "close", None)
        if callable(close):
            close()
    return counts, answer


def main() -> None:
    """Ingest the magazine slice under two ontologies and compare the results."""
    load_dotenv()  # make OPENAI_API_KEY in a local .env visible before checks
    _require_openai_key()
    _check_pdf_present()

    text, source = _load_slice()
    if not text.strip():
        log.error("Loaded text is empty — nothing to ingest. Check the page range.")
        sys.exit(1)

    # Pass 1: the generic, batteries-included ontology.
    default_counts, default_answer = _run_one(
        graph=GRAPH_DEFAULT,
        ontology=Ontology.default(),
        text=text,
        source=source,
        banner="PASS 1/2 — generic ontology  (graph: mm_default)",
    )

    # Pass 2: the SAME slice under a tuned business/finance ontology.
    tuned_counts, tuned_answer = _run_one(
        graph=GRAPH_TUNED,
        ontology=Ontology.from_types(TUNED_TYPES),
        text=text,
        source=source,
        banner="PASS 2/2 — tuned business/finance ontology  (graph: mm_tuned)",
    )

    _print_comparison(
        default_counts=default_counts,
        tuned_counts=tuned_counts,
        default_answer=default_answer,
        tuned_answer=tuned_answer,
    )


if __name__ == "__main__":
    main()
