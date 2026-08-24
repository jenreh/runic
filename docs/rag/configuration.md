# Configuration & deployment

`runic.rag` reads its entire runtime configuration from environment variables, validated into a single `RagSettings` object. This page is the reference: every `RUNIC_RAG_*` setting and its default, how to switch LLM/embedding providers and graph backends, how the schema is created in development versus production, and the `python -m runic.rag` CLI.

Settings load through [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). The env prefix is `RUNIC_RAG_` and matching is **case-insensitive**; a local `.env` at the repo root is read automatically. Two variables are deliberately **unprefixed** — `OPENAI_API_KEY` and `OLLAMA_BASE_URL` — so they line up with the conventions the OpenAI and Ollama clients already expect. Call `load_settings()` to get a validated `RagSettings` (it runs `dotenv.load_dotenv()` first), or pass `RagSettings(...)` explicitly to override fields in code.

```python
from runic.rag import RagSettings, load_settings

settings = load_settings()                 # reads .env + environment
settings = RagSettings(top_k=20)           # or override fields directly
```

---

## Settings reference

Every field below maps to a `RUNIC_RAG_<FIELD>` variable (the two credential exceptions are noted). Defaults mirror `.env.example` exactly. Set `0` on the cost knobs to mean "unlimited".

### LLM

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_LLM_PROVIDER` | Chat provider for extraction + answer synthesis (`openai` or `ollama`) | `openai` |
| `RUNIC_RAG_LLM_MODEL` | Chat model id | `gpt-5.4-nano` |

### Embeddings

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_EMBEDDING_PROVIDER` | Embedding provider (`openai` or `ollama`) | `openai` |
| `RUNIC_RAG_EMBEDDING_MODEL` | Embedding model id | `text-embedding-3-small` |
| `RUNIC_RAG_EMBEDDING_DIM` | Embedding dimension — must match the model | `1536` |
| `RUNIC_RAG_EMBED_BATCH_SIZE` | Max texts per embedding request at ingest (`<=0` → one request) | `128` |

### Credentials

| Variable | Meaning | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI key (**unprefixed**); required when a provider is `openai` | `None` |
| `RUNIC_RAG_OPENAI_BASE_URL` | OpenAI-compatible base URL (leave unset for `api.openai.com`) | `None` |
| `OLLAMA_BASE_URL` | Ollama endpoint (**unprefixed**), e.g. `http://localhost:11434/v1` | `None` |

### Backend

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_BACKEND` | Graph backend: `falkordb`, `neo4j`, `memgraph`, `arcadedb`, `age`, `neptune`, or `neptune_analytics` | `falkordb` |
| `RUNIC_RAG_FALKORDB_HOST` | FalkorDB host | `localhost` |
| `RUNIC_RAG_FALKORDB_PORT` | FalkorDB port | `6379` |
| `RUNIC_RAG_FALKORDB_GRAPH` | FalkorDB graph name | `runic_rag` |
| `RUNIC_RAG_NEO4J_URI` | Neo4j Bolt URI, e.g. `bolt://localhost:7687` | `None` |
| `RUNIC_RAG_NEO4J_USERNAME` | Neo4j username | `None` |
| `RUNIC_RAG_NEO4J_PASSWORD` | Neo4j password | `None` |
| `RUNIC_RAG_NEO4J_DATABASE` | Neo4j database | `neo4j` |

::: info
`memgraph`, `arcadedb`, `age`, `neptune`, and `neptune_analytics` carry their own `RUNIC_RAG_<BACKEND>_*` connection variables (host/port/database/username/password; `_GRAPH` for AGE; `_ENDPOINT`/`_REGION`/`_USE_IAM_AUTH` for Neptune; `_GRAPH_ID`/`_REGION` for Neptune Analytics). See `runic/rag/config.py` for the full list; FalkorDB and Neo4j are the primary, natively-accelerated backends.
:::

### Chunking

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_CHUNK_SIZE` | Target chunk size (characters) | `1200` |
| `RUNIC_RAG_CHUNK_OVERLAP` | Overlap between adjacent chunks | `200` |

### Resolution

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_RESOLVE_THRESHOLD` | Cosine similarity above which two mentions auto-merge | `0.92` |
| `RUNIC_RAG_TIEBREAK_LOW` | Lower bound of the ambiguous band | `0.82` |
| `RUNIC_RAG_TIEBREAK_HIGH` | Upper bound of the ambiguous band | `0.92` |
| `RUNIC_RAG_LLM_TIEBREAK` | Use an LLM to break ties inside the ambiguous band | `false` |

