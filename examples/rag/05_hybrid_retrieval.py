"""Example 5 — local vs hybrid vs auto retrieval (RRF fusion, ADR-017).

This example ingests one small corpus and then runs the SAME query through the
three retrieval modes the :class:`~runic.rag.facade.GraphRAG` facade supports,
side by side:

  * ``mode="local"`` — a single vector seed expanded over the entity
    neighbourhood (``max_hops``). Precise and cheap, but recall is limited to
    whatever the nearest entities happen to mention.

  * ``mode="hybrid"`` — fans out across THREE complementary strategies and fuses
    them with Reciprocal Rank Fusion (RRF, ADR-017):
        - vector search   (semantic similarity over entity embeddings)
        - fulltext search (exact lexical / keyword matches)
        - high-level      (LLM-extracted theme keywords → thematic subgraph)
    Because an item ranked highly by *any* retriever bubbles up in the fused
    result, hybrid mode recovers evidence that a pure-vector walk misses —
    higher recall without drowning precision.

  * ``mode="auto"`` — a light, dependency-free classifier inspects the query and
    picks ``local`` for short, entity-pointed questions or ``hybrid`` for broad,
    thematic ones. You get hybrid's recall only when the question needs it.

For each mode the script prints the retrieved entities and chunks (with their
fused scores) and the synthesized answer, so you can see how RRF widens recall.

The default backend is FalkorDB on localhost:6379 (graph name unique to this
example).

Prerequisites:
  * A running FalkorDB:  docker run -p 6379:6379 -it --rm falkordb/falkordb
  * An OpenAI key:  OPENAI_API_KEY=sk-...  (extraction/embeddings/synthesis)

Run it:
    uv run python examples/rag/05_hybrid_retrieval.py
"""
# ruff: noqa: T201 - examples print their output to stdout for the reader.

from __future__ import annotations

import logging

from dotenv import load_dotenv

from runic.rag import GraphRAG, RagSettings, load_settings
from runic.rag.domain import Answer

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_GRAPH_NAME = "runic_rag_ex05"

# The three modes we contrast, in increasing breadth/recall.
_MODES: tuple[str, ...] = ("local", "hybrid", "auto")


# ---------------------------------------------------------------------------
# A small corpus engineered so the three modes diverge.
#
# The "vector" cluster (renewable energy) and the "lexical" cluster (a specific
# product code, "SOLARK-9000") let us show that:
#   - vector search finds semantically related material, and
#   - fulltext search finds the exact code a vector search may rank lower,
# so the hybrid fusion recovers BOTH.
# ---------------------------------------------------------------------------

DOC_OVERVIEW = """\
Helios Energy is a renewable power company focused on grid-scale solar storage.
Its flagship battery system pairs lithium-iron-phosphate cells with an inverter
designed for long-duration discharge. The company positions itself against
incumbent fossil-fuel peaking plants.

Helios Energy was founded by Mara Quinn, an electrical engineer who previously
worked on photovoltaic efficiency research. Under her leadership the firm has
prioritised safety and recyclability over raw energy density.
"""

DOC_PRODUCT = """\
The SOLARK-9000 is Helios Energy's grid-scale battery product. Each SOLARK-9000
unit stores up to four megawatt-hours and is rated for twenty thousand charge
cycles. Utilities deploy the SOLARK-9000 to smooth demand peaks and to back up
intermittent solar generation.

The SOLARK-9000 uses a modular rack design so capacity can be added without
replacing the inverter. Its firmware exposes a telemetry API for remote health
monitoring.
"""

DOC_MARKET = """\
Demand for long-duration energy storage is rising as grids add more wind and
solar capacity. Analysts expect storage deployments to grow sharply over the
next decade, driven by falling battery costs and supportive policy.

Helios Energy competes with several established manufacturers, but differentiates
on cycle life and on the recyclability of its lithium-iron-phosphate chemistry.
Mara Quinn has argued publicly that durability, not just price, will decide which
storage vendors endure.
"""

