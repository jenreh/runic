"""DeepEval metrics for the runic-ogm skill evaluation.

Two LLM-judged GEval metrics, scored by the key-free ``ClaudeCLIModel``:

- ``Correctness``  — does the answer match the expected runic.ogm solution?
- ``APIFidelity``  — does it use the real runic.ogm API (no SQLAlchemy/Django
  idioms or invented methods)?

To use the standard hosted API instead, set ``ANTHROPIC_API_KEY`` and replace
``_JUDGE`` with ``deepeval.models.AnthropicModel("claude-sonnet-4-6")``.
"""

from __future__ import annotations

from claude_cli_model import ClaudeCLIModel
from deepeval.metrics import BaseMetric, GEval
from deepeval.test_case import LLMTestCaseParams

_JUDGE = ClaudeCLIModel()

_PARAMS = [
    LLMTestCaseParams.INPUT,
    LLMTestCaseParams.ACTUAL_OUTPUT,
    LLMTestCaseParams.EXPECTED_OUTPUT,
]

correctness = GEval(
    name="Correctness",
    criteria=(
        "Judge whether the 'actual output' is a correct, working answer to the "
        "runic.ogm question in 'input', using 'expected output' as the reference "
        "solution. Reward answers that define models with the right Node/Edge "
        "declarations, use the correct Field/Relation options, and run the right "
        "session/query-builder calls. Minor stylistic differences from the "
        "reference are fine; missing or wrong API usage is not."
    ),
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

api_fidelity = GEval(
    name="APIFidelity",
    evaluation_steps=[
        "Check whether the 'actual output' uses the genuine runic.ogm API as "
        "shown in 'expected output' (Node/Edge with labels=/type=, Field(), "
        "Relation(relationship=, direction=, target=, edge_model=), select()/"
        "session.query(), .where(), session.relate(), get(..., fetch=), etc.).",
        "Penalize SQLAlchemy/Django idioms that do not exist in runic.ogm: "
        ".filter(), .label(), field.desc(), Column, declarative_base, "
        "sessionmaker, objects.filter, query(Model).all().",
        "Penalize invented runic.ogm methods or arguments (e.g. session.run(), "
        "prefetch=, target_model=, .between(), wrong driver import paths).",
        "A high score means the answer would import and run against runic.ogm; a "
        "low score means it would fail because the API does not exist.",
    ],
    evaluation_params=_PARAMS,
    model=_JUDGE,
    threshold=0.7,
)

# Imported by the eval test file.
SINGLE_TURN_NO_TRACING_METRICS: list[BaseMetric] = [correctness, api_fidelity]