### Concurrency

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_CONCURRENCY` | Max concurrent LLM/embedding requests during ingest | `8` |
| `RUNIC_RAG_REQUESTS_PER_MINUTE` | Client-side rate limit (`0` = no limit) | `0` |

### Cost / budget

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_MAX_LLM_CALLS` | Hard cap on LLM calls per run (`0` = unlimited) | `0` |
| `RUNIC_RAG_MAX_TOKENS` | Hard cap on tokens per run (`0` = unlimited) | `0` |
| `RUNIC_RAG_GLEANING_PASSES` | Extra extraction passes per chunk to raise recall | `0` |
| `RUNIC_RAG_CACHE_DIR` | On-disk cache for LLM + embedding results | `.cache/runic-rag` |

### Retrieval

| Variable | Meaning | Default |
| --- | --- | --- |
| `RUNIC_RAG_MAX_HOPS` | Graph-expansion depth for the local walk | `2` |
| `RUNIC_RAG_TOP_K` | Retrieval breadth (candidates fetched per source) | `10` |

The budget caps span the whole run — ingestion *and* the query path (extraction, high-level keyword extraction, synthesis) draw from the same `max_llm_calls` / `max_tokens` budget. Exceeding it raises `BudgetExceededError`.

::: tip
Set `RUNIC_RAG_CACHE_DIR` to make re-ingestion cheap: re-running an unchanged document reuses cached LLM and embedding results instead of paying for them again.
:::

---

## Switching providers

