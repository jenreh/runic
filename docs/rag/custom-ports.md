# Writing custom ports

Every stage of the `runic.rag` pipeline is a **port** — a `typing.Protocol`
describing one collaborator the services depend on. The chunker, the extractor,
the embedder, the retrievers, the reranker, the synthesizer, and the graph store
are all ports, and each ships with a default adapter. Because the services
depend on the *protocol* and never on a concrete class (the Dependency Inversion
Principle), you can replace any stage with your own implementation without
touching the rest of the pipeline. This page is the how-to: what a port is, how
to implement one correctly, how to wire it in, and — most importantly — what to
keep in mind so your adapter behaves like the one it replaces.

The constructor of [`GraphRAG`](./api.md#graphrag-facade) is the **extension
seam**: every collaborator is an injected argument. `with_defaults()` is just
the batteries-included path that builds the production adapters for you. To swap
a stage you call the constructor directly with your own port in its place.

---

## The eleven ports

All ports live in `runic.rag.ports` and are exported from `runic.rag`. Each is
`@runtime_checkable`, so `isinstance(obj, Chunker)` works as a coarse sanity
check (it tests for method *presence*, not signatures).

| Port | Method(s) | Swap it to… |
| --- | --- | --- |
| `Chunker` | `split(text, *, source) -> list[Chunk]` | change how documents are segmented (headings, fixed windows, semantic splits) |
| `Extractor` | `extract(chunk, *, entity_types) -> Extraction` | use a different model, prompt, or a rules-based extractor |
| `Embedder` | `dimension`; `embed(text)`; `embed_batch(texts)` | a different embedding provider or a local model |
| `EntityResolver` | `canonical_key(entity)`; `find_duplicate(entity, embedding, store)` | change how surface variants collapse onto one node |
| `Retriever` | `retrieve(query, *, top_k) -> RetrievalContext` | a new retrieval strategy (registered under a name) |
| `Reranker` | `rerank(query, contexts, *, top_k) -> RetrievalContext` | a different fusion/scoring scheme |
| `Synthesizer` | `synthesize(query, context) -> Answer` | change the answer prompt, model, or format |
| `GraphStore` | `bootstrap_schema()`, `writer()`, `vector_search()`, `fulltext_search()`, `get_entities()`, `expand()`, `chunks_for_entities()` | an entirely different persistence layer (rarely needed) |
| `Writer` | `add_chunk()`, `upsert_entity()`, `relate()`, `mention()` | the unit-of-work yielded by a custom `GraphStore` |
| `DocumentParser` | `supports(source)`; `parse(path) -> str` | a structure-aware parse of a document *file* into text/markdown, which then feeds the existing `Chunker` |
| `DocumentChunker` | `supports(source)`; `chunk_document(path, *, source) -> list[Chunk]` | a fused parse + chunk of a document *file*, fully structure-aware |

The full method signatures and the value objects they exchange are in the
[API reference](./api.md#ports).

The last two ports are **optional** and **file-oriented**, and they behave
differently from the other nine. Both default to `None`, so the stock pipeline
never has them; you opt in by injecting one through the constructor. They are
consulted **only by `ingest_document(path)`** — the `ingest_text(text, *,
source)` path always uses the plain `Chunker` and is completely unchanged.
When you supply them, `ingest_document` tries them in a fixed order: the
`DocumentChunker` first (fused parse + chunk), then the `DocumentParser` (parse
to text, then hand off to the `Chunker`), and finally the built-in loader for
any path neither `supports`. Each `supports(source)` decides per file extension
(`.pdf`, `.docx`, …) whether that adapter claims the file; unclaimed suffixes
fall through to the next stage, so wiring one in never disturbs the formats it
does not handle.

::: info
`DocumentParser` and `DocumentChunker` exist because some parsers are natively
*document → text* or *document → chunks*, not *text → chunks* like `Chunker`.
The next section shows the canonical case — Docling — and why forcing it through
`Chunker` would throw away the very structure it extracts.
:::

---

## How a port works

A port is a **structural** protocol, so implementing one is deliberately
low-ceremony:

- **No base class to inherit.** You don't subclass anything. An object satisfies
  `Chunker` the moment it has a `split(self, text, *, source)` method with a
  matching shape — that is all the type checker and the facade require.
  Inheriting the protocol (`class HeadingChunker(Chunker): ...`) is *allowed* and
  documents intent, but it is optional.
- **No registry.** There is no decorator and nothing to register. You construct
  your adapter yourself and hand it to the `GraphRAG` constructor.
- **The domain value objects are the contract currency.** Ports exchange the
  frozen pydantic models in `runic.rag.domain` — `Chunk`, `Extraction`,
  `RetrievalContext`, `Answer`, and friends. Your `split` returns real `Chunk`
  objects; your `synthesize` returns a real `Answer`. Match those types exactly.
- **You own construction.** The facade never builds your adapter — it only calls
  its methods. So your `__init__` can take whatever dependencies you like
  (settings, a client, a model handle); inject them when you wire it in.

::: tip
Match the signature *precisely*, including keyword-only arguments. `split` takes
`source` after a `*`, so it must be passed by keyword — `split(text,
source=src)`, never `split(text, src)`. The services always call ports with the
documented keyword arguments.
:::

---

## Example: a custom chunker

`Chunker` is the simplest port — it has one method, no external dependencies, and
returns plain domain objects. Here is a chunker that splits Markdown into one
chunk per heading section instead of the default paragraph-packing strategy:

```python
import hashlib
import re

from runic.rag import Chunk

_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
_ID_TEXT_PREFIX = 64


class HeadingChunker:
    """Split Markdown into one Chunk per heading section."""

    def split(self, text: str, *, source: str) -> list[Chunk]:
        sections = self._split_on_headings(text)
        return [
            Chunk(id=_chunk_id(source, seq, body), text=body, seq=seq, source=source)
            for seq, body in enumerate(sections)
        ]

    @staticmethod
    def _split_on_headings(text: str) -> list[str]:
        starts = [match.start() for match in _HEADING.finditer(text)]
        if not starts:
            stripped = text.strip()
            return [stripped] if stripped else []
        bounds = [*starts, len(text)]
        sections = (text[bounds[i] : bounds[i + 1]].strip() for i in range(len(starts)))
        return [section for section in sections if section]


def _chunk_id(source: str, seq: int, text: str) -> str:
    """A deterministic, content-addressed chunk id (mirrors the default)."""
    payload = f"{source}|{seq}|{text[:_ID_TEXT_PREFIX]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

The single most important detail here is the **stable, content-addressed id**.
Ingestion writes every node with `MERGE`, so re-ingesting the same document must
produce the same chunk ids — otherwise each run creates *new* chunk nodes and
the graph fills with duplicates. Derive the id from the content (and `source` +
`seq`), never from a counter that resets or anything random.

::: warning
A chunker that emits very large sections can hand text to the embedder that
exceeds the embedding model's token limit. The default `ParagraphChunker`
respects `chunk_size` for exactly this reason. If your strategy can produce big
chunks, cap their size or split oversized sections further.
:::

---

## Example: a custom synthesizer

`Synthesizer` is the retrieval-side counterpart: it turns the assembled
`RetrievalContext` into a cited `Answer`. This one is *extractive* — it returns
the top source chunks verbatim with citations and never calls an LLM, which
makes it fully deterministic and offline:

```python
from runic.rag import Answer, Citation, RetrievalContext


class ExtractiveSynthesizer:
    """Return the top source chunks verbatim, with citations. No LLM."""

    def __init__(self, *, max_chunks: int = 3) -> None:
        self._max_chunks = max_chunks

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        chunks = context.chunks[: self._max_chunks]
        text = "\n\n".join(chunk.text for chunk in chunks) or "No relevant context."
        citations = [
            Citation(chunk_id=chunk.id, source=chunk.source, text=chunk.text)
            for chunk in chunks
        ]
        return Answer(text=text, citations=citations, context=context)
```

Two contract points to copy: build `Citation` objects from the chunks you
actually used (that is what makes the answer traceable), and pass the `context`
back on the `Answer` so callers can inspect the evidence.

If your synthesizer *does* call an LLM, remember it runs **outside** the
ingestion cache and rate limiter — those wrap only extraction and embedding. You
are responsible for your own budgeting. Accept the shared `BudgetGuard` and gate
the call the way `HighLevelRetriever` does:

```python
def synthesize(self, query: str, context: RetrievalContext) -> Answer:
    if self._budget is not None:
        self._budget.check()              # raises BudgetExceededError if over cap
    result = self._agent.run_sync(...)    # your LLM call
    if self._budget is not None:
        self._budget.record(llm_calls=1, tokens=estimate_tokens(query))
    ...
```

---

## Example: document-aware ports with Docling

The two document ports are not academic — they exist for exactly one shape of
problem, and [Docling](https://github.com/docling-project/docling) is the
canonical case. Docling parses PDF, DOCX, PPTX, XLSX, HTML, and images into a
structured `DoclingDocument` — preserving layout, tables, and heading hierarchy
— and then chunks *that structure* with its `HybridChunker`. It is natively
*document → chunks*, never *text → chunks*.

That is why it needs `DocumentChunker` rather than the text `Chunker`. To drive
Docling through `Chunker.split(text)` you would first flatten the
`DoclingDocument` to Markdown, then re-parse that Markdown back into chunks —
discarding the table and heading structure Docling just worked to recover, and
parsing the document twice. The dedicated port lets Docling parse the original
**once** and emit `Chunk` objects **directly** from the structured document, with
no round-trip. (See ADR-019 for the port decision and ADR-021 for the fused,
no-re-parse adapter.)

Here is the shape of a `DocumentChunker` backed by Docling. It claims files by
suffix, parses each one once into a `DoclingDocument`, walks the
`HybridChunker`, contextualizes every raw chunk (headings and captions are
prepended), and wraps the result in a domain `Chunk` with the same stable,
content-addressed id the built-in chunker uses:

```python
import logging
from pathlib import Path
from typing import Any

from runic.rag import Chunk, RagError

log = logging.getLogger(__name__)

# Lowercase suffixes Docling parses structure-aware; `str.endswith` takes a tuple.
_SUPPORTED_SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md")
_ID_TEXT_PREFIX = 64


class DoclingChunker:
    """Fused parse + chunk via Docling. Implements runic.rag DocumentChunker."""

    def __init__(self, *, converter: Any, hybrid_chunker: Any) -> None:
        self._converter = converter        # injected: DoclingDocument from a path (DIP)
        self._hybrid = hybrid_chunker      # injected: Docling HybridChunker

    def supports(self, source: str) -> bool:
        return source.lower().endswith(_SUPPORTED_SUFFIXES)

    def chunk_document(self, path: str | Path, *, source: str | None = None) -> list[Chunk]:
        src = source or str(path)
        try:
            doc = self._converter.document_from_path(path)  # ORIGINAL → DoclingDocument
        except Exception as exc:  # wrap provider failures as a typed error
            raise RagError(f"docling failed to parse {src}") from exc
        chunks: list[Chunk] = []
        for seq, raw in enumerate(self._hybrid.chunk(doc)):  # directly on the structure
            body = self._hybrid.contextualize(raw)           # prepend headings/captions
            chunks.append(
                Chunk(id=_make_chunk_id(src, seq, body), text=body, seq=seq, source=src)
            )
        log.debug("docling chunked %s into %d chunks", src, len(chunks))
        return chunks


def _make_chunk_id(source: str, seq: int, text: str) -> str:
    """Mirror the runic.rag default id scheme byte-for-byte → idempotent re-ingest."""
    import hashlib

    payload = f"{source}|{seq}|{text[:_ID_TEXT_PREFIX]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

This reuses the same contract points as every other port on this page: a
**stable, content-addressed id** (identical to the default formula, so a
re-ingested file `MERGE`s onto the same chunk nodes instead of duplicating),
chunks emitted in **reading order**, sizes bounded by the chunker's
`max_tokens`, **typed errors** (`RagError`, wrapping the provider exception),
and house style throughout — annotated methods, `logger.debug`, no f-strings in
log calls.

You wire it in through the same constructor seam, but as the `document_chunker`
argument rather than `chunker`. The plain `Chunker` stays in place for the
`ingest_text` path; `DoclingChunker` is consulted only when you call
`ingest_document` with a file it `supports`:

```python
rag = GraphRAG(
    store,
    ontology=ontology,
    chunker=ParagraphChunker(settings),            # ingest_text path (raw strings) — unchanged
    document_chunker=DoclingChunker(               # ← opt-in, file path → structure-aware chunks
        converter=converter,
        hybrid_chunker=hybrid,
    ),
    extractor=PydanticAIExtractor(settings),
    embedder=embedder,
    resolver=TwoStageResolver(settings),
    retrievers=retrievers,
    reranker=RRFReranker(),
    synthesizer=PydanticAISynthesizer(settings, budget=budget),
    settings=settings,
    budget=budget,
)
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")     # Docling parses + chunks the original directly
```

::: tip
You do not have to write this adapter yourself. It ships, production-ready, as
the optional **`runic-rag-docling`** package — including a `DoclingParser`
(the `DocumentParser` variant for *parse-only* use with the built-in
`ParagraphChunker`), a local-or-server converter strategy, and a
`build_graphrag(...)` one-liner that wires Docling into the default stack. The
sketch above is deliberately trimmed to show the *port contract*; see
[Docling integration](./docling.md) for setup, the local-vs-server modes, and
operational best practices.
:::

---

## Wiring custom ports in

The explicit constructor takes the **whole** set of ports — there is no
partial-override helper. To swap one or two stages, reproduce the
`with_defaults()` wiring and substitute your adapters. The scaffold below mirrors
the production stack exactly, swapping in the two custom ports from above:

```python
from runic.ogm import create_driver
from runic.rag import (
    FulltextRetriever,
    GraphRAG,
    GraphStoreAdapter,
    HighLevelRetriever,
    LocalRetriever,
    Ontology,
    OpenAIEmbedder,
    PydanticAIExtractor,
    RagSettings,
    RRFReranker,
    TwoStageResolver,
    VectorRetriever,
)
from runic.rag.concurrency import BudgetGuard

settings = RagSettings(falkordb_graph="custom_demo")
ontology = Ontology.default()

# Build the store once and share it with every retriever.
driver = create_driver(
    "falkordb",
    host=settings.falkordb_host,
    port=settings.falkordb_port,
    graph=settings.falkordb_graph,
)
store = GraphStoreAdapter(driver, settings, schema_models=ontology.schema_models())
embedder = OpenAIEmbedder(settings)

# One budget spans ingestion AND the query path (see below).
budget = BudgetGuard(max_llm_calls=settings.max_llm_calls, max_tokens=settings.max_tokens)

rag = GraphRAG(
    store,
    ontology=ontology,
    chunker=HeadingChunker(),                       # ← custom
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
    synthesizer=ExtractiveSynthesizer(),            # ← custom
    settings=settings,
    budget=budget,
)
rag.bootstrap_schema()
```

A few things this scaffold makes explicit:

- **Build the store yourself** (`GraphStoreAdapter`, the exported alias of
  `runic.rag.store.GraphStore`) so the retrievers can share the same handle. You
  *could* pass the bare driver as the first argument and let the facade wrap it,
  but then you have no store reference to give the retrievers.
- **Share one `BudgetGuard`** across ingestion and the query path so
  `max_llm_calls` / `max_tokens` cap the whole run rather than each component in
  isolation — exactly what `with_defaults()` does internally.
- Everything you don't customize is the stock adapter, constructed the same way
  `with_defaults()` constructs it.

---

## Custom retrievers and the mode planner

`Retriever` is special because the `RetrievalService` looks retrievers up **by
name** in the `retrievers` dict. The planner only ever runs four keys —
`"vector"`, `"fulltext"`, `"local"`, and `"highlevel"` — and a name it does not
recognise is silently skipped:

- **To replace a strategy**, register your adapter under an existing key. A
  custom retriever wired in as `"vector"` is run wherever the built-in vector
  retriever would have run (hybrid mode and the auto-classifier's hybrid branch).
- **Adding a brand-new key alone does nothing** — no built-in mode references it,
  so it never runs. Hook a new strategy in by registering it under one of the
  four planned keys (or by composing it into one).

A retriever reads exclusively through the injected `GraphStore` — it never
touches a backend directly. The store gives you `vector_search` and
`fulltext_search` (returning `ScoredKey`s with normalised `[0, 1]` scores),
`get_entities` to hydrate them, `expand` to walk the neighbourhood, and
`chunks_for_entities` to attach provenance. Build a `RetrievalContext` from those
and return it; the reranker fuses your context with the others by **rank**, so
exact score magnitudes matter less than their order — but keep scores normalised
so a swapped-in reranker still behaves.

---

## Replacing the graph store

`GraphStore` and `Writer` are the only **backend-aware** ports — they hide the
dialect differences between FalkorDB, Neo4j, and the other drivers. You almost
never need to reimplement them: the store is *already* swappable by changing
`RUNIC_RAG_BACKEND` or passing a different driver, which gives you all five
supported backends for free. See [configuration](./configuration.md#switching-backends).

Reimplement `GraphStore` only to target persistence the OGM does not cover. If
you do, honour these contracts so the ingestion pipeline keeps working:

- **`writer()` is a unit of work.** It returns a context manager yielding a
  `Writer`. Every `add_chunk` / `upsert_entity` / `relate` / `mention` stages a
  change; commit them when the context exits cleanly and roll back on exception.
  Ingestion wraps a whole document in one writer.
- **Writes are idempotent.** Re-ingesting the same content must not duplicate
  nodes or edges — implement upserts as `MERGE`-equivalent operations keyed on
  the canonical key / id.
- **Honour the score conventions.** `vector_search` and `fulltext_search` return
  normalised `[0, 1]` similarity; `get_entities` may hydrate with a placeholder
  score that retrievers overlay with the real seed score.
- **`bootstrap_schema()` is idempotent** and must size the vector index to the
  real `embedding_dim`.
- **Quote the `label` and `prop` you are handed.** Both are interpolated into
  Cypher, so a graph whose embedding property is called `count` — or whose label
  is `Match` — must still work. The built-in store backtick-quotes them for
  identifier positions and passes them through
  `runic.cypher.escape_string()` where a procedure takes them as a string
  literal. Apache AGE reads an unquoted `n.count` as the aggregate function and
  rejects the whole statement.

---

## What to keep in mind

The checklist that separates a drop-in port from a subtly-broken one:

- **Honour the contract, not just the signature.** Matching the method shape is
  necessary but not sufficient. Reproduce the *behaviour*: `Chunker` returns
  chunks in reading order; `Embedder.embed_batch` returns vectors in the **same
  order** as its input; retrieval scores are normalised `[0, 1]`.
- **Keep ids deterministic.** Content-address chunk ids and canonical keys so the
  idempotent `MERGE` writes never duplicate on re-ingest. Random or sequential
  ids defeat the cache and the dedup.
- **Match the embedder dimension.** A custom `Embedder` must return vectors whose
  length equals `settings.embedding_dim`, and its `dimension` property must agree
  — the vector index is sized to that number at bootstrap. A mismatch surfaces as
  a vector error at query time.
- **Mind the cross-cutting concerns.** The services wrap extraction and embedding
  with the cache, rate limiter, and `BudgetGuard`. A port that makes its own
  LLM/network calls (a custom synthesizer or an LLM-driven retriever) runs
  *outside* that machinery — budget and rate-limit it yourself, sharing the
  injected `BudgetGuard`.
- **Make the extractor thread-safe.** Extraction runs concurrently across chunks
  in a thread pool (`parallel_map`), so `Extractor.extract` must hold no shared
  mutable state. The other stages run single-threaded.
- **Depend on the narrowest port (ISP).** Ask only for what you use. The
  `FulltextRetriever` takes no embedder; the resolver depends on the slim
  `VectorSearcher` slice of the store, not the whole surface. Narrow ports are
  easier to fake and harder to misuse.
- **Raise typed errors.** Surface failures as `RagError` (or `ConfigError` /
  `BudgetExceededError`) and wrap provider exceptions —
  `raise RagError(...) from exc` — the way the built-in adapters do. Don't
  swallow errors into empty results.
- **Keep backend knowledge in the store.** Only `GraphStore` / `Writer` know
  dialects. Every other port reaches the graph *through* the injected store.
- **Match house style.** Type-annotate every method, default logs to
  `logger.debug`, and never use f-strings in logger calls — your adapter should
  read like the ones it sits beside.

---

## Testing custom ports

Because ports are protocols, a custom adapter is unit-testable in isolation and
you can fake the rest of the pipeline. Test the port directly against its
contract, and use the fakes in `tests/runic/rag/fakes.py` to exercise it inside
the services without a live backend or network.

```python
from runic.rag import Chunk
from runic.rag.ports import Chunker


def test_heading_chunker_is_a_chunker_and_is_stable():
    chunker = HeadingChunker()
    assert isinstance(chunker, Chunker)  # structural sanity check

    text = "# A\nalpha\n\n## B\nbeta"
    first = chunker.split(text, source="doc")
    second = chunker.split(text, source="doc")

    assert [c.text for c in first] == ["# A\nalpha", "## B\nbeta"]
    assert all(isinstance(c, Chunk) for c in first)
    # Deterministic ids → idempotent re-ingest.
    assert [c.id for c in first] == [c.id for c in second]
```

::: info
`isinstance(obj, SomePort)` only checks that the methods *exist* — it does not
verify their signatures or behaviour. Treat it as a smoke test; the real
guarantee comes from asserting the contract, as above.
:::

---

## Next steps

::: info See also

- [API Reference](./api.md#ports) — every port's exact signature and the value objects they exchange.
- [Docling integration](./docling.md) — the document ports in production: structure-aware parsing, local vs. server, best practices.
- [Ingesting documents](./ingestion.md) — how the chunker, extractor, embedder, and resolver compose at ingest time.
- [Retrieval & answers](./retrieval.md) — how the retrievers, reranker, and synthesizer compose at query time.
- [Configuration & deployment](./configuration.md) — swapping providers and backends without writing a port at all.

:::
