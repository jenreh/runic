# Document parsing with Docling

The built-in document loaders in `runic.rag` are deliberately
dependency-light: they pull plain text out of `.txt`, `.md`, and `.pdf` files
and hand it to the heuristic `ParagraphChunker`. That is robust, but it is
*structure-blind* — it does not see headings, tables, or page layout, and it
cannot read a scanned PDF at all.

[Docling](https://github.com/docling-project/docling) (MIT) closes that gap. It
parses PDF/DOCX/PPTX/XLSX/HTML and images **structure-aware** — layout, tables,
and headings — into a `DoclingDocument`, and chunks that structured
representation with a heading- and table-aware `HybridChunker`. The result is
chunks that respect the document's real shape instead of splitting mid-table or
mid-section.

Docling is a heavy dependency (it pulls `torch`), so it does **not** live in the
`runic.rag` core. It ships as an **optional add-on**, `runic-rag-docling`, that
implements the core's two file-oriented ports — `DocumentParser` and
`DocumentChunker` — and is injected through the `GraphRAG` constructor. The core
itself imports no Docling and stays light; you opt in only when you need it.

::: info
This page assumes the file-oriented ports from
[Writing custom ports](./custom-ports.md). Docling is the reference
implementation of `DocumentChunker` (fused parse + chunk) and `DocumentParser`
(parse-only); the core defines the ports, the add-on supplies the heavy
implementation.
:::

---

## Installation

The add-on is a separate distribution with two mutually-exclusive extras — pick
the one that matches how you want to run Docling:

```bash
# In-process (default). Heavy — pulls torch (~3–5 GB). Parses + chunks locally.
uv add 'runic-rag-docling[local]'

# Lightweight client against a docling-serve instance. No torch on the client;
# just httpx + docling-core for client-side re-hydration and chunking.
uv add 'runic-rag-docling[server]'
```

::: info
The two extras are declared as conflicting (full `docling` + torch vs. the light
`docling-core` client), so install exactly one. The core `runic.rag` wheel and
CI are unaffected either way — nothing heavy leaks into the core.
:::

---

## When to use Docling

Reach for Docling when the document's **structure carries meaning** and the
plain-text loader would throw it away:

- **Complex or structured PDFs** — multi-column layouts, figures, and headings
  that the flat text extractor flattens or interleaves incorrectly.
- **Tables** — Docling reconstructs table structure so a row stays a row instead
  of collapsing into a run-on line.
- **Scanned documents / images** — OCR turns a scanned PDF or an image
  (`.png`, `.jpg`, `.tiff`) into text the built-in loader cannot read at all.
- **Office formats** — `.docx`, `.pptx`, `.xlsx` are first-class inputs.

Stay on the **built-in loader** when the input is plain text or simple Markdown:
it is dependency-light, instant, and there is no structure for Docling to
recover. Docling's value is structure; on a flat `.txt` file it buys you nothing
but a `torch` install.

The Docling adapters claim these suffixes (anything else falls back to the
built-in loader): `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.md`,
`.markdown`, `.adoc`, `.asciidoc`, `.epub`, `.png`, `.jpg`, `.jpeg`, `.tiff`,
`.bmp`.

---

## Local vs. server

Docling runs either **in-process** or behind the `docling-serve` HTTP service.
Both modes produce **identical chunks** — the server path re-hydrates the
lossless `DoclingDocument` JSON client-side and runs the *same* `HybridChunker`
— so the choice is purely operational.

| Aspect | Local | Server |
| --- | --- | --- |
| Client dependencies | heavy (`docling`, torch ~3–5 GB) | light (`httpx` + opt. `docling-core`) |
| Latency | immediate (in-process) | HTTP round-trip |
| Scaling | single process | central / horizontal |
| Operations | nothing to run | run a service / container |

**How to choose.** The default is **local** — there is nothing to run, you just
pay the dependency weight once. Switch to **server** when you want to keep the
client light (no torch in your app image), offload parsing onto dedicated
hardware, or share one parser across many workers.

Running `docling-serve` via Docker:

```bash
docker run -p 5001:5001 quay.io/docling-project/docling-serve:latest
```

Then point the add-on at it with `DoclingSettings(mode="server",
server_url="http://localhost:5001")` (plus `api_key=...` if the service is
protected — it is sent as the `X-Api-Key` header). The client uploads the file
to `POST /v1alpha/convert/file`, reads back `md_content` and `json_content`, and
chunks the re-hydrated document locally.

::: tip
Because the chunk result is identical, you can develop against local Docling and
deploy against a shared `docling-serve` without re-ingesting — the
content-addressed chunk ids match across both modes.
:::

---

## Usage

There are two ways to wire Docling in, mirroring the patterns in
[Writing custom ports](./custom-ports.md): the explicit `GraphRAG` constructor
(full control), and the add-on's `build_graphrag` one-liner (batteries
included).

