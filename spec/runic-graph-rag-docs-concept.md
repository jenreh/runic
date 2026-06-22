# runic.rag — Documentation Concept

> Status: Plan v1 · Companion to [`spec/runic-graph-rag-concept.md`](./runic-graph-rag-concept.md)
> Editorial plan for the new **Graph-RAG** docs section (VitePress, under `docs/rag/`).

This document is the editor-in-chief's merged plan for documenting `runic.rag`.
It defines a shared style guide, a tight per-page outline (no two pages duplicate
material — they cross-link instead), the API each page owns, the source/example
files each drafter lifts verified snippets from, and the nav/homepage wiring.

It synthesizes five research passes (examples, concept, evaluation, API/config,
style+nav) — all cross-checked against the shipped code on branch
`feature/graph-rag`, **not** the German draft spec. Where the spec and the code
disagree, the code wins (see "Accuracy guardrails" below).

---

## Accuracy guardrails (every drafter MUST honor)

These are verified-against-source facts that contradict the draft spec or the
task brief. Do not propagate the errors.

- **Package is `runic.rag`.** Import: `from runic.rag import GraphRAG, Ontology, RagSettings`. Never `runic_graph_rag` / `runic-graph-rag`.
- **PyPI dist is `runic-py`; install extra is `graphrag`:** `uv add "runic-py[graphrag]"` (add a backend: `"runic-py[graphrag,falkordb]"`). Always quote the spec.
- **Retrieval modes are exactly `local`, `hybrid`, `auto`.** No `global` / `drift` (Phase-3, not shipped). `query()` raises `ValueError` on an unknown mode.
- **`auto` is a cheap heuristic, not an LLM classifier:** picks `local` when the query has `<= 8` tokens AND contains no broad-cue word (`all, across, compare, overall, themes, trends, summarize, summary, relationship, relationships, everything`); otherwise `hybrid`.
- **Four facade verbs:** `bootstrap_schema()`, `ingest_text(text, *, source)` (the `source=` kwarg is REQUIRED), `ingest_document(path)`, `query(q, *, mode="auto")`.
- **Construction:** `GraphRAG.with_defaults(driver=None, *, settings=None, ontology=None)` — all optional; `driver=None` builds the backend driver from settings. Prefer the **driverless** form (`GraphRAG.with_defaults(settings=...)`) as the documented default; show the explicit `create_driver(...)` form only on the configuration page's backend-selection section.
- **Default ontology types:** `Person, Organization, Location, Concept, Product, Event`. The "Company/Executive/Industry/…" set is the *tuned* example, not the default.
- **`Entity` has a `type: str` field** (indexed) in addition to its subtype label.
- **`Answer`:** `text: str`, `citations: list[Citation]`, `context: RetrievalContext | None` — always guard `context` for `None`. `Citation`: `chunk_id, source, text`.
- **Default models:** `gpt-5.4-nano` (LLM), `text-embedding-3-small` / dim `1536` (embeddings).
- **Only `RRFReranker` is a default adapter.** `CrossEncoderReranker` is an exported opt-in alternative, NOT wired by `with_defaults`.
- **`backend` accepts five values:** `falkordb, neo4j, memgraph, arcadedb, age`. Document FalkorDB + Neo4j as the primary/native path; mention the other three as valid config (brute-force vector/fulltext path).
- **`bootstrap_schema()` raises `ValueError` if `embedding_dim <= 0`** — surface as a precondition.
- **deepeval is a dev dependency, version `4.0.6`.** Metric classes are SUFFIXED: `FaithfulnessMetric`, `AnswerRelevancyMetric`, `ContextualRelevancyMetric`, `ContextualRecallMetric`, `ContextualPrecisionMetric` (and `GEval`, no suffix). There are NO un-suffixed aliases.
- **`ingest --source` (CLI) bypasses PDF/MD parsing** — it always text-loads. Auto-detection happens only on the no-`--source` `ingest_document` path.

