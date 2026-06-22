# runic-graph-rag — Konzept & Implementierungsplan

> Status: Draft v4 (ADR-Anhang) · Zielprojekt: `jenreh/runic` · Ablageort: `spec/runic-graph-rag-concept.md`
> Eine schlanke, wiederverwendbare Graph-RAG-Erweiterung auf Basis von `runic.ogm` + `runic.migrate`.

---

## 1. Zielsetzung & Scope

`runic-graph-rag` ist eine **dünne SDK-Schicht oberhalb von runic**, die aus unstrukturiertem Text einen Wissensgraphen aufbaut und über ihn retrievt — ohne dass der Anwender ein explizites Schema modellieren oder rohes Cypher schreiben muss.

Leitprinzipien:

- **Minimaler Aufwand für den Konsumenten.** Ontologie als Konfiguration, sinnvolle Defaults, Schema-Bootstrap über `SchemaManager.sync_schema()`. Ein lauffähiger Graph-RAG in ~10 Zeilen.
- **Hybrid-Pfad als Default.** Entitätstypen sind hart constrained (polymorphe runic-Labels), Relationstypen bleiben weich (Property statt Edge-Label). Emergente Typen brauchen keinen Schemawechsel.
- **runic ist die Persistenz- und Schemaschicht.** `runic.ogm` ersetzt den „PropertyGraphStore" anderer Frameworks; `runic.migrate` verwaltet Indizes/Constraints versioniert.
- **Backend-portabel.** Unterstützt FalkorDB **und** Neo4j-basierte DBs (Neo4j, Memgraph, ArcadeDB, Apache AGE) über denselben Code. Backend-spezifische Cypher-Unterschiede liegen ausschließlich im `GraphStore`-Adapter.
- **Synchroner Codepfad.** Es wird die `runic.ogm`-`Session` (sync) verwendet, **nicht** `AsyncSession` — ein einziger Pfad über alle Backends statt zweier zu pflegender Varianten. Nebenläufigkeit bei der Ingestion läuft über Thread-Pools (LLM-/Embedding-Calls sind netz-I/O-gebunden, geben den GIL frei), nicht über asyncio.
- **Erweiterbar über Protocols, nicht über Forks.** Jeder Pipeline-Schritt (Chunking, Extraktion, Resolution, Retrieval, Reranking) ist ein austauschbarer Port.

**Non-Goals (YAGNI):** kein eigener Graph-Store, kein eigener Vektor-Store, keine eigene LLM-Abstraktion (delegiert an Pydantic AI), keine Multi-Tenant-Governance, keine UI. Community-Detection und Bi-Temporalität sind **opt-in**, nicht im Kern.

---

## 2. Analyse existierender Frameworks

| Framework | Kernidee | Charakteristische Konzepte | Was übernehmen | Was weglassen |
|---|---|---|---|---|
| **Microsoft GraphRAG** | Lokale-zu-globale Zusammenfassung über Community-Hierarchien | LLM-Entity/Relation-Extraktion, Leiden-Community-Detection, hierarchische Community-Summaries, local/global/DRIFT-Search, LazyGraphRAG (verzögerte Summaries) | Local/Global-Trennung, DRIFT als kombinierter Modus, Lazy-Variante als kostengünstige Global-Strategie | Eager-Summarization als Default (zu teuer), schwergewichtige Pipeline-Orchestrierung |
| **LightRAG** | Schnelle, inkrementelle Alternative ohne Community-Schritt | Dual-Level-Retrieval (low-level Entity / high-level Theme-Keywords), inkrementelles Update per Set-Merge, vektor-indizierter Graph | Dual-Level-Retrieval, inkrementelles Merge ohne Rebuild, „kein Community-Schritt nötig"-Philosophie | Eigenes Speicherformat |
| **Graphiti / Zep** | Temporaler Kontextgraph für Agent-Memory | Bi-temporales Modell (valid + ingestion time), episodenbasierte Ingestion, Fakt-Invalidierung (supersede statt delete), Provenance (non-lossy Episodic Edges), hybrides Retrieval (Vektor + BM25 + BFS) mit Reranking (RRF/MMR/Cross-Encoder) | Provenance/Chunk→Entity-Edges, hybrides Retrieval + RRF-Reranking, episodenbasiertes inkrementelles Ingestieren | Volle Bi-Temporalität (nur opt-in), Hyperedges |
| **LlamaIndex PropertyGraphIndex** | Komponierbare KG-Extraktion und -Retrieval | Pluggable `kg_extractors` (schema-guided `strict=True` vs. frei `strict=False`), komponierbare Sub-Retriever (Synonym + Vektor), `PropertyGraphStore`-Abstraktion | Pluggable-Extractor/Retriever-Architektur, `strict=False` als Hybrid-Mechanismus, komponierbare Retriever | Eigener Store/StorageContext (runic übernimmt das) |

**Beobachtung:** Die vier Frameworks decken ein Spektrum von „teuer & gründlich" (Microsoft) bis „leicht & inkrementell" (LightRAG) ab. Graphiti steuert Provenance + hybrides Retrieval bei, LlamaIndex die Erweiterbarkeits-Architektur. Keines ist auf eine OGM-getriebene, schema-versionierte Basis wie runic ausgelegt — genau das ist die Differenzierung.

---

## 3. Abgeleitete Kernkonzepte & Bewertung

Jedes Konzept gegen die zwei Zielachsen bewertet — **Fit mit runic** und **Beitrag zum „minimaler Aufwand / wiederverwendbar"-Ziel**:

| Konzept | Quelle | Fit mit runic | Entscheidung |
|---|---|---|---|
| LLM-Entity/Relation-Extraktion | alle | Kern | **IN** — Phase 1 |
| Hybrid-Schema (constrained Typen + freie Instanzen) | LlamaIndex `strict=False` | Mappt 1:1 auf polymorphe `Entity`-Labels | **IN** — Phase 1 |
| Pluggable Extractor/Retriever-Protocols | LlamaIndex | OCP/DIP, Architektur-Rückgrat | **IN** — Architektur |
| Vektor-indizierter Graph + Entity-Embeddings | LightRAG / alle | `Field(index_type="VECTOR")` nativ | **IN** — Phase 1 |
| Provenance (Chunk→Entity `MENTIONS`-Edges) | Graphiti | Billig, hoher Wert (Zitate, Debugging) | **IN** — Phase 1 |
| Lokales Retrieval (Vektor-Seed + Multi-Hop-Traversal) | alle | runic Query-Builder `traverse()` | **IN** — Phase 1/2 |
| Dual-Level-Retrieval (Entity + Theme) | LightRAG | Billig, kein Community-Schritt | **IN** — Phase 2 |
| Hybrides Retrieval (Vektor + Fulltext) + RRF-Reranking | Graphiti/Zep | runic hat Fulltext- **und** Vektor-Index | **IN** — Phase 2 |
| Community-Detection (Leiden) + hierarchische Summaries | Microsoft | Teuer (LLM-Summaries) | **OPTIONAL** — Phase 3 |
| Global-/DRIFT-Search | Microsoft | Hängt an Communities | **OPTIONAL** — Phase 3 |
| LazyGraphRAG (dynamische Community-Wahl, verzögerte Summaries) | Microsoft | Günstigere Global-Variante | **OPTIONAL** — bevorzugte Global-Strategie, falls Phase 3 |
| Inkrementelles Update (Set-Merge, kein Rebuild) | LightRAG | `MERGE`-Semantik des OGM macht das natürlich | **IN** — Phase 1 implizit, batched in Phase 4 |
| Bi-temporales Modell + Fakt-Invalidierung | Graphiti | Mächtig, aber schwer; nur für evolvierende/Agent-Memory-Fälle | **OPTIONAL** — Phase 4 |
| Episode-Subgraph (immutable Events) | Graphiti | Event-Sourcing-Charakter der Provenance | **OPTIONAL** — Phase 4 |

**Schnittmenge für den Kern (Phase 1–2):** hybride Extraktion → Vektor-Dedup → OGM-Write mit Provenance → komponierbares hybrides Retrieval mit Reranking. Das ist das „90%-Wertversprechen" ohne die teuren Teile.

---

## 4. Zielarchitektur

Hexagonal (Ports & Adapters). Der Domänenkern kennt weder Pydantic AI noch FalkorDB noch runic direkt — nur Protocols. Adapter binden die Außenwelt an.

```
                       ┌──────────────────────────────────────┐
   ingest()  ─────────▶│        IngestionService (Command)     │
   query()   ─────────▶│        RetrievalService (Query)       │   ← CQRS-leichte Trennung
                       └───────────────┬──────────────────────┘
                                       │ depends on (Protocols)
        ┌──────────┬──────────┬────────┴───────┬───────────┬──────────────┐
     Chunker   Extractor  EntityResolver   Embedder    Retriever      Reranker
        │          │          │               │           │              │
   ─────┴──────────┴──────────┴───────────────┴───────────┴──────────────┴────  Ports
   Adapter:   PydanticAI   VectorResolver  Ollama/OpenAI  Vector+Fulltext  RRF
                                       │
                              ┌────────┴─────────┐
                              │   GraphStore     │  ← Port; Adapter wrappt runic.ogm.Session
                              └────────┬─────────┘
                                       │
                              runic.ogm  +  runic.migrate (Schema-Lifecycle)
                                       │
                          FalkorDB │ Neo4j │ Memgraph │ ArcadeDB │ Apache AGE
```

### 4.1 CCD-Zuordnung

- **DIP** — `IngestionService`/`RetrievalService` hängen an `Protocol`-Ports, nie an konkreten Adaptern. Konstruktor-Injektion.
- **ISP** — schmale Protocols pro Bedarf (`Embedder`, `Reranker`, …), keine fette „GraphRAG"-Basisklasse.
- **OCP** — neue Extraktions-/Retrieval-Strategien werden als neue Adapter eingehängt, nicht durch Editieren bestehender `if/elif`-Ketten. Modus-Auswahl per Dict-Dispatch.
- **SRP** — je Service eine Verantwortung; Persistenz, Extraktion, Retrieval sind getrennt.
- **Information Hiding** — `__all__` je Modul, `GraphRAG`-Facade versteckt die Verdrahtung, Interna `_`-präfigiert.
- **Tell, Don't Ask** — `rag.ingest(...)` / `rag.query(...)` statt extern orchestrierter Schritte.
- **YAGNI** — Phase 3/4 sind optionale Pakete, kein spekulativer Code im Kern.

### 4.2 Ports (Auszug)

```python
# runic_graph_rag/ports.py
from typing import Protocol
from .domain import Chunk, Extraction, ExtractedEntity, RetrievalContext

class Chunker(Protocol):
    def split(self, text: str) -> list[Chunk]: ...

class Extractor(Protocol):
    def extract(self, chunk: Chunk) -> Extraction: ...        # via Agent.run_sync()

class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...

class EntityResolver(Protocol):
    def resolve_key(self, entity: ExtractedEntity) -> str: ...

class Retriever(Protocol):
    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext: ...

class Reranker(Protocol):
    def rerank(self, contexts: list[RetrievalContext]) -> RetrievalContext: ...
```

`GraphStore` ist ebenfalls ein Port; sein einziger Adapter wrappt `runic.ogm.Session` + `Repository` (synchron). So bleibt der Domänenkern frei von runic-Importen (saubere Testbarkeit, DIP). Der Adapter kapselt zudem die **backend-spezifischen** Cypher-Unterschiede (s. u.), sodass Services backend-agnostisch bleiben.

Die I/O-gebundenen Ports (`Extractor`, `Embedder`) sind synchron, intern aber über `Agent.run_sync()` bzw. synchrone Embedding-Clients realisiert. Für Durchsatz bei der Ingestion parallelisiert der `IngestionService` die Extraktion mehrerer Chunks über einen `ThreadPoolExecutor`; die Graph-Writes laufen anschließend in **einer** `Session` (Unit of Work).

### 4.3 Backend-Portabilität

Das OGM glättet die meisten Unterschiede transparent; der Rest wird im `GraphStore`-Adapter isoliert (OCP — neues Backend = neuer Adapter, kein Editieren der Services):

| Aspekt | FalkorDB | Neo4j-Familie | Behandlung im Adapter |
|---|---|---|---|
| Vektor-KNN-Proc | `db.idx.vector.queryNodes(...)` | `db.index.vector.queryNodes(...)` | Dialekt-abhängige Query im Adapter, hinter dem `GraphStore`-Port |
| Ungerichtetes `MERGE` (`direction="BOTH"`) | nicht unterstützt → OGM fällt transparent auf `OUTGOING` zurück | unterstützt | vom OGM erledigt, keine Modelländerung |
| `relabel_nodes` (Migration) | unterstützt | Apache AGE / ArcadeDB werfen `NotImplementedError` | Migration nur backend-bewusst einsetzen |
| Vektor-/Fulltext-Index-DDL | über `Field(index_type=...)` | dito | identisch deklariert, `op.*` übersetzt |