### Variant A — inject `DoclingChunker` via the constructor

Wire `DoclingChunker` as the `document_chunker`. `ingest_document()` then routes
file paths to Docling for fused parse + chunk, while `ingest_text()` (a raw
string) keeps using the regular `chunker`. This scaffold mirrors the
custom-ports wiring exactly, adding just the one document port:

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
    ParagraphChunker,
    PydanticAIExtractor,
    PydanticAISynthesizer,
    RagSettings,
    RRFReranker,
    TwoStageResolver,
    VectorRetriever,
)
from runic.rag.concurrency import BudgetGuard

from runic_rag_docling import DoclingChunker, DoclingSettings  # ← add-on

settings = RagSettings(falkordb_graph="docling_demo")
ontology = Ontology.default()

driver = create_driver(
    "falkordb",
    host=settings.falkordb_host,
    port=settings.falkordb_port,
    graph=settings.falkordb_graph,
)
store = GraphStoreAdapter(driver, settings, schema_models=ontology.schema_models())
embedder = OpenAIEmbedder(settings)
budget = BudgetGuard(max_llm_calls=settings.max_llm_calls, max_tokens=settings.max_tokens)

rag = GraphRAG(
    store,
    ontology=ontology,
    chunker=ParagraphChunker(settings),                  # ingest_text path (raw string)
    document_chunker=DoclingChunker(DoclingSettings(mode="local")),  # ← fused parse+chunk
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
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")  # Docling parses + chunks the original
```

`DoclingChunker(settings=None, *, converter=None, hybrid_chunker=None)` builds
its converter from `settings.mode` when you do not inject one; the `converter`
and `hybrid_chunker` arguments exist so tests can fake Docling entirely (DIP).

### Variant B — the `build_graphrag` one-liner

`build_graphrag` mirrors `GraphRAG.with_defaults()` but injects the Docling
`document_chunker` for you — the whole batteries-included stack plus
structure-aware ingestion in two lines:

```python
from runic.rag import load_settings

from runic_rag_docling import DoclingSettings, build_graphrag

rag = build_graphrag(
    load_settings(),
    DoclingSettings(mode="server", server_url="http://localhost:5001"),
)
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")
```

`build_graphrag(settings, docling_settings=None, *, driver=None, ontology=None)`
forwards `driver` and `ontology` to `with_defaults` unchanged; omit
`docling_settings` to default to in-process `local` mode.

### Parser-only mode

If you want Docling's structure-aware *parsing* but prefer to keep the existing
`ParagraphChunker` (e.g. you have tuned `chunk_size` and want character-based
chunks over token-based ones), wire `DoclingParser` as the `document_parser`
instead of a `document_chunker`. `ingest_document()` then parses the file to
normalized Markdown with Docling and feeds that text to the regular chunker:

```python
from runic_rag_docling import DoclingParser, DoclingSettings

rag = GraphRAG(
    store,
    ontology=ontology,
    chunker=ParagraphChunker(settings),                 # still chunks the parsed text
    document_parser=DoclingParser(DoclingSettings(mode="local")),  # ← parse-only
    # ... the rest of the stack, exactly as in Variant A
    settings=settings,
    budget=budget,
)
```

::: info
The dispatch order in `ingest_document()` is: a matching `document_chunker`
wins (fused parse + chunk), else a matching `document_parser` (parse, then the
core chunker), else the built-in loader. Set **one** of the two — wiring both a
`DoclingChunker` and a `DoclingParser` means the chunker always takes a
supported file first.
:::

---

## Configuration

The add-on has its **own** settings model, `DoclingSettings`
([pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)),
fully independent of the core `RagSettings`. It reads from the environment with
the **`RUNIC_DOCLING_`** prefix (and an optional `.env`); every adapter accepts
either a `DoclingSettings` instance or explicit kwargs.

| Field | Env var | Meaning | Default |
| --- | --- | --- | --- |
| `mode` | `RUNIC_DOCLING_MODE` | `local` (in-process) or `server` (`docling-serve`) | `local` |
| `server_url` | `RUNIC_DOCLING_SERVER_URL` | `docling-serve` base URL, e.g. `http://localhost:5001` | `None` |
| `api_key` | `RUNIC_DOCLING_API_KEY` | sent as `X-Api-Key` when set (server mode) | `None` |
| `max_tokens` | `RUNIC_DOCLING_MAX_TOKENS` | `HybridChunker` token cap per chunk | `512` |
| `tokenizer` | `RUNIC_DOCLING_TOKENIZER` | HF tokenizer id; `None` → Docling's default | `None` |
| `merge_peers` | `RUNIC_DOCLING_MERGE_PEERS` | merge adjacent small peer chunks | `true` |
| `ocr` | `RUNIC_DOCLING_OCR` | local PDF OCR (server mode ignores it) | `false` |
| `timeout` | `RUNIC_DOCLING_TIMEOUT` | server HTTP timeout in seconds | `120.0` |

```python
from runic_rag_docling import DoclingSettings

# From the environment (RUNIC_DOCLING_*) + .env:
settings = DoclingSettings()

# Or override in code:
settings = DoclingSettings(mode="local", max_tokens=256, ocr=True)
```

::: warning
`DoclingSettings` is **not** the core `RagSettings`. The chunking knobs here
(`max_tokens`, `tokenizer`, `merge_peers`) are Docling's; the core's
`RUNIC_RAG_CHUNK_SIZE` / `RUNIC_RAG_CHUNK_OVERLAP` do **not** apply to the fused
`DocumentChunker` path — `DoclingChunker` deliberately bounds chunk size by
`max_tokens` instead. (They *do* still apply to the parser-only path, where the
core `ParagraphChunker` does the chunking.)
:::

---

## Best practices & operations

**Tokenizer and `max_tokens`.** The `HybridChunker`'s default tokenizer may
**download a Hugging Face model on first run** (network access required). For
reproducible or air-gapped environments, either set `tokenizer` to a model id
you already have cached, or pre-fetch the models with `docling models download`.
Tune `max_tokens` to your embedding model's input limit — chunks are capped by
tokens here, not characters.

**OCR is off by default.** OCR is expensive and only needed for scanned pages;
leave `ocr=False` unless a document is image-only. Note that OCR is a *local*
concern — `ServerDoclingConverter` does not forward it.

**macOS multiprocessing caveat.** Local Docling has occasionally shown
multiprocessing/OCR instability on macOS. If you hit it, prefer **server mode**
(the heavy work runs in the container, your client stays light) or keep OCR off.

**Pin against the running `docling-serve` API version.** The server endpoint
path (`/v1alpha/convert/file`) is encapsulated in `ServerDoclingConverter`;
verify it against the version of `docling-serve` you actually run, since the
service's API surface can shift between releases.

**Idempotent re-ingest.** `DoclingChunker` reuses the core's content-addressed
chunk-id scheme byte-for-byte (`sha256("{source}|{seq}|{text[:64]}")`), so
re-ingesting the same file produces the same ids and the idempotent `MERGE`
never duplicates nodes — exactly like the built-in chunker.

**Budgets are unaffected.** Parsing and chunking are local, CPU/GPU-bound steps
with **no LLM calls**, so they draw nothing from the `max_llm_calls` /
`max_tokens` budget. The budget still governs extraction, embedding, and
synthesis downstream, exactly as for the built-in path.

**Errors are typed.** Both adapters raise `runic.rag.RagError` on failure —
including a clear install hint if you wire a Docling adapter without the matching
extra installed (e.g. *"install with: `uv add 'runic-rag-docling[local]'`"*).

### Best-practices checklist

::: tip

- **Use Docling only for structured inputs** (complex PDFs, tables, scans,
  Office docs); keep plain text/Markdown on the dependency-light built-in loader.
- **Pick local vs. server on operations, not output** — chunks are identical;
  choose by client weight, latency, and scaling.
- **Set `tokenizer` (or run `docling models download`)** before an air-gapped
  run so the first chunk does not try to fetch an HF model.
- **Match `max_tokens` to your embedder's input limit** — the fused path caps by
  tokens, and the core `chunk_size` does not apply to it.
- **Leave `ocr=False`** unless a document is scanned/image-only.
- **On macOS, prefer server mode** if local multiprocessing/OCR misbehaves.
- **Pin to the running `docling-serve` API version** before relying on the
  server path in production.
- **Trust idempotent re-ingest** — content-addressed ids match the built-in
  chunker, so re-running a document never duplicates the graph.
:::

---

## Next steps

::: info See also

- [examples/docling_quickstart.py](https://github.com/jenreh/runic/blob/main/packages/runic-rag-docling/examples/docling_quickstart.py) — the runnable one-liner walkthrough (Variant B).
- [examples/docling_explicit_wiring.py](https://github.com/jenreh/runic/blob/main/packages/runic-rag-docling/examples/docling_explicit_wiring.py) — the same flow wired by hand through the `GraphRAG` constructor, no `build_graphrag` (Variant A).
- [Writing custom ports](./custom-ports.md) — the `DocumentParser` / `DocumentChunker` ports and the constructor extension seam Docling plugs into.
- [Ingesting documents](./ingestion.md) — how `ingest_document()` dispatches and how chunks become a graph.
- [Configuration & deployment](./configuration.md) — the core `RUNIC_RAG_*` settings that govern everything downstream of parsing.
:::
