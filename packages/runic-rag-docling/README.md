# runic-rag-docling

Optional [Docling](https://github.com/docling-project/docling) adapters that
implement the `runic.rag` file-oriented ports `DocumentParser` and
`DocumentChunker`. Docling parses PDF/DOCX/PPTX/XLSX/HTML/images structure-aware
(layout, tables, headings) and chunks the structured document directly — no
Markdown re-parse. The heavy Docling dependency lives only in this add-on; the
`runic.rag` core stays light and imports no Docling.

## Install

In-process (default, heavy — pulls torch):

```bash
uv add 'runic-rag-docling[local]'
```

Lightweight client against a `docling-serve` instance:

```bash
uv add 'runic-rag-docling[server]'
```

## Usage

### Variant A — inject `DoclingChunker` via the `GraphRAG` constructor

Wire the Docling chunker as the `document_chunker`; `ingest_document` then parses
and chunks the original structure-aware, while `ingest_text` keeps the built-in
`ParagraphChunker`.

```python
from runic.rag import GraphRAG, ParagraphChunker, RagSettings  # plus the other ports
from runic_rag_docling import DoclingChunker, DoclingSettings

rag = GraphRAG(
    store,
    ontology=ontology,
    chunker=ParagraphChunker(settings),
    document_chunker=DoclingChunker(DoclingSettings(mode="local")),
    # extractor, embedder, resolver, retrievers, reranker, synthesizer, settings ...
)
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")  # Docling parses + chunks the original
```

Runnable: [`examples/docling_explicit_wiring.py`](examples/docling_explicit_wiring.py)
wires the full stack by hand (no `build_graphrag`).

### Variant B — `build_graphrag` one-liner (default stack + Docling)

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

For parse-only behavior, wire `DoclingParser` as the `document_parser` (keeps the
core `Chunker`).

## Configuration

`DoclingSettings` reads from the environment with the `RUNIC_DOCLING_` prefix
(e.g. `RUNIC_DOCLING_MODE=server`, `RUNIC_DOCLING_SERVER_URL=...`,
`RUNIC_DOCLING_API_KEY=...`, `RUNIC_DOCLING_MAX_TOKENS=512`).

See [`docs/rag/docling.md`](../../docs/rag/docling.md) for the full guide.
