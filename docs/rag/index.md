# Graph-RAG

`runic.rag` is a thin Graph-RAG SDK built on `runic.ogm` and `runic.migrate`.
It extracts entities and relations from your documents into a knowledge graph,
then answers questions over that graph with hybrid (vector + fulltext + graph
expansion) retrieval and inline citations. The whole pipeline sits behind one
`GraphRAG` facade and runs on FalkorDB or Neo4j out of the box.

## Graph-RAG

- [What is Graph-RAG?](./concepts.md) — The big picture: how documents become a graph and how that graph answers questions.
- [Quickstart](./quickstart.md) — Install `runic.rag`, ingest a document, and ask your first question — all on one page.
- [Ingesting documents](./ingestion.md) — How the graph is built: chunking, extraction, embedding, and entity resolution.
- [Retrieval & answers](./retrieval.md) — How questions are answered: the `local`, `hybrid`, and `auto` modes, and the `Answer` shape.
- [Designing & optimizing ontologies](./ontologies.md) — Tune the entity vocabulary to your domain for sharper extraction and retrieval.
- [Evaluating quality](./evaluation.md) — Measure faithfulness, relevancy, and recall with deepeval before you ship.
- [Configuration & deployment](./configuration.md) — Every `RagSettings` knob, backend selection, and the dev-to-prod schema lifecycle.
- [Writing custom ports](./custom-ports.md) — Swap any pipeline stage — chunker, extractor, retriever, synthesizer — with your own adapter, and what to keep in mind when you do.
- [API Reference](./api.md) — `runic.rag` — the facade, domain objects, ports, and default adapters.

---