Praktisch heißt das: ein `GraphStore`-Adapter pro Backend-Dialekt, der genau die KNN- und etwaige proc-spezifischen Reads kapselt. Services, Domänenmodell und Ontologie bleiben unverändert.

---

## 5. Datenmodell

Polymorphe `Entity`-Hierarchie (= loose Ontologie) + generische `RELATES_TO`-Kante mit Typ-als-Property + Provenance über `Chunk`. Alle Indizes sind als `Field`-Annotation deklariert, damit `SchemaManager.sync_schema()` sie ohne Handarbeit anlegt.

```python
# runic_graph_rag/models.py
from runic.ogm import Edge, Field, Node, Relation

class Chunk(Node, labels=["Chunk"]):
    id: str = Field(primary_key=True, generated=True)
    text: str = Field(index_type="FULLTEXT")
    embedding: list[float] | None = Field(index_type="VECTOR", default=None)
    source: str = Field(index=True)              # Provenance: Dokument/Episode
    mentions: list["Entity"] = Relation(
        relationship="MENTIONS", direction="OUTGOING", target="Entity",
    )

class RelationEdge(Edge, type="RELATES_TO"):
    rel_type: str = Field()                      # weicher Relationstyp
    description: str = Field(default="")
    confidence: float = Field(default=1.0)
    source_chunk: str = Field(default="")        # Provenance

class Entity(Node, labels=["Entity"], primary_label="Entity"):
    canonical_key: str = Field(primary_key=True)
    name: str = Field(index_type="FULLTEXT")
    description: str = Field(default="")
    embedding: list[float] | None = Field(index_type="VECTOR", default=None)
    related: list["Entity"] = Relation(
        relationship="RELATES_TO", direction="OUTGOING",
        target="Entity", edge_model=RelationEdge,
    )

class Person(Entity, labels=["Entity", "Person"], primary_label="Entity"): ...
class Project(Entity, labels=["Entity", "Project"], primary_label="Entity"): ...
class Technology(Entity, labels=["Entity", "Technology"], primary_label="Entity"): ...
class Concept(Entity, labels=["Entity", "Concept"], primary_label="Entity"): ...
```

**Schema-Lifecycle (runic 3-Stufen):**

1. **Dev** — `SchemaManager(adapter).sync_schema([Chunk, Entity, RelationEdge, *subtypes])` legt alle Indizes sofort an. Idempotent.
2. **Versionierung** — `runic baseline -m "graph-rag baseline"` introspeziert und erzeugt die Root-Migration + `SchemaManifest`-Block für `env.py` (Vektor-`dimension` von `0` auf realen Wert setzen).
3. **Produktion** — handgeschriebene Revisionen je Schemaänderung; `runic check` als CI-Gate.

Optionale Phase-3-Knoten (`Community` mit `level`, `summary`, `summary_embedding`) und Phase-4-Felder (`valid_from`, `valid_to`, `ingested_at` auf `RelationEdge`) kommen erst dann ins Modell, wenn die Phase gezogen wird (YAGNI).

---

## 6. Phasenplan

### Phase 0 — Skelett & Verträge

- Paketgerüst `runic-graph-rag` (oder Extra `runic-py[graphrag]`), Typer-CLI-Stub, ruff/mypy, Taskfile.
- `domain.py` (Value Objects: `Chunk`, `ExtractedEntity`, `ExtractedRelation`, `Extraction`, `RetrievalContext` als `frozen` Pydantic-Modelle), `ports.py` (Protocols), `models.py` (OGM).
- `GraphStore`-Adapter über `Session` (sync), inkl. backend-spezifischem Vektor-KNN-Read.
- **Deliverable:** importierbares Paket, leere Services, grünes mypy.
- **CCD-Checkpoint:** Interfaces vor Implementierung; `__all__` gesetzt; keine Adapter-Importe im Domänenkern.

### Phase 1 — Ingestion-MVP + lokales Retrieval

- `Chunker`-Default (Token-/Absatz-basiert), `PydanticAIExtractor` (Hybrid: `EntityType`-Enum constraint, `RelationType` mit `RELATES_TO`-Fallback), `Embedder`-Adapter (Ollama/OpenAI), zweistufiger `EntityResolver` (deterministisch + Vektor-KNN, Merge bei Cosine-Sim ≥ 0.92 innerhalb desselben Typs; s. 9.3).
- `IngestionService.ingest(text)`: chunk → extract → resolve → OGM-Upsert (`session.get`/`add`, dirty-Update) → `relate()` (idempotent) → `MENTIONS`-Provenance.
- `LocalRetriever`: Vektor-Seed auf `Entity.embedding` + 1–2-Hop-`traverse()` + zugehörige `Chunk`-Texte.
- `RetrievalService.query(q, mode="local")` → Kontext → Pydantic-AI-Synthese.
- **Deliverable:** End-to-end `ingest()` → `query(mode="local")` gegen FalkorDB **und** Neo4j (gleicher Code, Adapter-Auswahl über `create_driver`).
- **Acceptance:** Roundtrip-Test (ingest Beispielkorpus, faktische Query liefert zitierte Entitäten/Chunks); `runic test` grün für die Baseline-Migration.

### Phase 2 — Dual-Level + hybrides Retrieval + Reranking

- `HighLevelRetriever` (LightRAG-Stil): LLM extrahiert Theme-Keywords aus der Query → Fulltext-Match auf `Entity.name`/`description` → thematische Subgraphen.
- `FulltextRetriever` (BM25 über runic-Fulltext-Index) ergänzt `VectorRetriever`.
- `RRFReranker` (Reciprocal Rank Fusion) als Default; `CrossEncoderReranker` optional.
- `mode="hybrid"` komponiert mehrere Retriever nebenläufig und fusioniert (komponierbar wie LlamaIndex-Sub-Retriever).
- **Deliverable:** `query(q, mode="hybrid")` mit fusionierten, gerankten Ergebnissen.
- **Acceptance:** messbar bessere Recall-Werte vs. reines Vektor-Retrieval auf einem Eval-Set; Retriever einzeln unit-testbar (DIP).
- **CCD-Checkpoint:** Modus-Auswahl per Dict-Dispatch (`_MODES: dict[str, Retriever]`), kein `if/elif` (OCP).

### Phase 3 — Community-Detection & Global-Search (optional)

