# runic.rag — Graph-RAG examples

Runnable, self-contained examples for the **`runic.rag`** Graph-RAG SDK. Each
script ingests text into a graph (entities + relations + source chunks) and then
answers natural-language questions with citations, using the
[`GraphRAG`](../../runic/rag/facade.py) facade.

The design, decisions, and architecture behind these examples are documented in
the concept spec: [`spec/runic-graph-rag-concept.md`](../../spec/runic-graph-rag-concept.md).

---

## Prerequisites

1. **An OpenAI API key.** Extraction, embedding, and answer synthesis call the
   OpenAI API by default. Put it in your shell or in a `.env` at the repo root:

   ```bash
   export OPENAI_API_KEY=sk-...
   # or:  cp .env.example .env   &&   edit .env
   ```

   Every script loads `.env` via `dotenv` before reading settings, and guards
   with a clear message if the key is missing.

2. **A running FalkorDB** on `localhost:6379` (the default backend). The repo
   ships a compose file:

   ```bash
   docker compose -f docker-compose.test.yml up -d falkordb
   ```

   Each example uses its own graph name, so they never clobber one another.

3. **Dependencies installed.** The Graph-RAG extras (`pydantic-ai-slim[openai]`,
   `pydantic-settings`, `pymupdf`, `tiktoken`) are part of the project. Run
   examples with `uv` so they resolve against the project environment:

   ```bash
   uv run python examples/rag/01_quickstart.py
   ```

Configuration is driven by `RUNIC_RAG_*` environment variables (see
[`.env.example`](../../.env.example)); the most relevant knobs:

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_LLM_MODEL` | Chat model for extraction + synthesis | `gpt-5.4-nano` |
| `RUNIC_RAG_EMBEDDING_MODEL` | Embedding model | `text-embedding-3-small` |
| `RUNIC_RAG_EMBEDDING_DIM` | Embedding dimension (must match the model) | `1536` |
| `RUNIC_RAG_EMBED_BATCH_SIZE` | Texts per `embed_batch` request at ingest | `128` |
| `RUNIC_RAG_MAX_LLM_CALLS` | Hard cap on LLM calls per ingest (`0` = ∞) | `0` |
| `RUNIC_RAG_TOP_K` | Retrieval breadth | `10` |
| `RUNIC_RAG_MAX_HOPS` | Graph-expansion depth | `2` |

> **Optional local mode.** Set `RUNIC_RAG_LLM_PROVIDER=ollama` **and**
> `RUNIC_RAG_EMBEDDING_PROVIDER=ollama` (plus `RUNIC_RAG_EMBEDDING_MODEL`/`_DIM`
> for a local embedder, e.g. `nomic-embed-text` / `768`) to run fully offline
> against an Ollama endpoint — no OpenAI key required. Embeddings default to
> OpenAI, so the embedding provider must be switched too. See `.env.example`.

---

## The examples

Run any of them with `uv run python examples/rag/<file>`.

| # | File | What it demonstrates |
| --- | --- | --- |
| 1 | [`01_quickstart.py`](01_quickstart.py) | The smallest end-to-end loop: `GraphRAG.with_defaults()`, ingest a short text, ask a question, print the cited answer. |
| 2 | [`02_custom_ontology.py`](02_custom_ontology.py) | Swap the generic ontology for a domain-specific one via `Ontology.from_types([...])` to get better-typed entities. |
| 3 | [`03_multiple_documents.py`](03_multiple_documents.py) | Ingest several documents into one graph and watch entity resolution merge cross-document mentions of the same entity. |
| 4 | [`04_manager_magazin_pdf.py`](04_manager_magazin_pdf.py) | **Flagship.** Ingest a real, complex German business-magazine PDF and run an A/B comparison of the **generic vs. a tuned** ontology on the same text. |
| 5 | [`05_hybrid_retrieval.py`](05_hybrid_retrieval.py) | Contrast the retrieval modes (`local` vs `hybrid` vs `auto`) on the same graph and question. |
| 6 | [`06_evaluation.py`](06_evaluation.py) | Score answer + retrieval quality with [deepeval](https://github.com/confident-ai/deepeval) (faithfulness, answer relevancy, contextual recall) over a small golden set. |

### Flagship: `04_manager_magazin_pdf.py`

This is the example to read if you only read one. It:

- Loads a **bounded page range** of a large PDF
  (`runic.rag.adapters.documents.load_pdf_pages`), defaulting to a modest
  ~8-page slice so a run is cheap; a clearly-commented switch
  (`INGEST_WHOLE_DOC` / `MM_INGEST_WHOLE_DOC=1`) ingests the whole magazine.
- Caps cost with a `BudgetGuard` (via `RUNIC_RAG_MAX_LLM_CALLS` / the
  `MM_MAX_LLM_CALLS` override), so it stays affordable by default.
- Ingests the **same slice twice** — once with `Ontology.default()` into graph
  `mm_default`, once with a tuned business/finance ontology (Company, Executive,
  Industry, FinancialMetric, Product, Market, Person, Location) into graph
  `mm_tuned` — then answers the same business question against both and prints a
  **side-by-side comparison**: entity counts per type, typed coverage, and the
  answer with citations.

```bash
docker compose -f docker-compose.test.yml up -d falkordb
export OPENAI_API_KEY=sk-...
uv run python examples/rag/04_manager_magazin_pdf.py

