# Evaluating quality

`runic.rag` answers questions by retrieving evidence from a graph and synthesizing text over it. Each of those stages can fail in its own way, so "is the answer good?" is really three questions: did retrieval find the right context, did the synthesizer stay faithful to it, and did entity resolution build a clean graph in the first place. This page shows how to measure all three with [deepeval](https://github.com/confident-ai/deepeval) (a dev dependency, pinned to `4.0.6`).

The retrieval and answer metrics are **LLM-judged**: a judge model reads the question, the answer, and the retrieved context and scores them. That makes results *directional*, not exact — the same test case can score `0.83` one run and `0.79` the next. Pin the judge model, average two or three runs, and watch trends rather than absolute decimals. The entity-resolution check, by contrast, is a deterministic graph assertion with no LLM in the loop.

---

## What you need

Evaluation reuses the same ingest-then-query loop as the rest of the SDK, plus deepeval and a judge LLM.

```bash
uv add "runic-py[graphrag,falkordb]"   # SDK + FalkorDB driver
docker run -p 6379:6379 falkordb/falkordb   # a running graph
export OPENAI_API_KEY=sk-...                 # or put it in .env
```

deepeval is **not** a runtime dependency of `runic.rag` — it ships as a dev dependency (`deepeval==4.0.6`) so it is on the path when you run examples and tests with `uv run`. The LLM-judged metrics need a judge model:

- **OpenAI (default):** export `OPENAI_API_KEY`. deepeval picks it up automatically — the same key the SDK already uses for extraction and synthesis.
- **Key-free local judge:** the repo ships a `ClaudeCLIModel` that shells out to the local `claude -p` CLI (it reuses your Claude Code login, so no extra key). See [`tests/evals/claude_cli_model.py`](https://github.com/jenreh/runic/blob/main/tests/evals/claude_cli_model.py) and pass it as the `model=` of any metric.

The verified import block — note that every metric class is **`Metric`-suffixed**, while `GEval` has no suffix and there are no un-suffixed aliases:

```python
from deepeval import assert_test, evaluate
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
```

::: tip
Set `RUNIC_RAG_CACHE_DIR` (or `cache_dir` on `RagSettings`) before you ingest the eval corpus. Re-running the suite then re-uses cached extraction/embeddings instead of paying for them again on every measure-tune-measure loop.
:::

---

## Mapping an `Answer` to an `LLMTestCase`

deepeval scores `LLMTestCase` objects. The whole bridge from `runic.rag` to deepeval is one small adapter that reads an `Answer` and the question that produced it. The `Answer.context` is `RetrievalContext | None`, so guard it before reading `.chunks`:

```python
from runic.rag import Answer
from deepeval.test_case import LLMTestCase


def answer_to_test_case(
    question: str, answer: Answer, golden: str | None = None
) -> LLMTestCase:
    """Map a runic.rag Answer onto a deepeval LLMTestCase."""
    chunks = answer.context.chunks if answer.context else []
    return LLMTestCase(
        input=question,
        actual_output=answer.text,
        retrieval_context=[hit.text for hit in chunks],
        expected_output=golden,
        name=question,
    )
```

The field correspondence is exact:

| `LLMTestCase` field | Source in `runic.rag` | Notes |
| --- | --- | --- |
| `input` | the question you passed to `rag.query(...)` | the user's question |
| `actual_output` | `answer.text` | the synthesized answer |
| `retrieval_context` | `[hit.text for hit in answer.context.chunks]` | `ChunkHit.text` per retrieved chunk; `[]` when `context is None` |
| `expected_output` | your hand-authored golden answer | optional; required only by recall/precision |
| `name` | the question (or any stable id) | labels the case in the report |

::: info
In `local` mode (a neighbourhood walk) retrieval can return only a handful of chunks, so `retrieval_context` is short by design. That is not a bug to paper over — a thin context is itself a recall signal. If `ContextualRecallMetric` is low and the context is nearly empty, the fix is in retrieval, not in the test.
:::

---

## The five core RAG metrics

Run the right metric for the failure you suspect. The first three read the retrieved context and diagnose the **retriever**; the last two read the answer and diagnose the **synthesizer**. Recall and precision additionally need an `expected_output`.

| Metric | Answers | Reads | Catches | Knob to turn |
| --- | --- | --- | --- | --- |
| `ContextualRecallMetric` | Did retrieval fetch *enough* of what the answer needs? | context + `expected_output` | missing evidence, under-retrieval | raise `top_k` / `max_hops`; try `hybrid` |
| `ContextualPrecisionMetric` | Is the *relevant* context ranked above the noise? | context + `expected_output` | good chunks buried under junk | reranker; lower `top_k`; tighter types |
| `ContextualRelevancyMetric` | What fraction of the context is actually on-topic? | context + question | retrieving off-topic chunks | tighten ontology types; lower `top_k` |
| `FaithfulnessMetric` | Is every claim grounded in the context? | answer + context | hallucination, unsupported claims | synthesis prompt |
| `AnswerRelevancyMetric` | Does the answer actually address the question? | answer + question | rambling, off-question answers | synthesis prompt |

The mental model: **recall + precision + relevancy** tell you whether the retriever did its job; **faithfulness + answer-relevancy** tell you whether the synthesizer did its job. A low faithfulness score with high recall means the context was there and the model ignored it — a generation problem. A low recall score means the context was never retrieved — a retrieval problem. Diagnosing which half is broken is the entire point of splitting the metrics.

```python
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)

# Judge defaults to OpenAI via OPENAI_API_KEY. Pass model=ClaudeCLIModel()
# for the key-free local judge instead.
metrics = [
    ContextualRecallMetric(threshold=0.7),
    ContextualPrecisionMetric(threshold=0.7),
    ContextualRelevancyMetric(threshold=0.7),
    FaithfulnessMetric(threshold=0.7),
    AnswerRelevancyMetric(threshold=0.7),
]
```

---

## Building a golden set

A golden set is a handful of `(question, expected_answer)` pairs written against the **real corpus** you ingest. Hand-author them — do **not** auto-generate `expected_output` from the same model under test, which would make the eval grade itself. Three to four well-chosen pairs are enough to catch regressions; include at least one **broad, thematic** question to exercise hybrid recall (the kind `auto` mode routes to `hybrid`).

```python
# A golden = a question + the answer a careful human would give from the corpus.
GOLDENS: list[tuple[str, str]] = [
    (
        "Who was the first computer programmer and why?",
        "Ada Lovelace, for her notes on Babbage's Analytical Engine "
        "describing an algorithm to compute Bernoulli numbers.",
    ),
    (
        "What machine did Ada Lovelace and Charles Babbage work on?",
        "The Analytical Engine.",
    ),
    # A broad, thematic question — forces hybrid retrieval to fuse evidence
    # across multiple chunks rather than a single neighbourhood walk.
    (
        "Summarize the relationship between Lovelace, Babbage, and their work.",
        "Lovelace collaborated with Babbage in London on the Analytical "
        "Engine and is credited as the first programmer for her algorithmic notes.",
    ),
]
```

The broad question matters: a corpus can ace every narrow lookup yet collapse on "summarize…" or "compare…" because those need recall *across* the graph. Keeping one such question honest is what tells you whether `hybrid` is pulling its weight.

---

## Running it

There are two entry points. Use `evaluate()` for an exploratory, scored report while tuning; use `assert_test()` inside a pytest for a CI gate that fails the build.

```python
from runic.rag import GraphRAG, Ontology, RagSettings
from deepeval import evaluate

settings = RagSettings(falkordb_graph="rag_eval")
rag = GraphRAG.with_defaults(settings=settings, ontology=Ontology.default())
rag.bootstrap_schema()
rag.ingest_text(_CORPUS, source="eval-corpus")  # seed once, then evaluate

cases = [
    answer_to_test_case(q, rag.query(q), golden=g) for q, g in GOLDENS
]
result = evaluate(test_cases=cases, metrics=metrics)
```

`evaluate()` prints a per-case scorecard and returns an `EvaluationResult`. Read individual scores from `result.test_results[*].metrics_data[*]` — each entry exposes `.name`, `.score`, `.success`, and `.reason` (the judge's rationale, which is the most useful field when a score surprises you):

```python
for test_result in result.test_results:
    for md in test_result.metrics_data:
        print(f"{md.name:24} score={md.score:.2f} pass={md.success}")
        if not md.success:
            print(f"  why: {md.reason}")
```

For CI, wrap each case in a parametrized pytest and call `assert_test()` — it raises `AssertionError` when a metric falls below its threshold, so a quality regression turns the build red. This mirrors the existing runic eval suites in [`tests/evals/`](https://github.com/jenreh/runic/blob/main/tests/evals/README.md):

```python
import pytest
from deepeval import assert_test


@pytest.mark.parametrize(("question", "golden"), GOLDENS)
def test_rag_quality(question: str, golden: str) -> None:
    case = answer_to_test_case(question, rag.query(question), golden=golden)
    assert_test(test_case=case, metrics=metrics)
```

```bash
uv run deepeval test run path/to/test_rag_quality.py
# Each case is judged against every metric; the run fails on any threshold miss.
```

---

## Measuring entity resolution & retrieval quality

Answer-level metrics tell you *that* retrieval is weak but not *why*. Most retrieval problems trace back to the graph: if entity resolution over-splits (two mentions of "Acme" become two nodes) recall drops, and if it over-merges (two different "Smith"s collapse into one) precision drops. Measure the graph directly.

### 1. A deterministic graph-level check (no LLM)

Ingest a tiny corpus where you already know the answer — the same real entity appears under several aliases — then assert that resolution collapsed them onto a single canonical entity. This is a plain Cypher count, so it is fast, free, and exactly reproducible.

```python
from runic.ogm.driver.factory import create_driver
from runic.rag import GraphRAG, Ontology, RagSettings

# A corpus where "Acme Corp", "Acme", and "ACME Corporation" are the SAME company.
_ALIASED = """\
Acme Corp launched a new product in Berlin.
Later that year, Acme expanded into Munich.
ACME Corporation reported record revenue.
"""

settings = RagSettings(falkordb_graph="res_eval")
driver = create_driver("falkordb", host=settings.falkordb_host,
                       port=settings.falkordb_port, graph=settings.falkordb_graph)
driver.execute("MATCH (n) DETACH DELETE n", {})  # start clean & comparable

rag = GraphRAG.with_defaults(driver, settings=settings,
                             ontology=Ontology.from_types(["Company", "Location"]))
rag.bootstrap_schema()
rag.ingest_text(_ALIASED, source="aliases")

# One canonical company expected. More -> over-split (threshold too high).
# A merged Acme+something-else -> over-merge (threshold too low).
result = driver.execute(
    "MATCH (e:Entity) WHERE e.type = 'Company' "
    "RETURN count(DISTINCT e.canonical_key) AS companies", {}
)
companies = int(result.rows[0][0])
assert companies == 1, f"expected 1 canonical company, got {companies}"
```

Counting `DISTINCT e.canonical_key` is the whole test: too many keys means resolution **over-split** (raise nothing — *lower* the threshold so near-duplicates merge), one key holding genuinely different entities means it **over-merged** (raise the threshold). Tune with `RagSettings`:

```python
settings = RagSettings(
    resolve_threshold=0.92,   # cosine sim to auto-merge a mention onto an entity
    tiebreak_low=0.82,        # below this -> always a new entity
    tiebreak_high=0.92,       # above this -> always merge
    llm_tiebreak=False,       # in [low, high]: ask the LLM when True, else split
)
```

### 2. A `GEval` entity-correctness metric (answer level)

For answers that should name specific entities, a custom `GEval` metric judges whether the right entities appear — the same pattern the runic skill suites use in [`tests/evals/metrics.py`](https://github.com/jenreh/runic/blob/main/tests/evals/metrics.py):

```python
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

entity_correctness = GEval(
    name="EntityCorrectness",
    criteria=(
        "Judge whether 'actual output' names the same key entities (people, "
        "companies, places) as 'expected output', without inventing entities "
        "absent from the reference."
    ),
    evaluation_params=[
        LLMTestCaseParams.INPUT,
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.EXPECTED_OUTPUT,
    ],
    threshold=0.7,
)
```

### Sweeping the knobs

Resolution and retrieval each have a precision/recall trade-off. Sweep the resolution knobs (`resolve_threshold`, `tiebreak_low`, `tiebreak_high`) against the graph check, and the retrieval knobs (`top_k`, `max_hops`) against the contextual metrics, then read the grid:

| Change | Effect on recall | Effect on precision |
| --- | --- | --- |
| `resolve_threshold` ↑ | ↓ (more over-split) | ↑ (fewer wrong merges) |
| `resolve_threshold` ↓ | ↑ (aliases merge) | ↓ (risk over-merge) |
| `top_k` ↑ | ↑ (more candidates) | ↓ (more noise) |
| `max_hops` ↑ | ↑ (wider neighbourhood) | ↓ (drift to weak links) |

Knob definitions and their env-var forms live on the [configuration](./configuration.md) page; here you only need to know which direction each one pushes recall versus precision.

---

## The iteration loop

Evaluation is a loop, not a gate: measure, change exactly one thing, re-measure. Let the failing metric pick the lever, change a single `RagSettings` field (or the ontology / synthesis prompt), and re-run the same golden set so the deltas are comparable.

```text
                    ┌─ low ContextualRecall ──────► raise top_k / max_hops,
                    │                                switch to mode="hybrid",
                    │                                suspect over-SPLIT resolution
                    │                                (lower resolve_threshold)
                    │
                    ├─ low ContextualPrecision ───► lower top_k, add a stronger
   weak score? ─────┤    / ContextualRelevancy      reranker (CrossEncoderReranker),
                    │                                tighten ontology types,
                    │                                suspect over-MERGE resolution
                    │                                (raise resolve_threshold)
                    │
                    ├─ low Faithfulness ──────────► tune the synthesis prompt
                    │                                (the answer ignored the context)
                    │
                    └─ low AnswerRelevancy ───────► tune the synthesis prompt
                                                     (the answer drifted off-question)
```

Each leaf names the field to touch: retrieval breadth is `RagSettings.top_k` and `RagSettings.max_hops` (or `mode="hybrid"` on the query); ranking is the reranker (the default is `RRFReranker`; `CrossEncoderReranker` is an exported opt-in you wire via the [`GraphRAG`](./api.md) extension constructor); graph cleanliness is `RagSettings.resolve_threshold` and the tiebreak band; and grounding lives entirely in synthesis. The ontology is the cheapest high-leverage change of all — see [ontologies](./ontologies.md) for why tuning entity types sharpens both recall and precision at once.

---

## Cost & determinism

::: warning
Every LLM-judged metric is a model call, and you pay per case × per metric × per run. Five metrics over four goldens averaged across three runs is sixty judge calls. Keep the golden set small, reserve `strict_mode=True` (binary pass/fail) for hard CI gates rather than exploratory runs, and seed a fixed corpus so ingestion is reproducible. The deterministic resolution check costs nothing — lean on it first, and reach for the judge only for what genuinely needs language understanding.
:::

The LLM-judged metrics need an OpenAI key (`OPENAI_API_KEY`, the default judge) or the key-free `ClaudeCLIModel`. The deterministic entity-resolution check needs neither — only a running FalkorDB.

---

## Next steps

::: info See also
- [examples/rag/06_evaluation.py](https://github.com/jenreh/runic/blob/main/examples/rag/06_evaluation.py) — the runnable end-to-end evaluation: ingest a corpus, score a golden set, and assert resolution quality.
- [retrieval](./retrieval.md) — `local` / `hybrid` / `auto` modes and how `top_k` / `max_hops` shape the context you measure here.
- [ontologies](./ontologies.md) — tuning entity types, the cheapest lever on both recall and precision.
- [configuration](./configuration.md) — every `RagSettings` knob (`resolve_threshold`, tiebreak band, `top_k`, `max_hops`) and its `RUNIC_RAG_*` env var.
- [api](./api.md) — `Answer`, `RetrievalContext`, `ChunkHit`, and the `GraphRAG` extension constructor.
:::
