"""Docling via the explicit GraphRAG constructor — no build_graphrag (concept §9 A).

Where ``docling_quickstart.py`` uses the :func:`build_graphrag` one-liner, this
example wires the whole stack by hand through the :class:`GraphRAG` constructor
(the extension seam) and injects a :class:`DoclingChunker` as the
``document_chunker``. Build it yourself when you want to swap or tune individual
stages — a custom retriever, a different reranker, your own embedder — while
still letting Docling parse **and** chunk documents structure-aware in
``ingest_document``. The plain-text ``chunker`` (``ParagraphChunker``) stays in
place for the ``ingest_text`` path.

Prerequisites
-------------
* The Docling extra installed (heavy — pulls torch)::

      uv add 'runic-rag-docling[local]'

* A running FalkorDB on ``localhost:6379`` (the default backend)::

      docker run -p 6379:6379 -it --rm falkordb/falkordb:latest

* ``OPENAI_API_KEY`` exported (or placed in a local ``.env``) for the LLM and
  embeddings. To run fully local instead, set ``RUNIC_RAG_LLM_PROVIDER=ollama``
  and ``RUNIC_RAG_EMBEDDING_PROVIDER=ollama`` in your ``.env``.

Run it (pass your own document, or let it fall back to the bundled sample)::

    uv run python examples/docling_explicit_wiring.py path/to/whitepaper.pdf
"""
# ruff: noqa: T201 - example scripts print their results for the reader.

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from runic.ogm import create_driver
from runic.rag import (
    FulltextRetriever,
    GraphRAG,
    GraphStoreAdapter,
    HighLevelRetriever,
    LocalRetriever,
    Ontology,
    OpenAIEmbedder,
    ParagraphChunker,
    PydanticAIExtractor,
    PydanticAISynthesizer,
    RRFReranker,
    TwoStageResolver,
    VectorRetriever,
    load_settings,
)
from runic.rag.concurrency import BudgetGuard

from runic_rag_docling import DoclingChunker, DoclingSettings

# Default to this package's own README as a self-contained, always-present
# document when the user does not pass a path on the command line. Markdown is a
# Docling-supported format, so the example runs without any extra files.
_DEFAULT_DOC = Path(__file__).resolve().parents[1] / "README.md"


def main() -> None:
    """Wire GraphRAG by hand with Docling, ingest a document, then query it."""
    # 1. Load a local .env (OPENAI_API_KEY, any RUNIC_RAG_* / RUNIC_DOCLING_*).
    load_dotenv()

    # 2. Pick the document: a CLI arg if given, else the bundled README.
    doc_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _DEFAULT_DOC
    if not doc_path.exists():
        raise SystemExit(f"document not found: {doc_path}")

    settings = load_settings()
    ontology = Ontology.default()

    # 3. Build the driver and the store ONCE, then share the store with every
    #    retriever (passing the bare driver would leave you no store handle).
    driver = create_driver(
        "falkordb",
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph=settings.falkordb_graph,
    )
    store = GraphStoreAdapter(driver, settings, schema_models=ontology.schema_models())
    embedder = OpenAIEmbedder(settings)

    # 4. One budget spans ingestion AND the query path so max_llm_calls /
    #    max_tokens cap the whole run, exactly as with_defaults does internally.
    budget = BudgetGuard(
        max_llm_calls=settings.max_llm_calls, max_tokens=settings.max_tokens
    )

    # 5. Wire the facade explicitly. Everything here is the stock adapter except
    #    document_chunker — swap any single stage for your own port the same way.
    rag = GraphRAG(
        store,
        ontology=ontology,
        # Raw-string path (ingest_text) keeps the default paragraph chunker.
        chunker=ParagraphChunker(settings),
        # Document path (ingest_document): Docling parses + chunks the original
        # structure-aware. Use mode="server" + server_url for docling-serve.
        document_chunker=DoclingChunker(DoclingSettings(mode="local")),
        extractor=PydanticAIExtractor(settings),
        embedder=embedder,
        resolver=TwoStageResolver(settings),
        retrievers={
            "vector": VectorRetriever(store, embedder, settings),
            "fulltext": FulltextRetriever(store, settings),
            "local": LocalRetriever(store, embedder, settings),
            "highlevel": HighLevelRetriever(store, settings, budget=budget),
        },
        reranker=RRFReranker(),
        synthesizer=PydanticAISynthesizer(settings, budget=budget),
        settings=settings,
        budget=budget,
    )

    # 6. Create the entity types + indexes (idempotent — safe on every startup).
    rag.bootstrap_schema()

    # 7. Ingest the document: because a document_chunker is wired and supports()
    #    this path, Docling parses+chunks it directly (no Markdown re-parse).
    report = rag.ingest_document(doc_path)
    print(
        f"Ingested {doc_path.name}: {report.chunks} chunks, "
        f"{report.entities} entities, {report.relations} relations, "
        f"{report.mentions} mentions"
    )

    # 8. Ask a question. mode="auto" classifies the query and picks the retrieval
    #    strategy (local / hybrid / global) automatically.
    answer = rag.query("What is this document about?")

    # 9. The Answer carries the synthesized text plus the chunks it cites.
    print("\nAnswer:\n", answer.text)
    print("\nCitations:")
    for citation in answer.citations:
        print(f"  - [{citation.source}] {citation.text[:80]}...")


if __name__ == "__main__":
    main()
