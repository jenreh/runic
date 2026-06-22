# runic-rag-docling — Docling-Integration: Konzept & Implementierungsplan

> Status: Draft v3 (Kern-Ports + Add-on) · Zielprojekt: `jenreh/runic` · Ablageort: `spec/runic-graph-rag-docling-concept.md`
> Ergänzt `spec/runic-graph-rag-concept.md`. Der `runic.rag`-Kern erhält **zwei schlanke, dokumentbasierte Ports** (`DocumentParser`, `DocumentChunker`); die **schwere [Docling](https://github.com/docling-project/docling)-Implementierung** lebt in einem **eigenständigen, optionalen Add-on-Paket** (`runic-rag-docling`), das diese Ports erstklassig bedient — lokal **und** als Server, **ohne Workarounds**.

---

## 1. Zielsetzung & Scope

`runic.rag` parst Dokumente heute dependency-leicht
(`runic/rag/adapters/documents.py`) und chunkt heuristisch (`ParagraphChunker`,
Port `Chunker.split(text, *, source)`). Das ist robust, aber struktur-blind.
[Docling](https://github.com/docling-project/docling) (MIT) parst
PDF/DOCX/PPTX/XLSX/HTML/Bilder struktur-bewusst (Layout, Tabellen, Überschriften)
in ein `DoclingDocument` und chunkt damit überschriften-/tabellen-bewusst
(`HybridChunker`).

**Designwechsel ggü. v2.** Docling ist von Natur aus *Dokument→(Text|Chunks)* und
passt nicht auf den *Text→Chunks*-`Chunker`-Port. Statt dies mit einem
Markdown-Re-Parse-Workaround zu erzwingen, bekommt der **Kern zwei dedizierte,
dokumentbasierte Ports** (`DocumentParser`, `DocumentChunker`). Damit kann Docling
das **Original einmal** parsen und das strukturierte `DoclingDocument` **direkt**
chunken — voll struktur-bewusst, ohne Umweg.

**Ziel:**

- **Kern:** zwei schlanke, **abhängigkeitsfreie** Ports + minimale, additive
  Verdrahtung in `ingest_document`. Der Default-Pfad bleibt unverändert
  (rückwärtskompatibel). Der Kern importiert **kein** Docling. (ADR-019)
- **Add-on:** die **schwere** Docling-Last (torch) liegt in einem **separaten,
  optionalen Paket** `runic-rag-docling`, das die neuen Kern-Ports implementiert —
  lokal und als Server. (ADR-020, ADR-022)

Harte Leitplanken:

- **Dokumentbasierte Ports im Kern, ohne Workaround.** `DocumentChunker` liefert
  Datei→`list[Chunk]` (fused parse+chunk); `DocumentParser` liefert Datei→Text.
  Beide sind **optional** (Default `None`) und ändern den bestehenden Pfad nicht.
  (ADR-019, ADR-021)
- **Docling bleibt ein echtes, optionales Add-on.** Eigene Distribution, eigene
  Extras; nichts Schweres im Kern. (ADR-020)
- **Beide Betriebsmodi.** Lokal (Default) und Server (`docling-serve`); identisches
  Chunk-Ergebnis. (ADR-022)

**Non-Goals (YAGNI):** kein Docling-Import im Kern, kein async-Pfad, kein
serverseitiges Chunking-Endpoint, kein Docling-Default (opt-in via Konstruktor),
keine eigene OCR-/Tokenizer-Abstraktion.

---

## 2. Funktionsweise von Docling

### 2.1 Parsing (lokal, in-process)

```python
from docling.document_converter import DocumentConverter

doc = DocumentConverter().convert("doc.pdf").document   # DoclingDocument
markdown = doc.export_to_markdown()                       # verlustarm
```

- Eingabeformate: PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, EPUB, Bilder.
- In-Memory über `DocumentStream(name=…, stream=BytesIO(...))`.
- PDF-Optionen: `PdfPipelineOptions(do_ocr=…, do_table_structure=…)`.

### 2.2 Chunking (struktur-bewusst, direkt auf dem DoclingDocument)

```python
from docling.chunking import HybridChunker

chunker = HybridChunker(max_tokens=512, merge_peers=True)
for raw in chunker.chunk(doc):          # arbeitet auf dem DoclingDocument
    text = chunker.contextualize(raw)   # stellt Überschriften/Kontext voran
```

- `HybridChunker` braucht das `DoclingDocument` (nicht reinen Text) — genau dafür
  existiert der neue `DocumentChunker`-Port. Tokenizer-Default kann beim ersten
  Lauf ein HF-Modell laden (Netz) → konfigurierbar; `docling models download` für
  air-gapped (ADR-022).

### 2.3 Server-Modus (`docling-serve`)

- HTTP-Dienst (pip/Docker `quay.io/docling-project/docling-serve`).
- `POST /v1alpha/convert/file` (Upload) bzw. `POST /v1/convert/source` (URL).
- Antwort: `document.md_content` (Markdown) **und** `document.json_content`
  (verlustfreies `DoclingDocument`-JSON). Kein offizielles Python-SDK → `httpx`.
  Optionale Auth `X-Api-Key`.
- Chunking bleibt **clientseitig**: `json_content` → `DoclingDocument` re-hydrieren
  (`docling-core`) → derselbe `HybridChunker` → identisches Ergebnis wie lokal.

### 2.4 Lokal vs. Server

| Aspekt | Lokal | Server |
|---|---|---|
| Client-Abhängigkeiten | schwer (`docling`, torch ~3–5 GB) | leicht (`httpx` + opt. `docling-core`) |
| Latenz | sofort | HTTP-Roundtrip |
| Skalierung | ein Prozess | zentral/horizontal |
| Betrieb | nichts | Dienst/Container |

Default **lokal** (nichts zu betreiben); Server für Offload/leichten Client.

---

## 3. Integrationsstrategie: dokumentbasierte Kern-Ports + optionales Add-on

`docs/rag/custom-ports.md` definiert den `GraphRAG`-Konstruktor als Extension-Seam:
eigene Port-Implementierungen werden injiziert. Heute gibt es neun Ports. Wir
ergänzen **zwei dokumentbasierte Ports** (auf zehn bzw. elf), weil der bestehende
`Chunker`-Port (*Text→Chunks*) Docling nicht ohne Workaround abbilden kann:

- **`DocumentParser`** — `parse(path) -> str`: struktur-bewusstes Parsing eines
  Originals (PDF/DOCX/…) nach Text/Markdown. Speist anschließend den vorhandenen
  `Chunker`.
- **`DocumentChunker`** — `chunk_document(path) -> list[Chunk]`: **fused** Parse+
  Chunk. Parst das Original **einmal** zum `DoclingDocument` und chunkt es **direkt**
  mit `HybridChunker` — voll struktur-bewusst, **kein** Markdown-Re-Parse.

Beide sind optional und greifen nur in `ingest_document` (Datei-Pfad). `ingest_text`
(roher String) bleibt unverändert beim regulären `Chunker`. Damit ist der
Default-Pfad unberührt und der Docling-Pfad maximal mächtig.

**Trennung der Verantwortung:** Der **Kern** definiert die Ports und verdrahtet sie
(abhängigkeitsfrei, kein Docling-Import). Die **schwere** Docling-Implementierung
liegt im **Add-on** und wird über den `GraphRAG`-Konstruktor eingehängt (DIP).

---

## 4. Kern-Erweiterung: neue Ports & Verdrahtung (im `runic`-Repo)

Additiv und rückwärtskompatibel — der Default (`builtin`) bleibt exakt wie heute.

### 4.1 Ports — `runic/rag/ports.py`

```python
@runtime_checkable
class DocumentParser(Protocol):
    """Parst eine Dokumentdatei in normalisierten Text (z. B. Markdown)."""
    def supports(self, source: str) -> bool: ...
    def parse(self, path: str | Path) -> str: ...

@runtime_checkable
class DocumentChunker(Protocol):
    """Parst UND chunkt eine Dokumentdatei zu geordneten Chunks (fused)."""
    def supports(self, source: str) -> bool: ...
    def chunk_document(self, path: str | Path, *, source: str | None = None) -> list[Chunk]: ...
```

`supports(source)` entscheidet per Extension, ob der Adapter die Datei übernimmt
(z. B. `.pdf/.docx/.pptx/.html`); nicht unterstützte Endungen fallen auf den
Built-in-Loader zurück. Beide Namen in `runic/rag/ports.py:__all__` **und**
`runic/rag/__init__.py` exportieren.

### 4.2 Ingestion-Service — `runic/rag/services/ingestion.py`

- `IngestionService.__init__` erhält optional `document_parser: DocumentParser |
  None = None` und `document_chunker: DocumentChunker | None = None` (Default
  `None` → heutiges Verhalten).
- Tail von `ingest()` als `_ingest_chunks(chunks, *, source) -> IngestionReport`
  extrahieren (Leer-Guard bleibt). `ingest(text)` = `chunker.split` + `_ingest_chunks`.
- Extension-Dispatch als `_load_builtin(path) -> str` extrahieren.
- `ingest_document(path)` nach 3-Stufen-Schema (additiv):

```python
def ingest_document(self, path: str | Path) -> IngestionReport:
    spec = str(path)
    if self._document_chunker is not None and self._document_chunker.supports(spec):
        chunks = self._document_chunker.chunk_document(path, source=spec)   # fused, kein Workaround
        return self._ingest_chunks(chunks, source=spec)
    if self._document_parser is not None and self._document_parser.supports(spec):
        return self.ingest(self._document_parser.parse(path), source=spec)
    return self.ingest(self._load_builtin(path), source=spec)               # Default unverändert
```

### 4.3 Facade — `runic/rag/facade.py`

- `GraphRAG.__init__` erhält optional `document_parser=None`, `document_chunker=None`
  und reicht sie an `IngestionService` durch (DIP-Erweiterungspunkt).
- `with_defaults(...)` bleibt **builtin** (beide `None`) — der Kern importiert
  **kein** Docling. Der Docling-Pfad wird über den expliziten Konstruktor (bzw.
  einen Add-on-Helfer) eingehängt.

### 4.4 Docs (Kern)

- `docs/rag/custom-ports.md` + `docs/rag/api.md`: die zwei neuen Ports in die
  Port-Tabelle/Referenz aufnehmen (jetzt 11 Ports), inkl. Hinweis „Datei-orientiert,
  greift in `ingest_document`".

**Kosten im Kern:** rein additiv (zwei Protocols + drei kleine Methoden-Refactors).
Keine Verhaltensänderung am Default; `RagSettings`/Backends unberührt.

---

## 5. Add-on: Paketstruktur & Architektur (`runic-rag-docling`)

```
packages/runic-rag-docling/            # eigenständige Distribution, schwere Docling-Last
  pyproject.toml                       # name = runic-rag-docling; deps: runic-py; extras [local]/[server]
  README.md
  runic_rag_docling/
    __init__.py        # exports: DoclingChunker, DoclingParser, DoclingSettings,
                       #          LocalDoclingConverter, ServerDoclingConverter, build_graphrag
    settings.py        # DoclingSettings (pydantic-settings, prefix RUNIC_DOCLING_)
    _converters.py     # _DoclingConverter Protocol + LocalDoclingConverter + ServerDoclingConverter
    chunker.py         # DoclingChunker  (implements runic.rag DocumentChunker)
    parser.py          # DoclingParser   (implements runic.rag DocumentParser)
    factory.py         # build_graphrag(settings, docling_settings, ...) — optionaler Einzeiler
    _ids.py            # make_chunk_id() — mirror des runic-Default-Schemas
  tests/               # eigene Suite (docling gemockt; importorskip für echten Lauf)
  examples/docling_quickstart.py
```

### 5.1 `DoclingChunker` — implementiert `DocumentChunker` (kein Workaround)

```python
from runic.rag import Chunk, RagError          # nur öffentliche Kern-API

class DoclingChunker:
    """Fused Parse+Chunk via Docling. Implementiert runic.rag DocumentChunker."""
    def __init__(self, settings=None, *, converter=None, hybrid_chunker=None) -> None: ...

    def supports(self, source: str) -> bool:
        return source.lower().endswith(_SUPPORTED_SUFFIXES)

    def chunk_document(self, path, *, source=None) -> list[Chunk]:
        src = source or str(path)
        doc = self._converter.document_from_path(path)        # ORIGINAL -> DoclingDocument
        out: list[Chunk] = []
        for seq, raw in enumerate(self._hybrid.chunk(doc)):   # direkt auf der Struktur
            body = self._hybrid.contextualize(raw)
            out.append(Chunk(id=make_chunk_id(src, seq, body),
                             text=body, seq=seq, source=src))
        return out
```

- **Stabile, content-adressierte IDs** (`sha256("{source}|{seq}|{text[:64]}")`,
  identisch zum Default) → `MERGE`-Idempotenz, kein Duplikat bei Re-Ingest.
- **Lesereihenfolge** erhalten; **Chunk-Größe** über `max_tokens` gedeckelt.
- **Typisierte Fehler** (`RagError`); **Hausstil** (Typannotationen, `logger.debug`,
  keine f-strings in Logs).

### 5.2 `DoclingParser` — implementiert `DocumentParser`

`parse(path) -> str` über `converter.markdown_from_path(path)` (normalisiert). Für
Nutzer, die Docling nur zum Parsen wollen und den vorhandenen `ParagraphChunker`
behalten.

### 5.3 Converter-Strategy (lokal/Server)

```python
class _DoclingConverter(Protocol):
    def document_from_path(self, path) -> Any: ...   # DoclingDocument (für DoclingChunker)
    def markdown_from_path(self, path) -> str: ...   # Markdown (für DoclingParser)

class LocalDoclingConverter:   # lazy import docling; memoisierter DocumentConverter
class ServerDoclingConverter:  # httpx -> docling-serve; X-Api-Key; Timeout; json_content re-hydrate
```

Lazy-Import + `RagError`-Hinweis (Muster `CrossEncoderReranker._INSTALL_HINT`),
z. B. „install with `uv add 'runic-rag-docling[local]'`". Converter und
HybridChunker sind injizierbar (DIP) → Tests ohne installiertes Docling.

---

## 6. Konfiguration — `DoclingSettings` (im Add-on)

Das Add-on besitzt **eigene** Settings (pydantic-settings, Prefix `RUNIC_DOCLING_`);
Adapter akzeptieren `DoclingSettings` **oder** explizite kwargs:

```python
class DoclingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNIC_DOCLING_", env_file=".env")
    mode: Literal["local", "server"] = "local"
    server_url: str | None = None        # http://localhost:5001
    api_key: str | None = None           # X-Api-Key
    max_tokens: int = 512                 # HybridChunker
    tokenizer: str | None = None          # HF-ID; None -> Docling-Default
    merge_peers: bool = True
    ocr: bool = False                     # lokales PDF-OCR
    timeout: float = 120.0               # Server-HTTP-Timeout (s)
```

---

## 7. Betriebsmodi: Lokal vs. Server

- **Lokal (Default).** `mode="local"`; `LocalDoclingConverter` baut einen
  memoisierten `DocumentConverter`. Nichts zu betreiben; schwere Abhängigkeit.
- **Server.** `mode="server"` + `server_url` (+ optional `api_key`);
  `ServerDoclingConverter` ruft `docling-serve` per `httpx`. Leichter Client;
  `document_from_path` re-hydriert `json_content` clientseitig zu einem
  `DoclingDocument` → identische Chunks; `markdown_from_path` nutzt `md_content`.

---

## 8. Abhängigkeiten & Optionalität — `packages/runic-rag-docling/pyproject.toml`

```toml
[project]
name = "runic-rag-docling"
dependencies = ["runic-py>=0.3.7", "pydantic-settings>=2.14.2"]

[project.optional-dependencies]
local  = ["docling>=2.59.0"]                                  # in-process parse + chunk (schwer: torch)
server = ["httpx>=0.27", "docling-core[chunking]>=2.0.0"]     # leichter Client + Re-Hydrate/HybridChunker

[tool.uv.sources]
runic-py = { path = "../..", editable = true }   # nur für lokale Entwicklung im Monorepo
```

- **Kern bleibt leicht:** keine Docling-/torch-Abhängigkeit in `runic`; Root-CI unberührt.
- Python 3.14: `docling ≥ 2.59` unterstützt 3.14; Server-Client braucht ohnehin kein torch.
- macOS-Hinweis (Multiprocessing/OCR) als Risiko in §12; OCR Default aus.

---

## 9. Öffentliche API & Nutzung

**Variante A — Docling als `DocumentChunker` (fused), via `GraphRAG`-Konstruktor.**
Spiegelt das Scaffold aus `custom-ports.md`, ergänzt den dokumentbasierten Port:

```python
from runic.ogm import create_driver
from runic.rag import (GraphRAG, GraphStoreAdapter, Ontology, OpenAIEmbedder,
                       ParagraphChunker, PydanticAIExtractor, PydanticAISynthesizer,
                       RagSettings, RRFReranker, TwoStageResolver, VectorRetriever,
                       FulltextRetriever, LocalRetriever, HighLevelRetriever)
from runic.rag.concurrency import BudgetGuard
from runic_rag_docling import DoclingChunker, DoclingSettings   # ← Add-on

settings = RagSettings(falkordb_graph="docling_demo")
ontology = Ontology.default()
driver = create_driver("falkordb", host=settings.falkordb_host,
                       port=settings.falkordb_port, graph=settings.falkordb_graph)
store = GraphStoreAdapter(driver, settings, schema_models=ontology.schema_models())
embedder = OpenAIEmbedder(settings)
budget = BudgetGuard(max_llm_calls=settings.max_llm_calls, max_tokens=settings.max_tokens)

rag = GraphRAG(
    store, ontology=ontology,
    chunker=ParagraphChunker(settings),                          # ingest_text-Pfad (roher String)
    document_chunker=DoclingChunker(DoclingSettings(mode="local")),  # ← neuer Kern-Port, fused
    extractor=PydanticAIExtractor(settings), embedder=embedder,
    resolver=TwoStageResolver(settings),
    retrievers={"vector": VectorRetriever(store, embedder, settings),
                "fulltext": FulltextRetriever(store, settings),
                "local": LocalRetriever(store, embedder, settings),
                "highlevel": HighLevelRetriever(store, settings, budget=budget)},
    reranker=RRFReranker(), synthesizer=PydanticAISynthesizer(settings, budget=budget),
    settings=settings, budget=budget,
)
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")   # Docling parst+chunkt das Original direkt
```

**Variante B — Add-on-Einzeiler (baut den Default-Stack + Docling):**

```python
from runic_rag_docling import build_graphrag, DoclingSettings
from runic.rag import load_settings

rag = build_graphrag(load_settings(), DoclingSettings(mode="server",
                                                      server_url="http://localhost:5001"))
rag.bootstrap_schema()
report = rag.ingest_document("whitepaper.pdf")
```

`build_graphrag` spiegelt `with_defaults`, injiziert aber den Docling-`document_chunker`
(bzw. `document_parser`). Nur-Parsing: `DoclingParser` als `document_parser` setzen.

---

## 10. Implementierungsplan

**A. Kern (`runic/`, additiv, rückwärtskompatibel):**
1. `ports.py` — `DocumentParser`, `DocumentChunker` + `__all__`; in `__init__.py` exportieren.
2. `services/ingestion.py` — `_ingest_chunks`/`_load_builtin` extrahieren; ctor-Parameter;
   `ingest_document` nach §4.2.
3. `facade.py` — ctor-Parameter + Durchreichung; `with_defaults` bleibt builtin.
4. `docs/rag/custom-ports.md` + `api.md` — zwei neue Ports dokumentieren.
5. Tests: `tests/runic/rag/` — `ingest_document` routet zu injiziertem
   `document_chunker`/`document_parser` (Fakes), Fallback auf builtin; `_ingest_chunks`-Guard.

**B. Add-on (`packages/runic-rag-docling/`):**
6. Paketgerüst (`pyproject.toml`, `README.md`, `__init__.py`), `settings.py`, `_ids.py`.
7. `_converters.py` (lokal/Server, lazy import, `RagError`-Hinweis).
8. `chunker.py` (`DoclingChunker` → `DocumentChunker`), `parser.py` (`DoclingParser` →
   `DocumentParser`), `factory.py` (`build_graphrag`).
9. Tests (§11), `examples/docling_quickstart.py`, README-Wiring.
10. Memory `project_runic_rag.md` nach Umsetzung ergänzen.

---

## 11. Teststrategie

**Kern** (`tests/runic/rag/`, ohne Docling): `ingest_document`-Dispatch zu
`document_chunker`/`document_parser`-Fakes + Fallback; Port-`isinstance`-Smoke-Tests;
`_ingest_chunks` Leer-Guard; Default-Verhalten unverändert (bestehende Tests grün).

**Add-on** (`packages/runic-rag-docling/tests/`, Docling gemockt):
- `fakes.py` — Fake-Converter (liefert triviales Doc-Objekt) + Fake-HybridChunker.
- `test_chunker.py` — `isinstance(DoclingChunker(...), runic.rag.ports.DocumentChunker)`;
  `chunk_document` → Chunks mit stabiler ID/seq/source + Kontextualisierung; Idempotenz;
  `supports()`-Matrix; Lazy-Import → `RagError` (Monkeypatch).
- `test_parser.py` — `DoclingParser.parse` mit Fake-Converter.
- `test_server_converter.py` — `ServerDoclingConverter` über `pytest-httpserver`
  (Upload-Form + `X-Api-Key`, `md_content`/`json_content`).
- `test_settings.py` — `DoclingSettings` Defaults + `RUNIC_DOCLING_*`-Env.
- `test_integration.py` — `@pytest.mark.integration` + `pytest.importorskip("docling")`,
  echtes Mini-PDF → nicht-leere Chunks.

Ziel: Coverage ≥ 80 % je Suite; Unit-Suiten **ohne** Docling-Import.

---

## 12. Risiken & offene Punkte

- **Docling-Gewicht/py3.14.** torch ~3–5 GB; py3.14 ab Docling 2.59. Gemildert durch
  Optionalität (Add-on-Extra) und leichten Server-Client.
- **macOS-Stabilität.** Vereinzelt Multiprocessing/OCR-Probleme bei lokalem Docling →
  Server-Modus / OCR aus (Default).
- **Tokenizer-Download.** HybridChunker-Default kann ein HF-Modell laden → `tokenizer`
  setzbar; `docling models download` für air-gapped.
- **`docling-serve`-API-Version.** Endpoint-Pfade gegen die betriebene Version prüfen;
  im `ServerDoclingConverter` gekapselt.
- **Kern-API-Oberfläche.** Zwei neue Ports vergrößern die öffentliche Oberfläche
  (bewusst, dauerhaft zu pflegen) — Gegenwert: kein Workaround, klare Datei-Semantik.

---

## 13. Verifikation

1. Kern-Suite: `task test` — grün (Default unverändert), neue Dispatch-Tests grün,
   Coverage ≥ 80 %.
2. Kern-Gates: `task format && task lint && task typecheck` sauber.
3. Add-on-Suite (Docling gemockt): `cd packages/runic-rag-docling && uv run pytest`
   — grün, Coverage ≥ 80 %; eigene `ruff`/`ty`-Gates sauber.
4. Optional real (schwer): `uv sync --extra local`, dann
   `examples/docling_quickstart.py` (PDF → FalkorDB); `@integration`-Test grün.
5. Server: `docling-serve` (Docker), `DoclingSettings(mode="server", server_url=…)` →
   äquivalentes Ergebnis zu lokal.

---

## Anhang A — Architecture Decision Records (ADRs)

In Fortführung der ADR-Reihe aus `spec/runic-graph-rag-concept.md` (endet bei
ADR-018). Format: Nygard-/MADR-Stil (Kontext, Entscheidung, verworfene
Alternativen, Konsequenzen). Datum 2026-06-22, Decider: `jenreh`, Status `Accepted`.

| ADR | Entscheidung | Betrifft |
|---|---|---|
| 019 | Dokumentbasierte Kern-Ports (`DocumentParser`, `DocumentChunker`), additiv & opt-in | §3, §4 |
| 020 | Docling-Implementierung als eigenständiges, optionales Add-on-Paket | §1, §5 |
| 021 | Add-on bedient die Ports fused & direkt (kein Markdown-Re-Parse-Workaround) | §3, §5 |
| 022 | Lokal vs. Server über eine Converter-Strategy; Lazy-Import, Tokenizer, Mock-Tests | §5–§8, §11 |

---

### ADR-019: Dokumentbasierte Kern-Ports (`DocumentParser`, `DocumentChunker`)

**Kontext:** Docling ist *Dokument→(Text|Chunks)*; der bestehende `Chunker`-Port ist
*Text→Chunks*. Den `HybridChunker` über `Chunker.split(text)` zu betreiben, würde
einen Markdown-Re-Parse-Workaround erzwingen und die Struktur verwerfen, von der
Docling lebt. `ingest_document` ist der natürliche Ort für „Datei → …".

**Entscheidung:** Der Kern erhält zwei schlanke, **abhängigkeitsfreie** Ports —
`DocumentParser` (`parse(path)->str`) und `DocumentChunker`
(`chunk_document(path)->list[Chunk]`, fused). Beide sind optional (Default `None`),
greifen nur in `ingest_document` und lassen den Default- und `ingest_text`-Pfad
unverändert. Der Kern importiert **kein** Docling.

**Alternativen:**
- *Workaround über `Chunker.split(text)` (md-Re-Parse)* — verworfen: verliert
  Struktur, doppeltes Parsen, „astonishing" bei Pfad-`source`.
- *Gar keine Kern-Ports, alles im Add-on über `Chunker`* — verworfen: zwingt den
  Workaround auf, schwächt Doclings Mehrwert (Nutzerwunsch: „nicht mit Workarounds").
- *Einen einzigen kombinierten Port* — verworfen: Parsing-only (→ vorhandener
  Chunker) und fused parse+chunk sind verschiedene Bedürfnisse (ISP).

**Konsequenzen:**
- (+) Docling kann das Original einmal parsen und direkt struktur-bewusst chunken.
- (+) Additiv & rückwärtskompatibel; Kern bleibt docling-/torch-frei.
- (−) Zwei zusätzliche öffentliche Ports + ein Verzweigungspunkt in `ingest_document`.

### ADR-020: Docling-Implementierung als eigenständiges, optionales Add-on-Paket

**Kontext:** Docling ist schwer (torch ~3–5 GB) und hatte py3.14-Friktion. Der Kern
soll leicht bleiben; Docling soll ein „echtes Add-on" sein.

**Entscheidung:** Die Docling-Adapter leben in einer **separaten Distribution**
`runic-rag-docling` (Import `runic_rag_docling`) unter `packages/runic-rag-docling/`,
die die Kern-Ports implementiert. Eingehängt über den `GraphRAG`-Konstruktor (bzw.
einen Add-on-Helfer `build_graphrag`). Kein Docling-Import im Kern.

**Alternativen:**
- *Docling-Adapter in `runic/rag/adapters/`* — verworfen: zieht torch in den
  Kern-Wheel/CI, widerspricht „leichter Kern / optionales Add-on".
- *Separates Repo* — möglich, aber Monorepo erleichtert gemeinsame Entwicklung/Tests
  (kann später ausgegliedert werden).

**Konsequenzen:**
- (+) Kern-Wheel/CI leicht; Docling-Last strikt opt-in; unabhängig versionierbar.
- (−) Zweite Distribution im Monorepo (eigener Build/CI-Lauf).

### ADR-021: Add-on bedient die Ports fused & direkt (kein Workaround)

**Kontext:** Mit den Kern-Ports aus ADR-019 kann das Add-on das Original direkt
verarbeiten, statt Text zu re-parsen.

**Entscheidung:** `DoclingChunker` implementiert `DocumentChunker`:
`document_from_path(path) -> DoclingDocument` → `HybridChunker.chunk(doc)` →
`Chunk`-Objekte mit stabilen, content-adressierten IDs (identisch zum Default-Schema).
`DoclingParser` implementiert `DocumentParser` (Markdown). **Kein**
Markdown-Re-Parse mehr.

**Alternativen:**
- *Markdown-Re-Parse im Chunker (v2)* — verworfen: unnötiger Qualitätsverlust und
  Doppelarbeit, nachdem der Kern die richtigen Ports hat.

**Konsequenzen:**
- (+) Volle Struktur-Treue (Layout/Tabellen/Überschriften) in den Chunks; einmaliges
  Parsen; identische IDs → `MERGE`-Idempotenz.
- (−) `DocumentChunker` ignoriert `chunk_size`/`chunk_overlap` des Kerns und nutzt
  `max_tokens` (bewusste Semantik; dokumentiert).

### ADR-022: Lokal vs. Server (Converter-Strategy) + Optionalität/Tests

**Kontext:** Docling läuft in-process (`DocumentConverter`, torch, py3.14 ab 2.59)
oder als Dienst `docling-serve` (HTTP; `md_content` + verlustfreies `json_content`).
Beide Modi sind gefordert. HybridChunkers Default-Tokenizer kann ein HF-Modell laden.

**Entscheidung:** Interne `_DoclingConverter`-Strategy mit `LocalDoclingConverter`
(Default) und `ServerDoclingConverter` (httpx, `X-Api-Key`, Timeout). Auswahl über
`DoclingSettings.mode`. Server-Pfad re-hydriert `json_content` clientseitig →
identisches Chunk-Ergebnis; leichter Client (httpx + `docling-core`, kein torch).
Docling hinter Add-on-Extras `[local]`/`[server]`; Lazy-Import + `RagError`-Hinweis;
Converter/HybridChunker injizierbar (DIP) → Unit-Tests via Fakes + `pytest-httpserver`,
echter Roundtrip nur als `@pytest.mark.integration` mit `importorskip`. Tokenizer
über `DoclingSettings.tokenizer`/`max_tokens`; `docling models download` für air-gapped.

**Alternativen:**
- *Nur lokal* — verworfen: kein Offload/Skalierung. *Nur Server* — verworfen:
  erzwingt Dienstbetrieb auch lokal. *Serverseitiges Chunking-Endpoint* — verworfen:
  API unausgereift; Chunking clientseitig (konsistent).
- *Docling in der Standard-CI / als harte Add-on-Abhängigkeit* — verworfen: ~3–5 GB
  torch, py3.14-Friktion, zwingt Last auf (auch reine Server-Nutzer).

**Konsequenzen:**
- (+) Beide Modi mit identischem Ergebnis; leichter Client im Server-Modus;
  deterministische Offline-Unit-Tests.
- (−) Zwei Konversionspfade zu pflegen; Server-Fused-Chunking braucht `docling-core`;
  Tokenizer-Download als Betriebsdetail zu dokumentieren.