- `CommunityBuilder`-Port; Default-Adapter mit **graspologic** `hierarchical_leiden` (MIT) über eine NetworkX-Projektion des `Entity`-Subgraphen → `Community`-Knoten je Level; `leidenalg` (GPLv3) optional hinter `[community-gpl]` (s. 9.2).
- `CommunitySummarizer` (LLM) — **standardmäßig lazy** (LazyGraphRAG: Summary erst bei Bedarf, dynamische Community-Wahl) statt eager über alle Communities.
- `GlobalRetriever` + `DriftRetriever` (Global-Seed → lokale Folgefragen → Re-Rank).
- **Deliverable:** `query(q, mode="global"|"drift")`.
- **Gate:** nur ziehen, wenn korpusweite „Hauptthemen"-Fragen real gebraucht werden; Kostenbudget für LLM-Summaries definiert.

### Phase 4 — Inkrementelles Update & Temporalität (optional)

- `IncrementalIngestionService`: Set-Merge neuer Episoden in den bestehenden Graphen ohne Rebuild (LightRAG); betroffene Communities selektiv neu berechnen.
- Bi-temporale Felder auf `RelationEdge` + `FactInvalidationPolicy` (widersprechende Fakten → `valid_to` setzen statt löschen; Graphiti). Event-Sourcing-Charakter: Episoden als immutable Provenance.
- **Gate:** nur für evolvierende Korpora / Agent-Memory (z. B. Pantau-Kontext). Sonst bleibt Phase-1-`MERGE`-Idempotenz ausreichend.

---

## 7. Öffentliche API (Skizze)

**Minimaler Aufwand — Happy Path:**

```python
from runic.ogm import create_driver
from runic_graph_rag import GraphRAG, Ontology

# FalkorDB ODER Neo4j — nur das create_driver-Argument wechselt:
driver = create_driver("falkordb", host="localhost", port=6379, graph="kb")
# driver = create_driver("neo4j", uri="bolt://localhost:7687", auth=("neo4j", "..."))

rag = GraphRAG.with_defaults(driver, ontology=Ontology.default())
rag.bootstrap_schema()                       # SchemaManager.sync_schema() intern
rag.ingest_text(open("doc.md").read())
answer = rag.query("Was sind die Hauptthemen?", mode="auto")
print(answer.text, answer.citations)
```

**Wiederverwendbar — eigene Bausteine einhängen (OCP/DIP):**

```python
rag = GraphRAG(
    driver,
    ontology=my_ontology,                    # eigene Entity-/Relation-Typen
    extractor=MyExtractor(model="ollama:gemma3"),
    embedder=OllamaEmbedder(dim=1024),
    retrievers=[VectorRetriever(...), FulltextRetriever(...)],
    reranker=RRFReranker(),
)
```

`GraphRAG.with_defaults(...)` ist die Tell-Don't-Ask-Facade mit vorverdrahteten Adaptern; der explizite Konstruktor ist der Erweiterungspfad. `mode="auto"` wählt per Dict-Dispatch zwischen local/hybrid/global anhand einer leichten Query-Klassifikation.

---

## 8. Reusability & minimaler Aufwand

- **Paketierung:** eigenständiges `runic-graph-rag` mit Extras (`[falkordb]`, `[neo4j]`, `[ollama]`, `[community]` = graspologic/MIT für Leiden, `[community-gpl]` = leidenalg/GPLv3 als Alternative). Kern hängt nur an `runic.ogm`, Pydantic AI, Pydantic — Backend-Treiber und Community-Detection kommen über das jeweilige Extra, der Kern bleibt permissiv lizenziert.
- **Ontologie als Konfiguration:** `Ontology.default()` liefert eine generische Typmenge; Projekte überschreiben via eigener `Entity`-Subklassen + Enum. Eine `Ontology` erzeugt die OGM-Modelle und das Extraktions-Constraint aus **einer** Quelle.
- **Schema-Bootstrap ohne Migrationen** in Dev via `sync_schema()`; `runic baseline` macht es produktionsreif — derselbe Workflow, den runic ohnehin vorgibt.
- **Sensible Defaults**, alles überschreibbar: jeder Port hat genau einen Default-Adapter, Austausch per Konstruktor.
- **Agent-Harness-Kompatibilität:** Da Extraktion und Synthese über Pydantic-AI-`Agent` laufen, sind Ollama/Gemma als Modell-Targets erstklassig nutzbar — passt zum local-first-Anspruch.

---

## 9. Geklärte Entscheidungen & Restrisiken

Die in v2 offenen Punkte sind entschieden. Jede Entscheidung ist als Default fixiert; Restrisiken sind explizit markiert.

### 9.1 Vektor-KNN je Backend — gelöst

Der `GraphStore`-Port bietet `vector_search(label, prop, query_vec, k) -> list[ScoredKey]` und liefert eine **normalisierte Cosine-Ähnlichkeit in [0, 1] (höher = ähnlicher)**. Damit ist der Threshold im Domänenkern backend-agnostisch; die Dialekt-Unterschiede leben ausschließlich im Adapter (dünner Raw-`session.execute`-Pfad, da der OGM-Query-Builder KNN-Procs nicht abbildet).

| | FalkorDB | Neo4j-Familie |
|---|---|---|
| Aufruf | `CALL db.idx.vector.queryNodes($label, $prop, $k, vecf32($q)) YIELD node, score` | `CALL db.index.vector.queryNodes($index, $k, $q) YIELD node, score` |
| Identifikation | Label **+** Property | **Index-Name** → Namenskonvention `{label}_{prop}_vec` bei Schema-Erstellung vergeben |
| Score-Semantik | Cosine-**Distanz** → normalisieren: `sim = (2 - score) / 2` | Cosine-**Ähnlichkeit** 0..1, bereits normalisiert |
| Vektor-Literal | `vecf32(...)`-Wrapper nötig | rohe Liste/`VECTOR` |
| Selbsttreffer ausschließen | `WHERE score > 0` nach Normalisierung | `WHERE score < 1` |

**Restrisiko:** Neuere Neo4j-Versionen verlangen für Vektorindizes zunehmend die explizite Cypher-`SEARCH`-Klausel statt der Prozedur; die exakte Syntax/Mindestversion ist gegen die Ziel-Neo4j-Version zu verifizieren. Der Neo4j-Adapter kapselt das hinter `vector_search()` — Proc oder `SEARCH` ist ein interner Zweig, keine API-Auswirkung.

### 9.2 Community-Detection-Bibliothek — gelöst