---

## Shared style guide

(Drafters: this is the single source of truth for voice and mechanics. The
per-page plans below assume it.)

**Voice & tone**
- Second person, present tense, imperative for instructions ("Pass a driver to `GraphRAG`", "Ingest the document"). Match `docs/ogm/quickstart.md`.
- Open every page with a 1–3 sentence orientation paragraph, symbols in code spans, exactly like `docs/ogm/quickstart.md` ("`runic.ogm` maps Python classes to graph nodes and edges…").
- Module is `runic.rag` (code span) in prose; the product/section name is **Graph-RAG** (capitalized, hyphenated) in headings, nav, and links — mirroring `runic.migrate` vs "Migration".
- State the "why" briefly after the "how". Keep paragraphs to 2–4 sentences. No emojis. No marketing fluff in guide pages (the persuasive register lives only on `docs/index.md`).

**Headings & rules**
- Exactly one H1 per page = the page title, matching nav text where sensible. Section headers are H2; sub-steps are H3. Never skip a level.
- Separate major top-level sections on long pages with a horizontal rule `---` (as `ogm/quickstart.md` does). Do NOT put `---` between every H3.

**Code fences**
- `markdown.lineNumbers: true` is global — every fence already shows a gutter. Do NOT add `:line-numbers` or `{1,3}` highlight meta unless highlighting is genuinely needed. Bare ` ```python ` / ` ```bash ` is house style.
- Always tag the language: `python`, `bash`, `cypher`, `text`. No untagged fences.
- Python examples are import-complete and runnable (import line first: `from runic.rag import GraphRAG, Ontology, RagSettings`). Default to the FalkorDB path; show backend swaps as a one-line aside.
- CLI: show the command, then expected output as a trailing `#`-comment (migration Quick look style). Generated Cypher goes as `#`-prefixed comment lines beneath the Python.

**Containers (:::)**
- `::: info See also` for cross-reference blocks (one blank line, then `-` bullet links `[text](./page.md) — short description`, closing `:::` on its own line). This is the dominant pattern in `ogm/quickstart.md`.
- Bare `::: info` (no title) for short inline clarifications/caveats.
- `::: tip` for genuinely optional advice (e.g. "set `RUNIC_RAG_CACHE_DIR` to make re-ingestion cheap").
- `::: warning` only for cost / data-loss / footguns (embedding-dimension mismatch, LLM spend). Do not overuse.

**Cross-link format**
- In-body prose: relative paths WITH `.md` (`[concepts](./concepts.md)`). Cross-section: up one level with `.md` (`[OGM Quickstart](../ogm/quickstart.md)`).
- Nav/sidebar/hero/feature config: root-absolute, extension-less (`/rag/quickstart`).
- Links to source files: absolute GitHub blob URLs (`https://github.com/jenreh/runic/blob/main/examples/rag/01_quickstart.py`).
- In-prose page-name tokens are lowercase (`[concepts](./concepts.md)`); "See also" headings and homepage actions are Title Case.

**Install line (canonical)**
```bash
uv add "runic-py[graphrag]"   # or: pip install "runic-py[graphrag]"
```
With a backend: `uv add "runic-py[graphrag,falkordb]"`. Follow with the FalkorDB
docker line (`docker run -p 6379:6379 falkordb/falkordb` or
`docker compose -f docker-compose.test.yml up -d falkordb`) and an
`OPENAI_API_KEY` note (export or `.env`).

**Misc**
- Symbols in prose go in code spans: `GraphRAG`, `ingest_text()`, `RUNIC_RAG_TOP_K`, `examples/rag/01_quickstart.py`.
- End substantial pages with a `## Next steps` section wrapped in a single `::: info See also` block of bullet links.
- Config/mode tables are standard GFM pipe tables (auto-wrapped in a scroll container). Column shape for knobs: `Variable | Meaning | Default`.

---

## Page map & scope boundaries

