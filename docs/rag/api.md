# API Reference

> **Note:** This is a manually-maintained API reference. For the authoritative API, read the [source on GitHub](https://github.com/jenreh/runic/tree/main/runic/rag).

`runic.rag` is a thin Graph-RAG SDK layered on [`runic.ogm`](../ogm/api.md): it adds
entity/relation extraction, embeddings, graph storage, and hybrid (vector +
fulltext + graph-expansion) retrieval. The public surface is the `GraphRAG`
facade plus the domain value objects, configuration, ontology, OGM models,
default adapters, and ports needed to extend or test the pipeline. Everything
imports from `runic.rag`. For the end-to-end workflow, start with the
[quickstart](./quickstart.md); this page is the reference.

```python
from runic.rag import GraphRAG, Ontology, RagSettings
```

---

## GraphRAG facade

`runic.rag.facade.GraphRAG`

The single entry point. It hides all wiring: given a driver (or a prebuilt
store) plus its ports, it composes an ingestion service and a retrieval service
and exposes four verbs — `bootstrap_schema()`, `ingest_text()`,
`ingest_document()`, and `query()`. Construct it with `with_defaults()` for the
batteries-included path, or call the constructor directly to swap any stage.

### `with_defaults`

```python
@classmethod
def with_defaults(
    cls,
    driver: Any = None,
    *,
    settings: RagSettings | None = None,
    ontology: Ontology | None = None,
    document_parser: DocumentParser | None = None,
    document_chunker: DocumentChunker | None = None,
) -> GraphRAG: ...
```

Build a fully-wired `GraphRAG` with the production adapters. All arguments are
optional — the driverless form is the documented default:

- `driver` — `None` builds a driver from `settings.backend` (FalkorDB on
  localhost by default, otherwise Neo4j/Memgraph/ArcadeDB/AGE).
- `settings` — `None` calls `load_settings()` (reads the environment + `.env`).
- `ontology` — `None` uses `Ontology.default()`.
- `document_parser`, `document_chunker` — `None` (the default) keeps the
  built-in `ingest_document` path. Pass already-built file-oriented ports
  (e.g. from the [runic-rag-docling](./docling.md) add-on) to parse/chunk
  documents structure-aware. This path imports no document backend.

```python
from runic.rag import GraphRAG, RagSettings

rag = GraphRAG.with_defaults(settings=RagSettings())
```

::: info
To select and configure a backend explicitly (e.g. build a driver with
`create_driver(...)`), see [configuration](./configuration.md).
:::

### Constructor (extension seam)

```python
def __init__(
    self,
    driver_or_store: Any,
    *,
    ontology: Ontology,
    chunker: Chunker,
    extractor: Extractor,
    embedder: Embedder,
    resolver: EntityResolver,
    retrievers: dict[str, Retriever],
    reranker: Reranker,
    synthesizer: Synthesizer,
    settings: RagSettings,
    budget: BudgetGuard | None = None,
    document_parser: DocumentParser | None = None,
    document_chunker: DocumentChunker | None = None,
) -> None: ...
```

Every collaborator is an injected port, so the whole pipeline is swappable and
unit-testable with fakes. `driver_or_store` may be an OGM driver (wrapped in a
`GraphStore`) or an already-built store. `retrievers` maps a retriever name to a
`Retriever`; the planner expects the keys `"vector"`, `"fulltext"`, `"local"`,
and `"highlevel"`. `document_parser` and `document_chunker` are the optional
file-oriented ingestion ports (both default `None`); they are forwarded to the
ingestion service and only consulted by `ingest_document` — see [Ports](#ports).

### Verbs

| Method | Signature | Description |
|---|---|---|
| `bootstrap_schema` | `bootstrap_schema() -> None` | Create the entity types and indexes for the ontology. Idempotent. |
| `ingest_text` | `ingest_text(text: str, *, source: str) -> IngestionReport` | Ingest `text` tagged with the required `source`; return the report. |
| `ingest_document` | `ingest_document(path: str \| Path) -> IngestionReport` | Load and ingest a `.txt`/`.md`/`.pdf` file (auto-detected); return the report. |
| `query` | `query(q: str, *, mode: str = "auto") -> Answer` | Answer `q` using the configured retrievers; return a cited `Answer`. |

`mode` is one of `"auto"`, `"local"`, or `"hybrid"`; any other value raises
`ValueError`. `auto` is a cheap heuristic (not an LLM classifier): it picks
`local` when the query has 8 or fewer tokens and contains no broad-cue word
(`all`, `across`, `compare`, `overall`, `themes`, `trends`, `summarize`,
`summary`, `relationship`, `relationships`, `everything`), and `hybrid`
otherwise. See [retrieval](./retrieval.md) for what each mode does.

::: warning
`bootstrap_schema()` raises `ValueError` when `embedding_dim <= 0` — the vector
index needs a real dimension. Keep `RUNIC_RAG_EMBEDDING_DIM` aligned with your
embedding model (1536 for `text-embedding-3-small`).
:::

---

## Ontology

`runic.rag.ontology.Ontology`

Bundles the entity-type vocabulary with its backing OGM `Entity` subclasses.
The ontology drives both schema bootstrap and which types the extractor is
allowed to emit.

```python
def __init__(self, entity_models: list[type[Entity]] | None = None) -> None: ...
```

Construct directly with explicit `Entity` subclasses, or use the two factories.

| Member | Signature | Description |
|---|---|---|
| `default` | `Ontology.default() -> Ontology` | The generic built-in subtypes: `Person`, `Organization`, `Location`, `Concept`, `Product`, `Event`. |
| `from_types` | `Ontology.from_types(type_names: list[str]) -> Ontology` | Build a tuned vocabulary; reuses built-in subtypes by name, else generates one dynamically. |
| `entity_types` | `entity_types() -> list[str]` | Ordered list of entity-type names in this ontology. |
| `subtype_for` | `subtype_for(type: str) -> type[Entity]` | The `Entity` subclass for `type`; falls back to the base `Entity` for unknown names. |
| `schema_models` | `schema_models() -> list[type]` | All OGM models needed to bootstrap: base `Entity`, every subtype, `Chunk`, and `RelationEdge` (deduped, base-first). |

```python
from runic.rag import Ontology

generic = Ontology.default()
tuned = Ontology.from_types(["Company", "Executive", "Industry", "FinancialMetric", "Market"])
```

See [ontologies](./ontologies.md) for tuning guidance and custom subclasses.

---

## RagSettings & load_settings

`runic.rag.config.RagSettings`, `runic.rag.config.load_settings`

Strongly-typed runtime configuration via pydantic-settings. Field names mirror
the `RUNIC_RAG_*` environment variables; `OPENAI_API_KEY` and `OLLAMA_BASE_URL`
are read unprefixed.

```python
class RagSettings(BaseSettings): ...

def load_settings() -> RagSettings: ...
```

`load_settings()` calls `dotenv.load_dotenv()` first (so a local `.env` is
visible to pydantic-settings and to the OpenAI client), then returns a validated
`RagSettings`. Key defaults: `llm_model="gpt-5.4-nano"`,
`embedding_model="text-embedding-3-small"`, `embedding_dim=1536`,
`backend="falkordb"`, `top_k=10`, `max_hops=2`. The full environment table lives
in [configuration](./configuration.md).

---

## Domain value objects

`runic.rag.domain`

All domain value objects are **frozen pydantic v2 models** — immutable and
deliberately decoupled from the OGM node models (e.g. the domain `Chunk` is
distinct from the OGM `Chunk` node).

### Ingestion side

#### `Chunk`

A contiguous slice of source text produced by a chunker.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Stable chunk identifier. |
| `text` | `str` | The chunk text. |
| `seq` | `int` | Ordinal position within the source. |
| `source` | `str` | Origin tag (file path or caller-supplied source). |

#### `ExtractedEntity`

An entity surfaced by the extractor from a chunk.

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Surface name as extracted. |
| `type` | `str` | Entity-type name (from the ontology vocabulary). |
| `description` | `str` | Optional one-line description (default `""`). |

#### `ExtractedRelation`

A directed relation between two extracted entities (by name).

| Field | Type | Description |
|---|---|---|
| `source` | `str` | Source entity name. |
| `target` | `str` | Target entity name. |
| `rel_type` | `str` | Relation type label. |
| `description` | `str` | Optional description (default `""`). |
| `confidence` | `float` | Extractor confidence in `[0, 1]` (default `1.0`). |

#### `Extraction`

The full set of entities and relations extracted from one chunk.

| Field | Type | Description |
|---|---|---|
| `entities` | `list[ExtractedEntity]` | Extracted entities (default empty). |
| `relations` | `list[ExtractedRelation]` | Extracted relations (default empty). |

#### `IngestionReport`

`runic.rag.services.ingestion.IngestionReport`

Returned by `ingest_text()` and `ingest_document()` — frozen counts of what was
written this run. You receive it from the return value; it is not imported from
`runic.rag` directly.

| Field | Type | Description |
|---|---|---|
| `chunks` | `int` | Chunks persisted. |
| `entities` | `int` | Distinct entities upserted. |
| `relations` | `int` | Relation edges created. |
| `mentions` | `int` | Chunk→entity mention links created. |

### Retrieval side

#### `ScoredKey`

| Field | Type | Description |
|---|---|---|
| `key` | `str` | Canonical entity/chunk key. |
| `score` | `float` | Normalized similarity score in `[0, 1]`. |

#### `EntityHit`

An entity returned by retrieval, with its relevance score.

| Field | Type | Description |
|---|---|---|
| `canonical_key` | `str` | Canonical entity key. |
| `name` | `str` | Entity name. |
| `type` | `str` | Entity-type name. |
| `description` | `str` | Entity description. |
| `score` | `float` | Relevance score. |

#### `ChunkHit`

A source chunk returned by retrieval, with its relevance score.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Chunk id. |
| `text` | `str` | Chunk text. |
| `source` | `str` | Origin tag. |
| `score` | `float` | Relevance score. |

#### `RelationHit`

A relation edge discovered while expanding the entity neighbourhood.

| Field | Type | Description |
|---|---|---|
| `source_key` | `str` | Source entity key. |
| `target_key` | `str` | Target entity key. |
| `rel_type` | `str` | Relation type label. |
| `description` | `str` | Relation description. |

#### `RetrievalContext`

The assembled evidence for a query.

| Field | Type | Description |
|---|---|---|
| `query` | `str` | The originating query string. |
| `entities` | `list[EntityHit]` | Retrieved entities (default empty). |
| `chunks` | `list[ChunkHit]` | Retrieved source chunks (default empty). |
| `relations` | `list[RelationHit]` | Expanded relations (default empty). |

### Answer side

#### `Citation`

A reference to a source chunk supporting an answer.

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `str` | Id of the cited chunk. |
| `source` | `str` | Origin tag of the cited chunk. |
| `text` | `str` | The cited chunk text. |

#### `Answer`

The result of `query()`: a synthesized answer with its supporting evidence.

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The synthesized answer text. |
| `citations` | `list[Citation]` | Supporting citations (default empty). |
| `context` | `RetrievalContext \| None` | The evidence used, or `None`. |

::: info
`Answer.context` may be `None` — always guard for it before reading
`context.chunks` or `context.entities`.
:::

---

## OGM models

`runic.rag.models`

These map directly onto graph nodes and edges via [`runic.ogm`](../ogm/api.md).
Embedding fields are typed `Vector | None`, which drives `vecf32()` on FalkorDB
so the KNN index works.

### `Entity`

`Entity(Node, labels=["Entity"], primary_label="Entity")` — a canonical
knowledge-graph entity.

| Field | Declaration | Description |
|---|---|---|
| `canonical_key` | `Field(primary_key=True)` | Primary key. |
| `name` | `Field(index_type="FULLTEXT")` | Fulltext-indexed surface name. |
| `type` | `Field(index=True)` | Indexed entity-type name (in addition to the subtype label). |
| `description` | `Field(default="", index_type="FULLTEXT")` | Fulltext-indexed description. |
| `embedding` | `Field(default=None, index_type="VECTOR")` | `Vector \| None`; backs the vector index. |
| `related` | `Relation("RELATES_TO", direction="OUTGOING", target="Entity", edge_model=RelationEdge)` | Outgoing relations to other entities. |

**Subtypes** — `Person`, `Organization`, `Location`, `Concept`, `Product`,
`Event`. Each is an `Entity` subclass labelled `["Entity", "<Subtype>"]` with
`primary_label="Entity"`.

### `ChunkNode`

The OGM `Chunk` node, re-exported as `ChunkNode` to disambiguate it from the
frozen domain `Chunk`. A persisted source-text chunk and the entities it
mentions.

| Field | Declaration | Description |
|---|---|---|
| `id` | `Field(primary_key=True)` | Primary key. |
| `text` | `Field(index_type="FULLTEXT")` | Fulltext-indexed chunk text. |
| `source` | `Field(index=True)` | Indexed origin tag. |
| `seq` | `Field(default=0)` | Ordinal position. |
| `embedding` | `Field(default=None, index_type="VECTOR")` | `Vector \| None`; backs the vector index. |
| `mentions` | `Relation("MENTIONS", direction="OUTGOING", target="Entity")` | Entities this chunk mentions. |

```python
from runic.rag import ChunkNode  # OGM node
from runic.rag import Chunk      # frozen domain value object
```

### `RelationEdge`

`RelationEdge(Edge, type="RELATES_TO")` — the property model for a typed
relation between two entities.

| Field | Declaration | Description |
|---|---|---|
| `rel_type` | `Field(index=True)` | Indexed relation type label. |
| `description` | `Field(default="")` | Relation description. |
| `confidence` | `Field(default=1.0)` | Extractor confidence. |
| `source_chunk` | `Field(default="")` | Id of the chunk the relation came from. |

---

## Ports

`runic.rag.ports`

Every collaborator the services depend on is a `typing.Protocol` (all
`@runtime_checkable`), enabling constructor injection and trivial fakes in
tests. Pass your own implementation through the `GraphRAG` constructor to swap a
stage — see [Writing custom ports](./custom-ports.md) for the how-to and the
contract each port must honour.

| Port | Method | Description |
|---|---|---|
| `Chunker` | `split(text: str, *, source: str) -> list[Chunk]` | Split raw text into ordered domain chunks. |
| `DocumentParser` | `supports(source: str) -> bool`; `parse(path: str \| Path) -> str` | Optional, file-oriented: turn a document file into normalized text fed to the `Chunker`. |
| `DocumentChunker` | `supports(source: str) -> bool`; `chunk_document(path: str \| Path, *, source: str \| None = None) -> list[Chunk]` | Optional, file-oriented: read a document file once and emit ordered chunks directly. |
| `Extractor` | `extract(chunk: Chunk, *, entity_types: list[str]) -> Extraction` | Extract entities and relations from one chunk. |
| `Embedder` | `dimension -> int` (property); `embed(text: str) -> list[float]`; `embed_batch(texts: list[str]) -> list[list[float]]` | Turn text into dense vectors; batch order matches input. |
| `EntityResolver` | `canonical_key(entity: ExtractedEntity) -> str`; `find_duplicate(entity, embedding, store) -> str \| None` | Decide canonical identity and detect existing duplicates. |
| `Retriever` | `retrieve(query: str, *, top_k: int) -> RetrievalContext` | Build a retrieval context for a query. |
| `Reranker` | `rerank(query: str, contexts: list[RetrievalContext], *, top_k: int) -> RetrievalContext` | Fuse, reorder, and trim contexts into one. |
| `Synthesizer` | `synthesize(query: str, context: RetrievalContext) -> Answer` | Produce a cited answer from context. |
| `Writer` | `add_chunk(chunk_node)`; `upsert_entity(key, name, type, description, embedding)`; `relate(src_key, rel_type, dst_key, description, confidence, source_chunk)`; `mention(chunk_id, entity_key)` | One graph unit-of-work; changes commit when the context manager exits. |
| `GraphStore` | `bootstrap_schema()`; `writer() -> AbstractContextManager[Writer]`; `vector_search(...)`; `fulltext_search(...)`; `get_entities(keys)`; `expand(keys, *, max_hops)`; `chunks_for_entities(keys, *, limit)` | The backend-isolating graph port; hides dialect differences. |

`DocumentParser` and `DocumentChunker` are **optional**, file-oriented ports
consulted by `ingest_document` in the order `document_chunker`, then
`document_parser`, then the built-in loader — the first one whose `supports()`
returns `True` wins, and `ingest_text()` never touches them. Both default to
`None`; the core imports no document backend.

The concrete `GraphStore` adapter is also exported as `GraphStoreAdapter`
(`= runic.rag.store.GraphStore`) for advanced wiring.

---

## Default adapters

`runic.rag.adapters`

`with_defaults()` wires this production stack. Pass alternatives through the
constructor to override any of them.

| Port | Default adapter |
|---|---|
| `Chunker` | `ParagraphChunker` |
| `Extractor` | `PydanticAIExtractor` |
| `Embedder` | `OpenAIEmbedder` |
| `EntityResolver` | `TwoStageResolver` |
| `Retriever` (`"vector"`) | `VectorRetriever` |
| `Retriever` (`"fulltext"`) | `FulltextRetriever` |
| `Retriever` (`"local"`) | `LocalRetriever` |
| `Retriever` (`"highlevel"`) | `HighLevelRetriever` |
| `Reranker` | `RRFReranker` |
| `Synthesizer` | `PydanticAISynthesizer` |
| `GraphStore` | `store.GraphStore` (exported as `GraphStoreAdapter`) |

::: info
`CrossEncoderReranker` and `OllamaEmbedder` are exported, opt-in alternatives —
they are **not** wired by `with_defaults()`. Pass them to the constructor (or
set `RUNIC_RAG_EMBEDDING_PROVIDER=ollama` for the embedder) to use them.
:::

The `DocumentParser` and `DocumentChunker` ports have **no built-in core
adapter** — they are provided by the optional
[runic-rag-docling](./docling.md) add-on and injected via the `document_parser`
/ `document_chunker` parameters.

---

## Exceptions

`runic.rag.exceptions`

| Exception | Base | Raised when |
|---|---|---|
| `RagError` | `Exception` | Base class for all `runic.rag` errors. |
| `BudgetExceededError` | `RagError` | A cost budget (LLM calls or tokens) is exceeded. |
| `ConfigError` | `RagError` | Configuration is missing or invalid. |

---

## Next steps

::: info See also
- [Quickstart](./quickstart.md) — the smallest end-to-end loop.
- [Ingesting documents](./ingestion.md) — how the graph is built.
- [Retrieval & answers](./retrieval.md) — how questions are answered, mode by mode.
- [Designing & optimizing ontologies](./ontologies.md) — tune the entity vocabulary.
- [Configuration & deployment](./configuration.md) — the full `RUNIC_RAG_*` table and backend selection.
:::
