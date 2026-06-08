"""DeepEval suite: does the runic-orm skill make Claude answer correctly?

Each golden is a real runic.orm question. The 'app' (runic_orm_app.run_ai_app)
answers it with the skill as context; two GEval metrics judge the answer for
correctness and API fidelity.

Run (from the repo root) with an environment that has deepeval installed:

    deepeval test run tests/evals/test_runic_orm_skill.py

This suite is intentionally NOT a project dependency — deepeval conflicts with
the repo's pinned deps on Python 3.14. See tests/evals/README.md for how to run
it in an isolated environment. Judging is key-free via the local `claude` CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the sibling helper modules importable regardless of pytest import mode.
sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from deepeval import assert_test  # noqa: E402
from deepeval.dataset import EvaluationDataset, Golden  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

import runic_orm_app  # noqa: E402
from metrics import SINGLE_TURN_NO_TRACING_METRICS  # noqa: E402

_DATASET_PATH = Path(__file__).parent / ".dataset.json"

dataset = EvaluationDataset()
dataset.add_goldens_from_json_file(file_path=str(_DATASET_PATH))


@pytest.mark.parametrize("golden", dataset.goldens)
def test_runic_orm_skill(golden: Golden) -> None:
    actual_output = runic_orm_app.run_ai_app(golden.input)
    test_case = LLMTestCase(
        input=golden.input,
        actual_output=actual_output,
        expected_output=getattr(golden, "expected_output", None),
    )
    assert_test(test_case=test_case, metrics=SINGLE_TURN_NO_TRACING_METRICS)
