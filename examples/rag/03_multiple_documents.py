"""Example 3 — Ingesting multiple documents with shared entities.

This example ingests FOUR distinct in-repo documents that deliberately share
entities (people, organizations, products) while coming from different sources.
It demonstrates the two things that make a *graph* RAG different from a flat
vector store:

  1. **Incremental MERGE / entity deduplication.** Each document is ingested in
     its own ``ingest_text`` call. Entities that recur across documents (e.g.
     "Ada Lovelace" or "Analytical Engine") collapse onto a single canonical
     node via the resolver + idempotent MERGE writes (ADR-004/015) — they are
     NOT duplicated per source.

  2. **Per-source provenance.** Every chunk keeps its ``source`` tag, and every
     ``Chunk-[:MENTIONS]->Entity`` edge records which document mentioned the
     entity. A cross-document query therefore returns citations that span
     multiple sources, even though the underlying entities are shared.

The default backend is FalkorDB on localhost:6379 (using a graph name unique to
this example so it never collides with the other examples).

Prerequisites:
  * A running FalkorDB:  docker run -p 6379:6379 -it --rm falkordb/falkordb
  * An OpenAI key in your environment / .env:  OPENAI_API_KEY=sk-...
    (extraction + embeddings + answer synthesis call the live LLM)

Run it:
    uv run python examples/rag/03_multiple_documents.py
"""
# ruff: noqa: T201 - examples print their output to stdout for the reader.

from __future__ import annotations

import logging

from dotenv import load_dotenv

from runic.rag import GraphRAG, RagSettings, load_settings

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# A graph name unique to this example so each example owns its own subgraph.
_GRAPH_NAME = "runic_rag_ex03"


# ---------------------------------------------------------------------------
# The corpus: four distinct documents with overlapping entities.
#
# Notice how "Ada Lovelace", "Charles Babbage", and the "Analytical Engine"
# recur across several documents. After ingestion each is ONE canonical node,
# yet every mention keeps the provenance of the document it came from.
# ---------------------------------------------------------------------------

# Source 1 — a biography note. Introduces Ada Lovelace + Charles Babbage.
DOC_BIOGRAPHY = """\
Ada Lovelace was a 19th-century mathematician widely regarded as the first
computer programmer. She collaborated closely with Charles Babbage, the
inventor of the Analytical Engine, an early mechanical general-purpose computer.

Working from Babbage's designs, Lovelace wrote what is now recognised as the
first algorithm intended to be carried out by a machine. Her notes on the
Analytical Engine went far beyond Babbage's own, describing how the machine
could manipulate symbols and not merely crunch numbers.
"""

# Source 2 — a machine-focused doc. Re-mentions the Analytical Engine + Babbage
# (shared with DOC_BIOGRAPHY) and adds the Difference Engine.
DOC_MACHINE = """\
The Analytical Engine was designed by Charles Babbage as a programmable
mechanical computer. It featured a "mill" for arithmetic and a "store" for
holding numbers, mirroring the modern separation of CPU and memory.

Babbage had earlier built the Difference Engine, a special-purpose calculator
for polynomial tables. The Analytical Engine was a far more ambitious follow-up:
it was Turing-complete in principle, decades before Alan Turing formalised the
idea of universal computation.
"""

# Source 3 — a legacy / influence doc. Re-mentions Ada Lovelace and Alan Turing
# (shared) and introduces the Ada programming language honouring Lovelace.
DOC_LEGACY = """\
Ada Lovelace's contribution was largely overlooked for over a century. Interest
revived in the 20th century as computing matured and historians revisited her
notes on the Analytical Engine.

In 1980 the United States Department of Defense named a new programming
language "Ada" in her honour. Alan Turing, whose work on computability defined
the theoretical limits of machines, is often discussed alongside Lovelace as a
founding figure of computer science.
"""

# Source 4 — a modern doc. Re-mentions Alan Turing (shared) and adds an entirely
# separate cluster (Grace Hopper, COBOL) so the graph has distinct subgraphs.
DOC_MODERN = """\
Grace Hopper was a computer scientist and US Navy rear admiral who pioneered
machine-independent programming languages. She is credited with popularising
the term "debugging" and led the team that developed COBOL.

Hopper's drive toward human-readable code echoes Ada Lovelace's much earlier
insight that machines could process more than numbers. Like Alan Turing, Hopper
is celebrated as one of the most influential figures in early computing.
"""