**Default: `graspologic.partition.hierarchical_leiden`** (MIT-Lizenz, Microsoft Research) — dieselbe Implementierung, die Microsoft GraphRAG und der LlamaIndex-GraphRAG-Pfad nutzen. Arbeitet auf einer NetworkX-Projektion des `Entity`-Subgraphen, Parameter `max_cluster_size` (Default 10). Permissive Lizenz → distributierbar ohne Copyleft-Folgen.

**Alternative: `leidenalg` + `python-igraph`** — funktional gleichwertig, aber **GPLv3** (Copyleft). Nur hinter dem separaten Extra `[community-gpl]`, nie Default, damit der Kern permissiv bleibt. Wheels für alle Plattformen inkl. macOS/Apple Silicon vorhanden.

Beide hinter dem optionalen `[community]`-Extra; ohne Phase 3 wird keine der beiden installiert.

**Restrisiko / Kostenwarnung:** Eager Global-Search, das alle Communities zusammenfasst, skaliert mit der Community-Zahl und wird auf großen Korpora schnell token-intensiv (dokumentierter Schwachpunkt von eager GraphRAG). → erzwingt die Lazy-Summary-Strategie aus 9.5.

### 9.3 Entity-Resolution — gelöst

Zweistufiger `EntityResolver` mit expliziten, testbaren Schwellen statt vergrabenem Magic Value:

1. **Deterministisch** — normalisierter Name (`casefold`, Unicode-NFKC, Whitespace) → `canonical_key`. Fängt exakte/quasi-exakte Dubletten billig ab.
2. **Vektoriell** — KNN auf `Entity.embedding`, **Merge bei normalisierter Cosine-Sim ≥ 0.92**, ausschließlich innerhalb desselben `EntityType`.
3. **Optional LLM-Tiebreak** — nur für das Grauband (0.82–0.92) als separater Adapter (OCP), per Default aus.

Schwelle und Grauband sind Konfig (`resolve_threshold`, `tiebreak_band`). **Restrisiko:** der Schwellenwert ist datensatzabhängig; er gehört in das Eval-Set aus Phase 1 (Precision/Recall der Resolution gegen einen gelabelten Mini-Korpus).

### 9.4 Nebenläufigkeit (sync) — gelöst

Per-Chunk-Extraktion/-Embedding über `ThreadPoolExecutor` (netz-I/O gibt GIL frei); Default `max_workers = min(8, rpm_limit)`. Ein `RateLimiter` (Token-Bucket) als Decorator um die LLM-/Embedder-Ports (SoC — Cross-Cutting, nicht inline). Graph-Writes laufen single-threaded in **einer** `Session` (Unit of Work) → keine Write-Contention. Konfig: `concurrency`, `requests_per_minute`.

### 9.5 Kostenkontrolle — gelöst

Ein `BudgetGuard`-Decorator auf dem LLM-Port (SoC/OCP) erzwingt harte Limits je Lauf (`max_llm_calls`, `max_tokens`). Gleaning-Pässe per Default 0 (opt-in). Phase-3-Summaries **lazy** (LazyGraphRAG: nur dynamisch gewählte Communities zur Query-Zeit zusammenfassen statt eager über alle) — adressiert direkt den Kostenausreißer aus 9.2. Extraktion und Embedding werden per Content-Hash gecacht.

### 9.6 N+1 beim Retrieval — gelöst (Designregel)

Die sync `Session` unterstützt Lazy-Loading direkt; im `GraphStore`-Adapter ist die Regel kodifiziert: Traversal-Reads immer mit `fetch=[...]`, Hop-Tiefe gedeckelt (Konfig, Default 2), Entity-Lookups nach `canonical_key` gebündelt. Reines Performancethema, kein Korrektheitsrisiko.

### Verbleibende echte Risiken

- **`graspologic`-Kompatibilität** mit der Ziel-NumPy/Python-Version vor Phase 3 verifizieren (Bibliothek hatte Phasen geringerer Pflege).
- **Extraktionsqualität bei lokalen Modellen** (Ollama/Gemma) — strukturierte Outputs sind schwächer als bei Frontier-Modellen; `strict`-Validierung + Gleaning als Gegenmittel, im Eval messen.

---

## 10. Nächster Schritt

Phase 0 + 1 als ein erstes Inkrement schneiden: Paketgerüst, Ports, OGM-Modelle, `IngestionService`, `LocalRetriever` — synchron, lauffähig gegen eine lokale FalkorDB- **und** eine Neo4j-Instanz (gleicher Code, Adapter über `create_driver`), mit `sync_schema()`-Bootstrap und einem Roundtrip-Test je Backend. Phasen 2–4 sind additiv und brechen die Phase-1-API nicht.

---

## Anhang A — Architecture Decision Records (ADRs)

Begründung aller substanziellen Entscheidungen dieses Dokuments. Format: Nygard-/MADR-Stil (Status, Kontext, Entscheidung, verworfene Alternativen, Konsequenzen). Datum durchgängig 2026-06-21, Decider: `jenreh`, Status `Accepted` sofern nicht anders vermerkt.

| ADR | Entscheidung | Betrifft |
|---|---|---|
| 001 | Dünne SDK auf runic statt eigenständigem Framework | §1, §4 |
| 002 | Hexagonale Architektur mit Protocol-Ports | §4 |
| 003 | CQRS-leichte Trennung Ingestion/Retrieval | §4 |
| 004 | Synchroner `Session`-Pfad statt `AsyncSession` | §1, §4 |
| 005 | Multi-Backend über `GraphStore`-Adapter | §1, §4.3 |
| 006 | Hybride Ontologie: harte Entity-Typen, weiche Relationen | §3, §5 |
| 007 | Generische `RELATES_TO`-Kante mit `rel_type`-Property | §5 |
| 008 | Schema über OGM-`Field`-Annotationen + 3-Stufen-Lifecycle | §5 |
| 009 | Provenance via `Chunk`→`Entity` `MENTIONS` | §5 |
| 010 | Pydantic AI als LLM-/Extraktions-Abstraktion | §6 |
| 011 | Phasenmodell mit opt-in Community/Temporalität (YAGNI) | §6 |
| 012 | Vektor-KNN-Abstraktion mit normalisierter [0,1]-Ähnlichkeit | §9.1 |
| 013 | `graspologic` (MIT) Default, `leidenalg` (GPL) opt-in | §9.2 |
| 014 | Zweistufige Entity-Resolution mit konfigurierbaren Schwellen | §9.3 |
| 015 | Nebenläufigkeit über `ThreadPoolExecutor` + `RateLimiter` | §9.4 |
| 016 | Kostenkontrolle: `BudgetGuard` + Lazy-Summaries + Cache | §9.5 |
| 017 | Retrieval: Dual-Level + Hybrid + RRF-Reranking | §6 (Phase 2) |
| 018 | N+1-Vermeidung als verbindliche Designregel | §9.6 |

