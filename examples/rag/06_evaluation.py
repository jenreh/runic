"""Example 6 — evaluating answer quality with deepeval.

The previous examples *show* answers; this one *scores* them. It ingests a tiny,
known corpus, defines a handful of **goldens** (a question paired with the answer
we expect), runs each question through :meth:`GraphRAG.query`, and grades the
result with three reference RAG metrics from `deepeval`:

  * ``AnswerRelevancyMetric``    — does ``answer.text`` actually address the
    question? (no expected answer needed)
  * ``FaithfulnessMetric``       — is every claim in ``answer.text`` grounded in
    the retrieved chunks, i.e. no hallucination beyond the evidence?
  * ``ContextualRecallMetric``   — did retrieval surface the chunks needed to
    support the *expected* answer? This is the metric that rewards a good graph +
    hybrid fusion: if recall is low, the synthesizer never had the evidence.

The bridge from runic to deepeval is one tiny adapter,
:func:`answer_to_test_case`, which maps an :class:`~runic.rag.domain.Answer` onto
a :class:`deepeval.test_case.LLMTestCase`:

    input            = the question
    actual_output    = answer.text
    expected_output  = the golden answer
    retrieval_context = [chunk.text for chunk in answer.context.chunks]

The judge model is deepeval's OpenAI default (``model=None`` -> ``GPTModel``),
which reads ``OPENAI_API_KEY`` — the same key this pipeline already needs for
extraction, embedding, and synthesis. (To judge with a different provider, pass
e.g. ``AnthropicModel(...)`` or ``OllamaModel(...)`` from ``deepeval.models``.)

Prerequisites:
  * A running FalkorDB:  docker run -p 6379:6379 -it --rm falkordb/falkordb
  * An OpenAI key:  OPENAI_API_KEY=sk-...  (pipeline AND the deepeval judge)

Run it:
    uv run python examples/rag/06_evaluation.py

CI gate: the same mapping powers a pytest assertion — in a test, swap
``evaluate(...)`` for ``assert_test(test_case, metrics)`` to fail the build when
a metric drops below its threshold.
"""
# ruff: noqa: T201 - examples print their output to stdout for the reader.

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

from deepeval import evaluate
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
)
from deepeval.test_case import LLMTestCase
from dotenv import load_dotenv

from runic.rag import GraphRAG, RagSettings, load_settings

if TYPE_CHECKING:
    from deepeval.metrics import BaseMetric

    from runic.rag.domain import Answer

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_GRAPH_NAME = "runic_rag_ex06"

# ---------------------------------------------------------------------------
# A tiny, known corpus. One entity is named three ways — "Helios Energy",
# "Helios", and "the company" — so entity resolution has to merge them for the
# graph to connect founder, product, and market facts. Goldens below probe
# exactly those connections.
# ---------------------------------------------------------------------------

CORPUS: dict[str, str] = {
    "helios_overview.txt": (
        "Helios Energy is a renewable power company based in Lisbon. Helios was "
        "founded in 2014 by Mara Quinn, an electrical engineer. The company "
        "builds grid-scale battery storage systems."
    ),
    "helios_product.txt": (
        "The SOLARK-9000 is Helios Energy's flagship battery. Each SOLARK-9000 "
        "unit stores up to four megawatt-hours and uses lithium-iron-phosphate "
        "cells chosen for their long cycle life and recyclability."
    ),
    "helios_market.txt": (
        "Demand for long-duration energy storage is rising as grids add wind and "
        "solar capacity. Helios competes on cycle life rather than price, and "
        "Mara Quinn argues durability will decide which storage vendors endure."
    ),
}

# (question, expected_answer) pairs. The last one is deliberately broad/thematic
# to exercise hybrid recall across all three source documents.
GOLDENS: list[tuple[str, str]] = [
    ("Who founded Helios Energy?", "Mara Quinn founded Helios Energy in 2014."),
    (
        "What is the SOLARK-9000?",
        "The SOLARK-9000 is Helios Energy's flagship grid-scale battery storing "
        "up to four megawatt-hours, using lithium-iron-phosphate cells.",
    ),
    (
        "Where is Helios Energy based?",
        "Helios Energy is based in Lisbon.",
    ),
    (
        "Summarise Helios Energy's strategy and how it competes.",
        "Helios Energy builds grid-scale battery storage and competes on cycle "
        "life and recyclability rather than price, betting that durability wins.",
    ),
]