By default both the LLM and the embedder talk to OpenAI. To run fully offline against [Ollama](https://ollama.com), switch **both** providers — embeddings default to OpenAI independently of the chat model, so flipping only `LLM_PROVIDER` still sends every embedding to OpenAI.

```bash
# Pull the models once:
ollama pull qwen2.5 && ollama pull nomic-embed-text

# Then point both providers at Ollama (.env or shell):
RUNIC_RAG_LLM_PROVIDER=ollama
RUNIC_RAG_LLM_MODEL=qwen2.5
RUNIC_RAG_EMBEDDING_PROVIDER=ollama
RUNIC_RAG_EMBEDDING_MODEL=nomic-embed-text
RUNIC_RAG_EMBEDDING_DIM=768
OLLAMA_BASE_URL=http://localhost:11434/v1
```

::: warning
`RUNIC_RAG_EMBEDDING_DIM` must match the embedding model — `1536` for `text-embedding-3-small`, `768` for `nomic-embed-text`. A mismatch surfaces as a vector-dimension error at query time, and changing the dimension after data exists means re-creating the vector index and re-embedding. Pick the dimension before you bootstrap.
:::

---

## Switching backends

`RUNIC_RAG_BACKEND` selects the graph store. FalkorDB (the default) and Neo4j are the primary backends and use native vector + fulltext procedures; `memgraph`, `arcadedb`, `age`, `neptune`, and `neptune_analytics` are also valid and fall back to a portable brute-force vector/fulltext path that works everywhere. The driverless path builds the driver for you from `settings.backend`:

```python
from runic.rag import GraphRAG, RagSettings

# FalkorDB on localhost — nothing else to wire.
rag = GraphRAG.with_defaults(settings=RagSettings())

# Neo4j — set the backend + connection in the environment or RagSettings.
rag = GraphRAG.with_defaults(
    settings=RagSettings(
        backend="neo4j",
        neo4j_uri="bolt://localhost:7687",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )
)
```

When you need control over the connection — a custom pool, an existing handle, or driver kwargs the facade does not set for you — construct the driver yourself with `create_driver` from `runic.ogm` and pass it in:

```python
from runic.ogm import create_driver
from runic.rag import GraphRAG, RagSettings

settings = RagSettings(falkordb_graph="my_app")
driver = create_driver(
    "falkordb",                 # or "neo4j", "memgraph", "arcadedb", "age",
                                # "neptune", "neptune_analytics"
    host=settings.falkordb_host,
    port=settings.falkordb_port,
    graph=settings.falkordb_graph,
)
rag = GraphRAG.with_defaults(driver, settings=settings)
```

::: info See also

- [OGM Quickstart](../ogm/quickstart.md) — `create_driver` and the driver/session model in full.
:::

---

## Schema lifecycle

The knowledge graph needs entity types and indexes — most importantly the vector index, whose dimension must equal `embedding_dim`. How you create them depends on the environment.

### Development

Call `bootstrap_schema()` once at startup. It is idempotent (safe on every run) and creates the vector index with the **real** `embedding_dim`:

```python
from runic.rag import GraphRAG, RagSettings

rag = GraphRAG.with_defaults(settings=RagSettings())
rag.bootstrap_schema()   # entity types + indexes, idempotent
```

::: warning
`bootstrap_schema()` raises `ValueError` if `embedding_dim <= 0` — a vector index cannot be created without a positive dimension. This is a precondition: set `RUNIC_RAG_EMBEDDING_DIM` to your model's real dimension before bootstrapping.
:::

### Production

For a tracked, replayable schema use `runic.migrate`: introspect the live graph into a baseline migration, then evolve it with hand-written revisions and gate CI on drift.

```bash
runic baseline    # introspect the graph -> a root migration
runic check       # CI gate: fail if models and graph have drifted
```

There is one gotcha to fix in the generated baseline. `SchemaManager.sync_schema` (and the introspection behind `runic baseline`) cannot know the embedding dimension, so it records vector indexes with a **placeholder dimension of 0**. `bootstrap_schema()` sidesteps this by always using the real `embedding_dim`; in a hand-written migration you must edit the generated root revision to set the vector dimension from `0` to the real value (e.g. `1536`) before applying it. See [schema](../migration/schema.md) for how index hints map to DDL across backends.

::: info See also

- [Migration](../migration/index.md) — versioned, replayable schema changes for production.
- [Schema management](../migration/schema.md) — `IndexManager` / `SchemaManager`, the vector-dimension placeholder, and per-backend DDL.
- [Migration Quickstart](../migration/quickstart.md) — `runic baseline`, revisions, and the `runic check` CI gate end to end.
:::

---

## CLI

`python -m runic.rag` is a thin wrapper over the facade verbs. It reads settings from the environment (including a local `.env`), wires the default adapter stack via `GraphRAG.with_defaults(settings=load_settings())`, and forwards to `bootstrap_schema()`, `ingest_document()` / `ingest_text()`, and `query()`.

```bash
python -m runic.rag bootstrap
# Schema bootstrapped.

python -m runic.rag ingest docs/whitepaper.pdf
# Ingested docs/whitepaper.pdf: 42 chunks, 88 entities, 61 relations, 130 mentions.

python -m runic.rag query "Who founded the company and when?" --mode hybrid
# <synthesized answer text>
#
# Citations:
# - [chunk-3] docs/whitepaper.pdf
```

`ingest` auto-detects `.txt`, `.md`, and `.pdf` and routes through the document adapters. `--mode` is one of `auto` (default), `local`, or `hybrid` — any other value raises `ValueError`.

::: warning
`ingest --source S` bypasses PDF/MD parsing and loads the file as **plain text** under the source tag `S`. Format auto-detection only happens on the plain `ingest <path>` (no `--source`) path, which calls `ingest_document()`. Pass a PDF without `--source` to get it parsed.
:::

---

## A .env example

Copy `.env.example` to `.env` and fill in your secrets. A minimal OpenAI + FalkorDB setup, with the Ollama local-mode block commented out:

```bash
# ── LLM + embeddings (OpenAI defaults) ──────────────────────────────
RUNIC_RAG_LLM_PROVIDER=openai
RUNIC_RAG_LLM_MODEL=gpt-5.4-nano
RUNIC_RAG_EMBEDDING_PROVIDER=openai
RUNIC_RAG_EMBEDDING_MODEL=text-embedding-3-small
RUNIC_RAG_EMBEDDING_DIM=1536

# ── Credentials (unprefixed; required when provider=openai) ──────────
OPENAI_API_KEY=sk-replace-me

# ── Graph backend (FalkorDB default) ────────────────────────────────
RUNIC_RAG_BACKEND=falkordb
RUNIC_RAG_FALKORDB_HOST=localhost
RUNIC_RAG_FALKORDB_PORT=6379
RUNIC_RAG_FALKORDB_GRAPH=runic_rag

# ── Cost control (0 = unlimited) ────────────────────────────────────
RUNIC_RAG_MAX_LLM_CALLS=0
RUNIC_RAG_CACHE_DIR=.cache/runic-rag

# ── Local mode: switch BOTH providers to Ollama (uncomment) ──────────
# RUNIC_RAG_LLM_PROVIDER=ollama
# RUNIC_RAG_LLM_MODEL=qwen2.5
# RUNIC_RAG_EMBEDDING_PROVIDER=ollama
# RUNIC_RAG_EMBEDDING_MODEL=nomic-embed-text
# RUNIC_RAG_EMBEDDING_DIM=768
# OLLAMA_BASE_URL=http://localhost:11434/v1
```

---

## Next steps

::: info See also

- [Quickstart](./quickstart.md) — the smallest end-to-end ingest-and-ask loop.
- [Retrieval & answers](./retrieval.md) — the `local` / `hybrid` / `auto` modes and how answers are grounded.
- [Evaluating quality](./evaluation.md) — measure faithfulness and relevancy as you tune these knobs.
- [API Reference](./api.md) — `RagSettings`, `GraphRAG`, and the value objects in full.
- [Migration](../migration/index.md) — productionize the schema with versioned migrations.
:::