---

### ADR-001: Dünne SDK auf runic statt eigenständigem Framework

**Kontext:** Microsoft GraphRAG, LightRAG, Graphiti und LlamaIndex bringen alle ihren eigenen Graph-/Vektor-Store mit. Es existiert mit `runic.ogm` bereits eine OGM- und Schema-Schicht über Cypher-DBs.

**Entscheidung:** `runic-graph-rag` ist eine dünne Schicht auf `runic.ogm` (Persistenz) + `runic.migrate` (Schema). Kein eigener Store, kein eigener Vektor-Store.

**Alternativen:**
- *Eigenständiges Framework (Fork eines bestehenden)* — verworfen: dupliziert Persistenz/Schema, Wartungslast, kein Mehrwert gegenüber runic.
- *LlamaIndex `PropertyGraphStore`-Adapter für runic schreiben* — verworfen: bindet an LlamaIndex-Lebenszyklus und -Abstraktionen, mehr Indirektion als nötig.

**Konsequenzen:**
- (+) Minimaler Code, Schema-Versionierung „gratis" über runic, eine konsistente Persistenz.
- (+) Reduziert Cloud-/Framework-Abhängigkeiten (local-first-Linie).
- (−) Funktionsumfang an runics OGM-Reife gekoppelt; fehlende Primitive (z. B. KNN im Query-Builder) müssen über Raw-Cypher im Adapter überbrückt werden.

### ADR-002: Hexagonale Architektur mit Protocol-Ports

**Kontext:** Jeder Pipeline-Schritt (Chunking, Extraktion, Resolution, Embedding, Retrieval, Reranking) hat mehrere plausible Implementierungen; LlamaIndex zeigt den Wert komponierbarer Extractor/Retriever.

**Entscheidung:** Ports & Adapters. Der Domänenkern hängt nur an `typing.Protocol`-Ports, Adapter binden Pydantic AI, Embedder, runic an. Konstruktor-Injektion.

**Alternativen:**
- *Konkrete Klassen mit Vererbung* — verworfen: verletzt DIP/OCP, schlecht testbar.
- *Fette Basisklasse `BaseGraphRAG`* — verworfen: verletzt ISP, zwingt Caller zu ungenutzten Methoden.

**Konsequenzen:**
- (+) DIP/ISP/OCP erfüllt; Adapter einzeln unit-testbar; neue Strategien ohne Kernänderung.
- (+) Domänenkern frei von runic-/LLM-Importen.
- (−) Mehr Dateien/Indirektion; Einstiegshürde für Gelegenheitsbeiträge höher.

### ADR-003: CQRS-leichte Trennung Ingestion/Retrieval

**Kontext:** Schreibpfad (Graph aufbauen) und Lesepfad (Graph abfragen) haben unterschiedliche Verantwortungen, Lebenszyklen und Skalierungseigenschaften.

**Entscheidung:** Getrennte `IngestionService` (Command) und `RetrievalService` (Query) statt eines Allzweck-Service.

**Alternativen:**
- *Ein `GraphRAGService` mit allem* — verworfen: verletzt SRP, vermischt zwei Änderungsgründe.
- *Volles CQRS mit getrennten Read-/Write-Modellen* — verworfen: YAGNI, gleiche Knoten, kein separater Read-Store nötig.

**Konsequenzen:**
- (+) SRP; jede Seite isoliert test- und optimierbar.
- (−) Etwas mehr Verdrahtung in der Facade.

### ADR-004: Synchroner `Session`-Pfad statt `AsyncSession`

**Kontext:** runic bietet `Session` und `AsyncSession`. Ziel ist die Unterstützung mehrerer Backends (FalkorDB + Neo4j-Familie) mit minimaler Pflege.

**Entscheidung:** Durchgängig synchrone `Session`. I/O-gebundene Ports (`Extractor`, `Embedder`) intern über `Agent.run_sync()`. Kein async-Pfad.

**Alternativen:**
- *`AsyncSession`* — verworfen: zwei parallele Codepfade über alle Backends zu pflegen; `AsyncSession` verbietet zudem Lazy-Loading (`LazyLoadError`).
- *Sync- und Async-Variante anbieten* — verworfen: doppelte Tests/Wartung ohne klaren Bedarf.

**Konsequenzen:**
- (+) Ein Codepfad, einfacheres mentales Modell, Lazy-Loading nutzbar.
- (−) Durchsatz braucht `ThreadPoolExecutor` (s. ADR-015) statt `asyncio.gather`; für netz-I/O-gebundene Calls praktisch gleichwertig.

### ADR-005: Multi-Backend über `GraphStore`-Adapter

**Kontext:** runic-OGM glättet die meisten Cypher-Unterschiede, aber Vektor-KNN, ungerichtetes `MERGE` und `relabel_nodes` differieren zwischen FalkorDB und der Neo4j-Familie.

**Entscheidung:** Backend-Spezifika ausschließlich im `GraphStore`-Adapter (ein Adapter pro Dialekt); Services/Domäne/Ontologie bleiben backend-agnostisch.

**Alternativen:**
- *Nur FalkorDB* — verworfen: explizites Ziel ist Neo4j-Unterstützung.
- *Verzweigungen in den Services* — verworfen: verletzt OCP, streut Dialekt-Wissen.

**Konsequenzen:**
- (+) Neues Backend = neuer Adapter, kein Kernänderung (OCP).
- (−) Je Dialekt ein dünner Raw-Cypher-Pfad zu pflegen und zu testen.

### ADR-006: Hybride Ontologie — harte Entity-Typen, weiche Relationen

**Kontext:** Rein schema-frei skaliert wegen Typ-Wildwuchs schlecht; rein starres Schema verlangt Vorab-Modellierung. LlamaIndex `SchemaLLMPathExtractor(strict=False)` zeigt den Mittelweg.

**Entscheidung:** Entity-Typen sind hart constrained (polymorphe runic-Labels + `EntityType`-Enum constraint den LLM); Relationstypen bleiben weich (Property, Fallback `RELATES_TO`).