def answer_to_test_case(
    question: str,
    answer: Answer,
    *,
    golden: str,
    name: str | None = None,
) -> LLMTestCase:
    """Adapt a runic :class:`Answer` into a deepeval :class:`LLMTestCase`.

    ``retrieval_context`` is what makes the RAG metrics meaningful: faithfulness
    grades ``actual_output`` *against these chunks*, and recall grades whether
    these chunks cover the ``expected_output``. We guard ``answer.context`` being
    ``None`` (a fully empty retrieval) so the mapping never raises.
    """
    chunks = answer.context.chunks if answer.context is not None else []
    return LLMTestCase(
        input=question,
        actual_output=answer.text,
        expected_output=golden,
        retrieval_context=[chunk.text for chunk in chunks],
        name=name or question,
    )


def build_metrics(
    judge: str | None = None, *, threshold: float = 0.7
) -> list[BaseMetric]:
    """Build the reference RAG metric suite, all sharing one judge model.

    ``judge=None`` selects deepeval's OpenAI default (``GPTModel`` via
    ``OPENAI_API_KEY``). Recall uses a gentler threshold because retrieval breadth
    is the hardest bar for a tiny graph to clear.
    """
    return [
        AnswerRelevancyMetric(model=judge, threshold=threshold),
        FaithfulnessMetric(model=judge, threshold=threshold),
        ContextualRecallMetric(model=judge, threshold=0.6),
    ]


def _require_openai_key() -> None:
    """Exit early with a clear message if no OpenAI key is configured."""
    if os.getenv("OPENAI_API_KEY"):
        return
    log.error(
        "OPENAI_API_KEY is not set. This example calls OpenAI for extraction, "
        "embedding, synthesis, AND the deepeval judge model."
    )
    log.error("Set it in your shell or .env, then re-run:")
    log.error("  export OPENAI_API_KEY=sk-...")
    log.error("  uv run python examples/rag/06_evaluation.py")
    sys.exit(1)


def _build_settings() -> RagSettings:
    """Load settings from the environment, pinning this example's graph name."""
    return load_settings().model_copy(update={"falkordb_graph": _GRAPH_NAME})


def _ingest_corpus(rag: GraphRAG) -> None:
    """Ingest the corpus, logging a one-line write report per source."""
    for source, text in CORPUS.items():
        report = rag.ingest_text(text, source=source)
        log.info(
            "  %s: %d chunks, %d entities, %d relations",
            source,
            report.chunks,
            report.entities,
            report.relations,
        )


def _build_test_cases(rag: GraphRAG) -> list[LLMTestCase]:
    """Answer every golden question and adapt each result into a test case."""
    cases: list[LLMTestCase] = []
    for question, golden in GOLDENS:
        log.info("Querying: %s", question)
        answer = rag.query(question)
        cases.append(answer_to_test_case(question, answer, golden=golden))
    return cases


def _print_scoreboard(result: object) -> None:
    """Print a compact per-question, per-metric scoreboard from the result."""
    test_results = getattr(result, "test_results", [])
    print("\n" + "=" * 78)
    print("EVALUATION SCOREBOARD")
    print("=" * 78)
    for test_result in test_results:
        print(f"\n  {test_result.name}")
        for metric in test_result.metrics_data or []:
            score = "n/a" if metric.score is None else f"{metric.score:.2f}"
            mark = "PASS" if metric.success else "FAIL"
            reason = (metric.reason or "").splitlines()[0] if metric.reason else ""
            if len(reason) > 60:
                reason = reason[:60] + "…"
            print(f"    [{mark}] {metric.name:<22} score={score:<5} {reason}")


def main() -> None:
    """Ingest a known corpus, answer the goldens, and grade them with deepeval."""
    load_dotenv()
    _require_openai_key()

    settings = _build_settings()
    log.info("Using FalkorDB graph %r on %s", _GRAPH_NAME, settings.falkordb_host)
    rag = GraphRAG.with_defaults(settings=settings)
    rag.bootstrap_schema()

    log.info("Ingesting %d documents...", len(CORPUS))
    _ingest_corpus(rag)

    test_cases = _build_test_cases(rag)
    metrics = build_metrics()

    log.info("Scoring %d answers with deepeval...", len(test_cases))
    # evaluate() prints deepeval's own rich per-case table; the scoreboard below
    # is a compact recap of the same numbers for quick scanning.
    result = evaluate(test_cases, metrics)
    _print_scoreboard(result)

    print(
        "\nReading the scores: high faithfulness with low recall means the "
        "answer is honest but the graph under-retrieved; raise recall by "
        "improving the ontology or using mode='hybrid' (see examples 4 and 5)."
    )


if __name__ == "__main__":
    main()
