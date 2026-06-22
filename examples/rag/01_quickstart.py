"""Quickstart: the ~10-line Graph-RAG happy path (concept §7).

This is the batteries-included flow: point :class:`GraphRAG` at a graph driver,
bootstrap the schema, ingest a document, and ask a question. ``with_defaults``
wires the full production adapter stack (paragraph chunker, pydantic-ai
extractor, OpenAI embedder, two-stage resolver, the four retrievers, RRF
reranker, pydantic-ai synthesizer) from your environment.

Prerequisites
-------------
* A running FalkorDB on ``localhost:6379`` (the default backend).
  ``docker run -p 6379:6379 -it --rm falkordb/falkordb:latest``
* ``OPENAI_API_KEY`` exported (or placed in a local ``.env``) for the LLM and
  embeddings. To run fully local instead, set ``RUNIC_RAG_LLM_PROVIDER=ollama``
  and ``RUNIC_RAG_EMBEDDING_PROVIDER=ollama`` in your ``.env``.

Run it::

    uv run python examples/rag/01_quickstart.py
"""
# ruff: noqa: T201 - example scripts print their results for the reader.

from __future__ import annotations

from dotenv import load_dotenv

from runic.ogm.driver.factory import create_driver
from runic.rag import GraphRAG, Ontology, RagSettings

# A tiny inline document so the example is self-contained (no files needed).
_DOC = """\
Ada Lovelace worked with Charles Babbage on the Analytical Engine in London.
She is regarded as the first computer programmer for her notes on the machine,
which described an algorithm to compute Bernoulli numbers.
"""


def main() -> None:
    """Run the end-to-end quickstart against a local FalkorDB graph."""
    # 1. Load a local .env (OPENAI_API_KEY, any RUNIC_RAG_* overrides).
    load_dotenv()

    # 2. Pick a dedicated graph for this example so it stays isolated. Switching
    #    backends is a one-line change: create_driver("neo4j", ...) instead.
    settings = RagSettings(falkordb_graph="rag_quickstart")
    driver = create_driver(
        "falkordb",
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph=settings.falkordb_graph,
    )

    # 3. Build the fully-wired facade with the default generic ontology
    #    (Person, Organization, Location, Concept, Product, Event).
    rag = GraphRAG.with_defaults(driver, settings=settings, ontology=Ontology.default())

    # 4. Create the entity types + indexes (vector index gets the REAL embedding
    #    dimension). Idempotent — safe to call on every startup.
    rag.bootstrap_schema()

    # 5. Ingest the document: chunk -> extract entities/relations -> embed ->
    #    resolve duplicates -> write the knowledge graph. Returns write counts.
    report = rag.ingest_text(_DOC, source="inline-demo")
    print(
        f"Ingested: {report.chunks} chunks, {report.entities} entities, "
        f"{report.relations} relations, {report.mentions} mentions"
    )

    # 6. Ask a question. mode="auto" classifies the query and picks the
    #    retrieval strategy (local / hybrid / global) automatically.
    answer = rag.query("Who was the first computer programmer and why?")

    # 7. The Answer carries the synthesized text plus the chunks it cites.
    print("\nAnswer:\n", answer.text)
    print("\nCitations:")
    for citation in answer.citations:
        print(f"  - [{citation.source}] {citation.text[:80]}...")

    # Productionization (the runic baseline path): in dev, bootstrap_schema()
    # calls SchemaManager.sync_schema() to create indexes on the fly. For a
    # versioned, reviewable schema, run `runic baseline -m "graph-rag baseline"`
    # to generate the root migration, then bump the placeholder vector
    # `dimension` from 0 to settings.embedding_dim in the generated revision.


if __name__ == "__main__":
    main()