**Alternativen:**
- *Vollständig schema-frei* — verworfen: inkonsistente Typen, teure Nachkonsolidierung.
- *Vollständig starres Schema (auch Relationen fix)* — verworfen: emergente Relationen erzwingen Schemawechsel.

**Konsequenzen:**
- (+) Versionierbare, saubere Entity-Labels bei gleichzeitig flexibler Relationssemantik.
- (+) Emergente Relationstypen ohne Migration.
- (−) Asymmetrie (Label vs. Property) muss im Retrieval bewusst behandelt werden.

### ADR-007: Generische `RELATES_TO`-Kante mit `rel_type`-Property

**Kontext:** Konsequenz aus ADR-006 für die konkrete Kantenmodellierung im OGM.

**Entscheidung:** Eine deklarierte `Relation`/`Edge` (`RELATES_TO`) trägt `rel_type`, `description`, `confidence` als Properties. Häufige `rel_type`-Werte können später zu echten Edge-Labels „promotet" werden (eigene `Relation` + Migration).

**Alternativen:**
- *Distinktes Edge-Label je Relationstyp* — verworfen für den Default: jeder neue Typ bräuchte eine deklarierte `Relation` + Migration; tötet die „weiche" Eigenschaft.

**Konsequenzen:**
- (+) Voll dynamische Relationstypen ohne Schemawechsel; idempotentes `relate()`.
- (−) Weniger graph-nativ (kein Edge-Label-Match); Promotion-Pfad für Hot-Types nötig, wenn label-basierte Queries gebraucht werden.

### ADR-008: Schema über OGM-`Field`-Annotationen + 3-Stufen-Lifecycle

**Kontext:** runic bietet `Field(index_type="VECTOR"|"FULLTEXT")`, `SchemaManager.sync_schema()`, `runic baseline` und versionierte Revisionen.

**Entscheidung:** Indizes/Constraints werden als `Field`-Annotation am Modell deklariert; Bootstrap in Dev über `sync_schema()`, Produktivierung über `runic baseline` → handgeschriebene Revisionen.

**Alternativen:**
- *Indizes von Hand in Migrationen pflegen, getrennt vom Modell* — verworfen: zwei Quellen der Wahrheit, Drift-Gefahr.

**Konsequenzen:**
- (+) Eine Quelle (Modell), aufwandsloser Dev-Bootstrap, versioniert in Prod — genau runics vorgesehener Workflow.
- (−) Vektor-`dimension` muss nach `baseline` einmalig vom Platzhalter `0` korrigiert werden.

### ADR-009: Provenance via `Chunk`→`Entity` `MENTIONS`

**Kontext:** Graphitis non-lossy Episodic-Edges erlauben Rückverfolgung von Fakten zu Quellen (Zitate, Debugging). Kosten dafür sind gering.

**Entscheidung:** Jeder extrahierte Knoten/Kante hält eine Provenance-Verbindung zum `Chunk` (`MENTIONS`, `source_chunk` auf der Kante).

**Alternativen:**
- *Keine Provenance* — verworfen: keine Zitate, schlechte Nachvollziehbarkeit von Resolution-Fehlern.
- *Volles Episode-Subgraph-Modell* — auf Phase 4 verschoben (YAGNI).

**Konsequenzen:**
- (+) Zitierfähige Antworten, einfacheres Debugging der Extraktion.
- (−) Mehr Kanten im Graphen.

### ADR-010: Pydantic AI als LLM-/Extraktions-Abstraktion

**Kontext:** Extraktion (strukturierte Outputs) und Synthese brauchen einen LLM-Client; eigene Abstraktion wäre Mehraufwand. Pydantic AI v1 ist bereits im Stack, `output_type` liefert validierte Strukturen.

**Entscheidung:** Extraktion und Synthese laufen über Pydantic-AI-`Agent`; keine eigene LLM-Schicht.

**Alternativen:**
- *Eigene LLM-Abstraktion* — verworfen: YAGNI, dupliziert Pydantic AI.
- *LangChain/LlamaIndex-LLM-Layer* — verworfen: schwergewichtige Abhängigkeit für wenig Nutzen.

**Konsequenzen:**
- (+) Validierte Extraktion via Enums (= Hybrid-Constraint aus ADR-006); Ollama/Gemma als Targets erstklassig (Agent-Harness-Linie).
- (−) Kopplung an Pydantic-AI-API-Stabilität.

### ADR-011: Phasenmodell mit opt-in Community/Temporalität (YAGNI)

**Kontext:** Community-Detection + hierarchische Summaries (Microsoft) und Bi-Temporalität (Graphiti) sind mächtig, aber teuer bzw. nur für bestimmte Use-Cases nötig.

**Entscheidung:** Kern = Phase 1–2 (hybride Extraktion + hybrides Retrieval). Community/Global (Phase 3) und inkrementell/temporal (Phase 4) sind optionale, gegateterte Pakete.

**Alternativen:**
- *Alles von Anfang an (GraphRAG-Vollumfang)* — verworfen: hohe Kosten/Komplexität ohne belegten Bedarf (YAGNI).

**Konsequenzen:**
- (+) Schneller, günstiger Kern mit 90 % des Werts; klare Erweiterungspunkte.
- (−) Global-Search/Temporalität erst nach zusätzlicher Arbeit verfügbar.

### ADR-012: Vektor-KNN-Abstraktion mit normalisierter [0,1]-Ähnlichkeit

**Kontext:** FalkorDB (`db.idx.vector.queryNodes(label, prop, k, vecf32(q))`) liefert eine Cosine-**Distanz**; Neo4j (`db.index.vector.queryNodes(indexName, k, q)`) eine fertige Cosine-**Ähnlichkeit** 0..1 und adressiert per Index-Namen statt Label+Property.

**Entscheidung:** Ein `GraphStore.vector_search(...)`-Port liefert eine **normalisierte Cosine-Ähnlichkeit in [0,1]**; FalkorDB-Distanz wird per `(2-score)/2` umgerechnet, Neo4j-Score unverändert übernommen. Threshold im Domänenkern arbeitet auf dieser einheitlichen Skala.

**Alternativen:**
- *Roh-Scores durchreichen* — verworfen: Threshold würde backend-abhängig, leakt Dialekt in die Domäne.

**Konsequenzen:**
- (+) Backend-agnostischer Resolver-Threshold; Dialekt-Wissen gekapselt.
- (−) Pro Dialekt ein verifizierter Raw-Cypher-Read; Neo4j braucht eine deterministische Index-Namenskonvention.

### ADR-013: `graspologic` (MIT) als Default-Community-Detection, `leidenalg` (GPL) opt-in