# Map each document to a stable, human-readable source identifier. The source
# string is what shows up in citations, so make it meaningful.
CORPUS: dict[str, str] = {
    "lovelace_biography.txt": DOC_BIOGRAPHY,
    "analytical_engine.txt": DOC_MACHINE,
    "lovelace_legacy.txt": DOC_LEGACY,
    "modern_pioneers.txt": DOC_MODERN,
}


def _build_settings() -> RagSettings:
    """Load settings from the environment, pinning this example's graph name."""
    settings = load_settings()
    return settings.model_copy(update={"falkordb_graph": _GRAPH_NAME})


def _ingest_corpus(rag: GraphRAG) -> None:
    """Ingest every document in its own call, printing the per-source report.

    Because writes are idempotent MERGEs, entities shared across documents are
    deduplicated: the *cumulative* set of distinct entities grows more slowly
    than the per-document totals would suggest.
    """
    print("\n=== Ingesting corpus (incremental, one call per document) ===")
    total_chunks = 0
    for source, text in CORPUS.items():
        report = rag.ingest_text(text, source=source)
        total_chunks += report.chunks
        print(
            f"  {source:<24} "
            f"chunks={report.chunks}  entities={report.entities}  "
            f"relations={report.relations}  mentions={report.mentions}"
        )
    print(
        f"  {'TOTAL':<24} chunks written across {len(CORPUS)} sources: {total_chunks}"
    )
    print(
        "  (entities recurring across documents — e.g. Ada Lovelace, the "
        "Analytical Engine — MERGE onto one canonical node.)"
    )


def _show_cross_document_answer(rag: GraphRAG, question: str) -> None:
    """Run one cross-document query and print its answer + spanning citations."""
    print(f"\n=== Q: {question} ===")
    # "hybrid" fans out across vector + fulltext + high-level retrieval so the
    # answer can draw on every document, not just the closest one.
    answer = rag.query(question, mode="hybrid")
    print("\nAnswer:")
    print(f"  {answer.text}")

    print("\nCitations (note how they span multiple source documents):")
    if not answer.citations:
        print("  (no citations returned)")
    sources_seen: set[str] = set()
    for citation in answer.citations:
        sources_seen.add(citation.source)
        snippet = citation.text.replace("\n", " ").strip()
        if len(snippet) > 80:
            snippet = f"{snippet[:80]}…"
        print(f"  - [{citation.source}] {snippet}")
    print(f"\n  distinct sources cited: {len(sources_seen)} of {len(CORPUS)}")


def _show_shared_entities(rag: GraphRAG, question: str) -> None:
    """Print the retrieved entities to make entity sharing visible.

    The retrieval context exposes the canonical entities behind the answer; an
    entity reached from several documents appears exactly once here, proving the
    dedup worked while provenance lives on the chunk citations.
    """
    print(f"\n=== Retrieved entities for: {question} ===")
    answer = rag.query(question, mode="hybrid")
    context = answer.context
    if context is None or not context.entities:
        print("  (no entities in retrieval context)")
        return
    for entity in context.entities:
        print(
            f"  - {entity.name} ({entity.type}) "
            f"key={entity.canonical_key} score={entity.score:.4f}"
        )
    if context.relations:
        print("\n  relations traversed in the knowledge graph:")
        for relation in context.relations:
            print(
                f"    {relation.source_key} -[{relation.rel_type}]-> "
                f"{relation.target_key}"
            )


def main() -> None:
    """Ingest several documents, then query across all of them."""
    load_dotenv()
    settings = _build_settings()
    log.info("Using FalkorDB graph %r on %s", _GRAPH_NAME, settings.falkordb_host)

    # GraphRAG.with_defaults() wires the full production pipeline from settings:
    # paragraph chunker, pydantic-ai extractor, OpenAI embedder, two-stage
    # resolver, the four retrievers, the RRF reranker, and the synthesizer.
    rag = GraphRAG.with_defaults(settings=settings)

    # Idempotent: creates entity types + indexes (vector index uses the REAL
    # embedding dimension, never the placeholder 0).
    rag.bootstrap_schema()

    _ingest_corpus(rag)

    # A question whose answer requires evidence from more than one document.
    _show_cross_document_answer(
        rag,
        "How is Ada Lovelace connected to the Analytical Engine and Alan Turing?",
    )

    # A second question pulling on the separate Grace Hopper / COBOL cluster
    # plus the shared "early computing" theme that bridges the documents.
    _show_shared_entities(
        rag,
        "Compare the contributions of Ada Lovelace and Grace Hopper.",
    )

    print("\nDone. Re-running this script MERGEs onto the same nodes (no dupes).")


if __name__ == "__main__":
    main()