CORPUS: dict[str, str] = {
    "helios_overview.txt": DOC_OVERVIEW,
    "solark_9000_spec.txt": DOC_PRODUCT,
    "storage_market.txt": DOC_MARKET,
}


def _build_settings() -> RagSettings:
    """Load settings from the environment, pinning this example's graph name."""
    settings = load_settings()
    return settings.model_copy(update={"falkordb_graph": _GRAPH_NAME})


def _ingest_corpus(rag: GraphRAG) -> None:
    """Ingest the corpus, printing a one-line report per source."""
    print("\n=== Ingesting corpus ===")
    for source, text in CORPUS.items():
        report = rag.ingest_text(text, source=source)
        print(
            f"  {source:<22} chunks={report.chunks} entities={report.entities} "
            f"relations={report.relations} mentions={report.mentions}"
        )


def _print_context(answer: Answer) -> None:
    """Print the retrieved entities and chunks behind *answer*."""
    context = answer.context
    if context is None:
        print("    (no retrieval context attached)")
        return

    print(f"    entities ({len(context.entities)}):")
    if not context.entities:
        print("      (none)")
    for entity in context.entities:
        print(f"      - {entity.name} ({entity.type})  score={entity.score:.5f}")

    print(f"    chunks ({len(context.chunks)}):")
    if not context.chunks:
        print("      (none)")
    for chunk in context.chunks:
        snippet = chunk.text.replace("\n", " ").strip()
        if len(snippet) > 72:
            snippet = f"{snippet[:72]}…"
        print(f"      - [{chunk.source}] score={chunk.score:.5f}  {snippet}")


def _run_mode(rag: GraphRAG, query: str, mode: str) -> Answer:
    """Run *query* under *mode*, printing the context and the fused answer."""
    print(f"\n--- mode={mode!r} ---")
    answer = rag.query(query, mode=mode)
    _print_context(answer)
    print("    answer:")
    print(f"      {answer.text}")
    print(f"    citations: {len(answer.citations)} chunk(s)")
    return answer


def _contrast_modes(rag: GraphRAG, query: str) -> None:
    """Run the same query through local, hybrid, and auto; summarise recall."""
    print(f"\n=== Q: {query} ===")
    entity_counts: dict[str, int] = {}
    chunk_counts: dict[str, int] = {}
    for mode in _MODES:
        answer = _run_mode(rag, query, mode)
        context = answer.context
        entity_counts[mode] = 0 if context is None else len(context.entities)
        chunk_counts[mode] = 0 if context is None else len(context.chunks)

    print("\n=== Recall comparison (entities / chunks retrieved) ===")
    for mode in _MODES:
        print(
            f"  {mode:<7} entities={entity_counts[mode]:<3} chunks={chunk_counts[mode]}"
        )
    print(
        "  RRF fusion in hybrid mode typically surfaces at least as many "
        "items as local, recovering lexical/thematic hits a vector-only "
        "walk would miss (ADR-017)."
    )


def main() -> None:
    """Ingest a corpus, then contrast local vs hybrid vs auto retrieval."""
    load_dotenv()
    settings = _build_settings()
    log.info("Using FalkorDB graph %r on %s", _GRAPH_NAME, settings.falkordb_host)

    rag = GraphRAG.with_defaults(settings=settings)
    rag.bootstrap_schema()
    _ingest_corpus(rag)

    # A broad, thematic question. "auto" should classify this as hybrid because
    # of the breadth cue word "compare" / its length, matching hybrid's result.
    _contrast_modes(
        rag,
        "Compare the SOLARK-9000 product with the overall energy storage market.",
    )

    # A short, entity-pointed question. "auto" should classify this as local,
    # so it stays cheap while hybrid still demonstrates wider fan-out.
    _contrast_modes(rag, "Who founded Helios Energy?")

    print("\nDone. Compare the per-mode entity/chunk counts and scores above.")


if __name__ == "__main__":
    main()
