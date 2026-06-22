"""Docling quickstart: structure-aware ingestion in one wiring call (concept §9 B).

This mirrors the core RAG quickstart but swaps the document path's chunker for
Docling: :func:`build_graphrag` wires the full batteries-included stack and
injects a :class:`DoclingChunker` as the ``document_chunker``, so
``ingest_document`` parses **and** chunks the original PDF/DOCX structure-aware
(layout, tables, headings) instead of re-parsing Markdown.

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

    uv run python examples/docling_quickstart.py path/to/whitepaper.pdf
"""
# ruff: noqa: T201 - example scripts print their results for the reader.

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from runic.rag import load_settings

from runic_rag_docling import DoclingSettings, build_graphrag

# Default to this package's own README as a self-contained, always-present
# document when the user does not pass a path on the command line. Markdown is a
# Docling-supported format, so the example runs without any extra files.
_DEFAULT_DOC = Path(__file__).resolve().parents[1] / "README.md"


def main() -> None:
    """Ingest a document via Docling, then ask a question about it."""
    # 1. Load a local .env (OPENAI_API_KEY, any RUNIC_RAG_* / RUNIC_DOCLING_*).
    load_dotenv()

    # 2. Pick the document: a CLI arg if given, else the bundled README.
    doc_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _DEFAULT_DOC
    if not doc_path.exists():
        raise SystemExit(f"document not found: {doc_path}")

    # 3. Build the default stack with Docling as the document chunker. Settings
    #    come from the environment via load_settings(); local in-process mode
    #    keeps the example dependency-light beyond the docling extra itself.
    settings = load_settings()
    rag = build_graphrag(settings, DoclingSettings(mode="local"))

    # 4. Create the entity types + indexes (idempotent — safe on every startup).
    rag.bootstrap_schema()

    # 5. Ingest the document: Docling parses+chunks the original, then the
    #    default pipeline extracts entities/relations, embeds, resolves, writes.
    report = rag.ingest_document(doc_path)
    print(
        f"Ingested {doc_path.name}: {report.chunks} chunks, "
        f"{report.entities} entities, {report.relations} relations, "
        f"{report.mentions} mentions"
    )

    # 6. Ask a question. mode="auto" classifies the query and picks the retrieval
    #    strategy (local / hybrid / global) automatically.
    answer = rag.query("What is this document about?")

    # 7. The Answer carries the synthesized text plus the chunks it cites.
    print("\nAnswer:\n", answer.text)
    print("\nCitations:")
    for citation in answer.citations:
        print(f"  - [{citation.source}] {citation.text[:80]}...")


if __name__ == "__main__":
    main()