# Ingest a different slice, or the whole document:
MM_PAGE_FIRST=10 MM_PAGE_LAST=18 uv run python examples/rag/04_manager_magazin_pdf.py
MM_INGEST_WHOLE_DOC=1 MM_MAX_LLM_CALLS=2000 \
    uv run python examples/rag/04_manager_magazin_pdf.py
```

Point it at your own PDF with `MM_PDF_PATH=/path/to/file.pdf`.

---

## Concept: ontology optimization

An **ontology** is the set of hard *entity types* the extractor is told to look
for (plus the OGM models that back them). It is the single highest-leverage knob
for extraction quality.

- `Ontology.default()` ships generic types — `Person`, `Organization`,
  `Location`, `Concept`, `Product`, `Event`. Great for getting started, but on a
  business magazine almost everything collapses into `Organization`/`Concept`.
- `Ontology.from_types([...])` builds a **tuned** vocabulary. Telling the
  extractor about `Company`, `Executive`, `Industry`, `FinancialMetric`, and
  `Market` makes it place nodes into meaningful, queryable buckets.

Why it matters: relations carry a generic `RELATES_TO` type and rely on entity
types for meaning, and retrieval can filter/expand by type. Better types ⇒
cleaner graph neighbourhoods ⇒ sharper, better-grounded answers — with no model
change and no extra LLM passes. Example 4 makes this difference visible.

## Concept: retrieval modes

`GraphRAG.query(question, mode=...)` selects how evidence is gathered before the
answer is synthesized:

- **`local`** — a focused neighbourhood walk: find the most relevant entities,
  then expand their graph neighbourhood (up to `max_hops`) and pull the chunks
  that mention them. Best for pointed, entity-centric questions.
- **`hybrid`** — fan out across **vector** similarity, **fulltext** search, and
  **high-level** graph expansion, then fuse the results with Reciprocal Rank
  Fusion (RRF) reranking. Best for broad or thematic questions.
- **`auto`** (default) — a light classifier picks `local` for short,
  entity-pointed questions and `hybrid` for broader ones.

Under the hood the graph store issues backend-native KNN/fulltext procedures
(FalkorDB or Neo4j) and normalizes scores into a comparable `[0, 1]` range, so
the same retrieval code works across backends.

---

## Troubleshooting

- **"OPENAI_API_KEY is not set"** — export the key or add it to `.env`.
- **Connection refused / FalkorDB unreachable** — start it with
  `docker compose -f docker-compose.test.yml up -d falkordb` and confirm it
  listens on `localhost:6379`.
- **`Vector dimension mismatch`** — `RUNIC_RAG_EMBEDDING_DIM` must match your
  embedding model (1536 for `text-embedding-3-small`). The examples create the
  vector index with the real dimension on bootstrap.
- **A run feels expensive** — lower the page range / `MAX_LLM_CALLS`, or set a
  `RUNIC_RAG_CACHE_DIR` so re-ingesting unchanged text reuses cached LLM and
  embedding results.
