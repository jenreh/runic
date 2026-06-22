# Quickstart

`runic.rag` builds a knowledge graph from your text and answers natural-language
questions over it — with citations back to the source. This page walks the
smallest end-to-end loop: install, connect, ingest one short document, and ask a
question. The example uses FalkorDB, the default backend; to swap in another
graph store you change only the settings or the driver — see
[configuration](./configuration.md).

---

## Installation

```bash
uv add "runic-py[graphrag,falkordb]"   # or: pip install "runic-py[graphrag,falkordb]"
```

The `graphrag` extra pulls in the LLM, embedding, and document-parsing
dependencies; `falkordb` adds the backend driver (swap for `neo4j` to target
Neo4j instead). Start a local FalkorDB instance for this example:

```bash
docker run -p 6379:6379 falkordb/falkordb
```

`runic.rag` calls OpenAI for extraction, embeddings, and answer synthesis by
default, so set your key — either export it or drop it in a local `.env`:

```bash
export OPENAI_API_KEY=sk-...
```

::: tip
Set `RUNIC_RAG_CACHE_DIR` (e.g. in your `.env`) to cache LLM and embedding
results, so re-ingesting unchanged text is cheap while you iterate.
:::

---

## Connect

Build the facade with `GraphRAG.with_defaults()`. Pass a `RagSettings` with a
dedicated graph name so this example stays isolated, and the default generic
ontology:

```python
from runic.rag import GraphRAG, Ontology, RagSettings

rag = GraphRAG.with_defaults(
    settings=RagSettings(falkordb_graph="rag_quickstart"),
    ontology=Ontology.default(),
)
```

`with_defaults()` wires the full production adapter stack — paragraph chunker,
pydantic-ai extractor, OpenAI embedder, two-stage resolver, the retrievers, RRF
reranker, and synthesizer — from your settings. Because you did not pass a
driver, it builds the FalkorDB driver itself from `settings.backend`.
`Ontology.default()` provides the generic entity types `Person`,
`Organization`, `Location`, `Concept`, `Product`, and `Event` — see
[concepts](./concepts.md) for what an ontology is and [ontologies](./ontologies.md)
for tuning it to your domain.

---

## Bootstrap the schema

```python
rag.bootstrap_schema()
```

This creates the entity types and indexes — including the vector index, sized to
the real `embedding_dim` (1536 for the default `text-embedding-3-small`). It is
idempotent, so it is safe to call on every startup.

::: warning
`bootstrap_schema()` raises `ValueError` if `embedding_dim <= 0`, and the vector
index dimension must match your embedding model. A mismatch breaks similarity
search — keep `RUNIC_RAG_EMBEDDING_DIM` in sync with the model.
:::

---

## Ingest

Feed in a document. `ingest_text()` requires a `source` label, which becomes the
provenance recorded on every citation:

```python
report = rag.ingest_text(
    "Ada Lovelace worked with Charles Babbage on the Analytical Engine.",
    source="inline-demo",
)
print(
    f"Ingested: {report.chunks} chunks, {report.entities} entities, "
    f"{report.relations} relations, {report.mentions} mentions"
)
```

Ingestion runs the pipeline chunk -> extract entities/relations -> embed ->
resolve duplicates -> write the graph, and returns an `IngestionReport` with the
write counts (`chunks`, `entities`, `relations`, `mentions`). See
[ingesting documents](./ingestion.md) for how each stage works and how to ingest
files with `ingest_document()`.

---

## Ask

Query the graph in natural language:

```python
answer = rag.query("Who was the first computer programmer and why?")

print(answer.text)
print("\nCitations:")
for citation in answer.citations:
    print(f"  - [{citation.source}] {citation.text[:80]}...")
```

`query()` returns an `Answer` carrying the synthesized `text` and the source
chunks it relied on as `citations` — each `Citation` exposes `source` and `text`
(and a `chunk_id`). The retrieval mode defaults to `auto`, a cheap heuristic that
picks a focused `local` walk for short, entity-pointed questions and a broader
`hybrid` search otherwise. See [retrieval & answers](./retrieval.md) for the
modes and how evidence is gathered.

---

## Next steps

::: info See also
- [What is Graph-RAG?](./concepts.md) — the mental model: ontology, the graph, and how retrieval grounds answers.
- [Ingesting documents](./ingestion.md) — how the graph is built, stage by stage, and ingesting files.
- [Retrieval & answers](./retrieval.md) — `local` / `hybrid` / `auto` modes and how citations are produced.
- [examples/rag/01_quickstart.py](https://github.com/jenreh/runic/blob/main/examples/rag/01_quickstart.py) — the full runnable script behind this page.
:::