Nine pages under `docs/rag/`, plus one new runnable example. Scope is tight —
each page OWNS its topic; siblings cross-link rather than re-explain.

| Page | Owns | Defers (cross-links) |
|---|---|---|
| `index.md` | Section landing + page map | everything |
| `concepts.md` | The *idea* of Graph-RAG; framework comparison; pipeline diagram | all API/how-to |
| `quickstart.md` | Smallest runnable loop | pipeline internals → ingestion; modes → retrieval |
| `ingestion.md` | How the graph is BUILT (chunk→extract→resolve→write, multi-doc, PDF, cost) | mode meanings → retrieval; env table → configuration; ontology design → ontologies |
| `retrieval.md` | How questions are ANSWERED (local/hybrid/auto, RRF, `Answer`) | how graph is built → ingestion; knob defaults → configuration |
| `ontologies.md` | Designing/optimizing entity types; A/B methodology | measuring quality → evaluation; full ontology API → api |
| `evaluation.md` | Measuring answer + retrieval + resolution quality with deepeval | tuning knobs defined in → configuration/retrieval |
| `configuration.md` | Full `RUNIC_RAG_*` reference, providers, backends, schema lifecycle, CLI | schema engine details → migration/*; concepts → concepts |
| `api.md` | Concise API reference (facade, ontology, domain, models, ports, adapters) | usage narrative → guide pages |

**Ownership of recurring topics (single home; everyone else links here):**
- Retrieval modes / RRF / `auto` heuristic → **retrieval.md**.
- The `RUNIC_RAG_*` env table + provider/backend switch → **configuration.md** (quickstart/ingestion show only the 2–3 knobs in context and link here).
- Schema lifecycle / vector-dim-from-0 gotcha → **configuration.md** (cross-linking `docs/migration/*`).
- Ontology design + A/B tuning → **ontologies.md**.
- The full domain value-object field tables → **api.md** (guide pages show only the fields they use inline).

---

## Per-page plans

### `index.md` — "Graph-RAG"
Mirror `docs/migration/index.md`: a 2–3 sentence `runic.rag` intro, then a single
bulleted list linking each page with a one-line description. Short. No code beyond
maybe none. Cross-links: all eight sibling pages.

### `concepts.md` — "What is Graph-RAG?"
Six-beat newcomer arc (no code in beats 1–4; first code in beat 5):
1. Classic vector RAG (the baseline they know).
2. Where vector-only RAG breaks: multi-hop + thematic/global questions.
3. Why a graph helps: entities, typed relations, source-chunk provenance (`MENTIONS`).
4. The hybrid ontology — hard entity types + soft `RELATES_TO` (`rel_type` property). The page's centerpiece; one-sentence forward-ref to ontologies.
5. `runic.rag` as a thin SDK on `runic.ogm` + `runic.migrate`; the canonical ~10-line happy path (from `01_quickstart.py`).
6. What's next — hand-off list; one honest sentence that corpus-level/global search is an optional, not-yet-shipped extension.
Plus: the 4-framework comparison table (3 columns, plain language) + one summarizing sentence; ONE Mermaid pipeline diagram (two lanes: ingest / query). Owns the conceptual model only.

### `quickstart.md` — "Quickstart"
Mirror `docs/ogm/quickstart.md` section rhythm: Installation → Connect → Ingest →
Ask → Next steps. Driverless `GraphRAG.with_defaults(settings=...)`,
`bootstrap_schema()`, `ingest_text(..., source=...)`, `query(...)`, print
`answer.text` + citations. Close with a `::: info See also` to concepts,
ingestion, retrieval.

### `ingestion.md` — "Ingesting documents"
Walk the pipeline (chunk → extract → resolve → write with `MENTIONS`, idempotent
`MERGE`). `ingest_text` vs `ingest_document` (txt/md/pdf dispatch). Multiple docs
into one graph + cross-doc entity dedup (`03_multiple_documents.py`), proven via
`answer.context`. Bounded PDF page range (`documents.load_pdf_pages`, from
`04_manager_magazin_pdf.py`). Cost/perf knobs in context: `BudgetGuard`
(`max_llm_calls`/`max_tokens`), content cache (`cache_dir`), batched embeddings
(`embed_batch_size`), `concurrency` + `requests_per_minute`. Show `IngestionReport`.
Usage-recommendations box. Defers mode meanings and the full env table.

### `retrieval.md` — "Retrieval & answers"
Precise `local` / `hybrid` / `auto` (exact heuristic: `<= 8` tokens & no broad cue
→ local). RRF fusion of vector + fulltext + highlevel. The `Answer` object
(`text`, `citations`, `context` with entities/chunks/relations) and grounding via
citations. When to pick each mode; how `top_k` / `max_hops` shift recall vs
precision. Based on `05_hybrid_retrieval.py` + the `answer.context` inspection
from `03_multiple_documents.py`.

### `ontologies.md` — "Designing & optimizing ontologies"
The optimization page (highest word-count budget). Three build paths:
`Ontology.default()`, `Ontology.from_types([...])` (`02_custom_ontology.py`),
custom `Entity` subclasses with extra Fields (`Ontology(entity_models=[...])`) —
keep the `labels=["Entity", T], primary_label="Entity"` signature exact. WHY
better types → cleaner neighbourhoods → sharper answers. The A/B methodology from
`04_manager_magazin_pdf.py` (same text, default vs tuned, compare typed-coverage +
answer quality). A concrete checklist (name types after your questions; 5–12 types;
avoid overlap; iterate against an eval set → link evaluation).

### `evaluation.md` — "Evaluating quality"
deepeval `4.0.6` mapping: `runic.rag` `Answer` → `LLMTestCase` (`input`=question,
`actual_output`=`answer.text`, `retrieval_context`=`[c.text for c in
answer.context.chunks]`, `expected_output`=golden). The five RAG metrics and what
each catches (Faithfulness, AnswerRelevancy, ContextualRelevancy, ContextualRecall,
ContextualPrecision) in a failure-isolation table. Build a small golden set; run
`evaluate()` / `assert_test()` in pytest; read scores. A section on entity-resolution
+ retrieval quality (deterministic graph-level count check + a `GEval` entity metric;
sweep `resolve_threshold` / `top_k` / `max_hops`). Close with the iteration loop.
Reference `examples/rag/06_evaluation.py`. Note deepeval needs an OpenAI key for
LLM-judged metrics (or the key-free `ClaudeCLIModel` judge). Use the verified
`*Metric`-suffixed class names.

### `configuration.md` — "Configuration & deployment"
Reference page. Full `RUNIC_RAG_*` table (var | meaning | default), grouped
(LLM / embeddings / credentials / backend / chunking / resolution / concurrency /
cost / retrieval). Note the two UNPREFIXED vars (`OPENAI_API_KEY`,
`OLLAMA_BASE_URL`). Provider switch (OpenAI vs Ollama — BOTH `llm` AND `embedding`
provider must switch) and backend switch (FalkorDB vs Neo4j; mention the
brute-force trio). Schema lifecycle: `bootstrap_schema()` for dev; `runic baseline`
+ revisions for prod; the vector-dim-from-0 gotcha — cross-linking `docs/migration/*`.
The CLI (`python -m runic.rag bootstrap|ingest|query`, with the `--source`
text-only caveat). A `.env` snippet. This page OWNS the explicit `create_driver(...)`
backend-selection example.

### `api.md` — "API Reference"
Mirror `docs/ogm/api.md` / `docs/migration/api.md`: the manually-maintained-note
blockquote, then grouped sections — `GraphRAG` facade (`with_defaults` +
constructor + 4 verbs), `Ontology`, `RagSettings`/`load_settings`, domain value
objects (full field tables: `Answer`, `Citation`, `RetrievalContext`, `EntityHit`,
`ChunkHit`, `RelationHit`, `Extraction` family, `IngestionReport`), OGM models
(`Entity` + subtypes, `Chunk`/`ChunkNode`, `RelationEdge`), the 9 Ports, and a
port → default-adapter table. Signatures + one-line descriptions. Flag the
`CrossEncoderReranker`-is-not-a-default correction.

---

## New example: `examples/rag/06_evaluation.py`

Runnable deepeval evaluation. Ingest a tiny engineered corpus (one entity referred
to several ways, to exercise resolution), define 3–4 goldens
(question + expected answer), build an `LLMTestCase` per question, run
`AnswerRelevancyMetric` + `FaithfulnessMetric` + `ContextualRecallMetric` (plus
optionally `ContextualPrecisionMetric` + a `GEval` entity metric) via `evaluate()`,
print scores. House style of other `examples/rag/*.py`: module docstring with
Prerequisites + Run it; `# ruff: noqa: T201`; `dotenv` load; FalkorDB localhost
with a graph name unique to this example (`runic_rag_ex06`); `OPENAI_API_KEY`
guard (for the *pipeline*; the judge can be key-free). Default the judge to a
key-free path where practical. Must pass ruff. Keep under ~180 lines. Add an
"Example 6" row + entry to `examples/rag/README.md`.

---

## Nav, sidebar & homepage wiring

**Nav (`docs/.vitepress/config.mts`):** add a `Graph-RAG` dropdown immediately
after the `Migration` object, with items: What is Graph-RAG?, Quickstart,
Ingesting documents, Retrieval & answers, Designing & optimizing ontologies,
Evaluating quality, Configuration & deployment, API Reference. (Dropdowns omit the
section-root link, matching OGM/Migration.)

**Sidebar (`config.mts`):** add a `'/rag/'` key BEFORE the `'/'` catch-all, with a
group header `text: 'Graph-RAG', link: '/rag/'` (the `link` surfaces the landing
page) and the same eight items.

**Homepage (`docs/index.md`):**
1. New 7th feature card (lucide `network` icon), title "Graph-RAG".
2. New 3rd `alt` hero action "Graph-RAG Quickstart" → `/rag/quickstart`.
3. New "Quick look — Graph-RAG" H2 between the Migration Quick look and "There's more under the surface", with the import-complete facade snippet.
4. Optional "Where to go next" bullets for Quickstart and ontologies.

---

## Files drafters lift from (all absolute)

- Voice/structure: `/Users/jens/Workspace/projekte/runic/docs/ogm/quickstart.md`, `/Users/jens/Workspace/projekte/runic/docs/migration/index.md`, `/Users/jens/Workspace/projekte/runic/docs/ogm/api.md`, `/Users/jens/Workspace/projekte/runic/docs/migration/api.md`.
- Examples: `/Users/jens/Workspace/projekte/runic/examples/rag/01_quickstart.py` … `05_hybrid_retrieval.py`, `/Users/jens/Workspace/projekte/runic/examples/rag/README.md`.
- API surface: `/Users/jens/Workspace/projekte/runic/runic/rag/{__init__,facade,config,ontology,domain,models,ports,cli,exceptions,store}.py`, `/Users/jens/Workspace/projekte/runic/runic/rag/services/{ingestion,retrieval}.py`.
- deepeval pattern: `/Users/jens/Workspace/projekte/runic/tests/evals/{README.md,claude_cli_model.py,metrics.py}`.
- Concept source (German; §2 framework table): `/Users/jens/Workspace/projekte/runic/spec/runic-graph-rag-concept.md`.
- Schema gotcha: `/Users/jens/Workspace/projekte/runic/docs/migration/schema.md` (line 68).
- Menu wiring: `/Users/jens/Workspace/projekte/runic/docs/.vitepress/config.mts`, `/Users/jens/Workspace/projekte/runic/docs/index.md`; confirm/add Mermaid in `/Users/jens/Workspace/projekte/runic/docs/package.json`.