**Kontext:** Leiden ist Standard für Community-Detection. `leidenalg` ist **GPLv3**, `python-igraph` **GPL**; `graspologic` (Microsoft) ist **MIT** und nutzt dieselbe Leiden-Familie wie Microsoft GraphRAG.

**Entscheidung:** Default-`CommunityBuilder` nutzt `graspologic.partition.hierarchical_leiden` (MIT). `leidenalg`/`igraph` nur hinter dem separaten Extra `[community-gpl]`, nie Default.

**Alternativen:**
- *`leidenalg` als Default* — verworfen: vererbt Copyleft auf eine permissiv lizenzierte SDK.
- *igraphs eingebautes Leiden* — verworfen: ebenfalls GPL über `python-igraph`.

**Konsequenzen:**
- (+) Kern bleibt permissiv distributierbar; Out-of-the-box-Wheels.
- (+) Da hinter Phase-3-Port, berührt selbst die GPL-Variante den Kern nicht.
- (−) `graspologic`-Pflege/NumPy-Kompatibilität vor Phase 3 zu verifizieren (s. Restrisiken).

### ADR-014: Zweistufige Entity-Resolution mit konfigurierbaren Schwellen

**Kontext:** Entity-Resolution ist der Punkt, an dem schema-freie/hybride Extraktion ohne Konsolidierung zerfällt; ein einzelner Magic-Threshold ist schwer zu begründen.

**Entscheidung:** (1) deterministisch über normalisierten Namen → `canonical_key`; (2) vektoriell, Merge bei normalisierter Sim ≥ `resolve_threshold` (Default 0.92), nur innerhalb desselben `EntityType`; (3) optionaler LLM-Tiebreak nur im Grauband (Default 0.82–0.92), als separater Adapter, per Default aus.

**Alternativen:**
- *Nur Vektor-Threshold* — verworfen: verschenkt billige exakte Treffer, intransparent.
- *LLM für jede Resolution* — verworfen: Kosten, unnötig für klare Fälle.

**Konsequenzen:**
- (+) Billige Mehrheit deterministisch; LLM nur für die unsicheren wenigen (OCP-Adapter).
- (−) Schwellen sind datensatzabhängig → gehören ins Eval-Set (Precision/Recall).

### ADR-015: Nebenläufigkeit über `ThreadPoolExecutor` + `RateLimiter`-Decorator

**Kontext:** Folge aus ADR-004 (sync). Extraktion/Embedding sind netz-I/O-gebunden; Provider haben RPM/TPM-Limits; runic-`Session` ist nicht thread-safe.

**Entscheidung:** Per-Chunk-Extraktion/-Embedding parallel über `ThreadPoolExecutor` (`max_workers` aus Konfig); Token-Bucket-`RateLimiter` als Decorator um die LLM-/Embedder-Ports; Graph-Writes single-threaded in **einer** `Session` nach der Parallelphase.

**Alternativen:**
- *asyncio* — ausgeschlossen durch ADR-004.
- *Rate-Limit inline in den Adaptern* — verworfen: verletzt SoC; gehört als Cross-Cutting in einen Decorator.

**Konsequenzen:**
- (+) Paralleler I/O-Durchsatz ohne async; Limits zentral; keine Write-Contention.
- (−) Pool-Größe/Limits sind zu tunende Betriebsparameter.

### ADR-016: Kostenkontrolle — `BudgetGuard` + Lazy-Summaries + Cache

**Kontext:** Extraktions- und Summary-LLM-Calls dominieren die Kosten; eager Global-Search über alle Communities skaliert teuer.

**Entscheidung:** `BudgetGuard`-Decorator auf dem LLM-Port erzwingt harte Limits je Lauf (`max_llm_calls`, `max_tokens`); Gleaning-Pässe Default 0 (opt-in); Phase-3-Summaries **lazy** (LazyGraphRAG: nur dynamisch gewählte Communities zur Query-Zeit); Extraktion/Embedding per Content-Hash gecacht.

**Alternativen:**
- *Eager Summaries für alle Communities* — verworfen: token-intensiver Kostenausreißer.
- *Keine Budgetgrenzen* — verworfen: unkontrollierte Kosten bei großen Korpora.

**Konsequenzen:**
- (+) Defaults bevorzugen günstig; „gründlich" ist bewusst opt-in; harte Obergrenzen.
- (−) Lazy-Summaries verlagern etwas Latenz in die Query-Zeit.

### ADR-017: Retrieval — Dual-Level + Hybrid + RRF-Reranking

**Kontext:** LightRAG zeigt günstiges Dual-Level-Retrieval (low-level Entity / high-level Theme) ohne Community-Schritt; Graphiti/Zep kombinieren Vektor + BM25 + Traversal mit Reranking.

**Entscheidung:** Phase 2 kombiniert `VectorRetriever` + `FulltextRetriever` (+ High-Level-Theme-Retriever) komponierbar; `RRFReranker` (Reciprocal Rank Fusion) als Default, `CrossEncoderReranker` optional. Modus-Auswahl per Dict-Dispatch.

**Alternativen:**
- *Nur Vektor-Retrieval* — verworfen: schlechterer Recall bei mehrschrittigen/thematischen Fragen.
- *Eager Community-Global als Default-Retrieval* — verworfen: zu teuer für den Kern (→ Phase 3).

**Konsequenzen:**
- (+) Besserer Recall ohne Community-Kosten; Retriever einzeln testbar; neue Retriever via OCP.
- (−) Fusion/Reranking erhöht die Retrieval-Komplexität.

### ADR-018: N+1-Vermeidung als verbindliche Designregel

**Kontext:** Die sync `Session` erlaubt Lazy-Loading; ein Top-k-Seed mit anschließendem Attributzugriff kann k Folgequeries auslösen.

**Entscheidung:** Traversal-Reads im `GraphStore`/`LocalRetriever` immer mit `fetch=[...]`; Hop-Tiefe gedeckelt (Konfig, Default 2); Entity-Lookups nach `canonical_key` gebündelt. Lazy-Zugriff in Hot-Paths gilt als Bug (Review-Gate).

**Alternativen:**
- *Lazy-Loading im Retrieval zulassen* — verworfen: N+1-Last bei größeren Ergebnismengen.

**Konsequenzen:**
- (+) Vorhersagbare Query-Last; reines Performancethema, kein Korrektheitsrisiko.
- (−) Entwickler müssen die benötigten Relationen pro Read explizit deklarieren.
