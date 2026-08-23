"""Guards on the skill and eval assets that the default test run cannot reach.

``tests/evals`` is excluded from the suite (``--ignore=tests/evals`` in
``pyproject.toml``) because deepeval cannot be a project dependency on Python
3.14.  That exclusion means a broken path inside an eval harness fails only when
somebody runs the eval suite by hand — which is how ``runic_orm_app`` came to
point at a ``skill/runic/`` directory that does not exist, silently disabling
the OGM skill evaluation.

These tests import the harness modules (which pull in nothing beyond the
standard library) and assert every file they reference resolves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILLS = ["runic-ogm", "runic-migrate"]


@pytest.mark.parametrize("skill", _SKILLS)
def test_skill_directory_exists(skill: str) -> None:
    skill_md = _REPO_ROOT / "skill" / skill / "SKILL.md"
    assert skill_md.is_file(), f"missing skill entrypoint: {skill_md}"


def test_orm_eval_harness_paths_resolve() -> None:
    from tests.evals.runic_orm_app import _SKILL_PATH

    assert _SKILL_PATH.is_file(), (
        f"eval harness points at a missing file: {_SKILL_PATH}"
    )


def test_migrate_eval_harness_paths_resolve() -> None:
    from tests.evals.runic_migrate_app import (
        _ADVANCED_PATH,
        _OP_API_PATH,
        _SKILL_PATH,
    )

    for path in (_SKILL_PATH, _OP_API_PATH, _ADVANCED_PATH):
        assert path.is_file(), f"eval harness points at a missing file: {path}"


@pytest.mark.parametrize("dataset", [".dataset.json", ".migrate_dataset.json"])
def test_eval_datasets_exist(dataset: str) -> None:
    path = _REPO_ROOT / "tests" / "evals" / dataset
    assert path.is_file(), f"missing eval dataset: {path}"


def test_eval_golden_sets_share_their_prompts() -> None:
    """The two eval harnesses must ask the same questions.

    ``skill/runic-ogm/evals/evals.json`` (assertion-style, for skill-creator)
    and ``tests/evals/.dataset.json`` (DeepEval) are different formats serving
    different tools, but the prompts are a shared surface. They had already
    drifted once; this is what keeps them together.
    """
    import json

    skill = json.loads(
        (_REPO_ROOT / "skill" / "runic-ogm" / "evals" / "evals.json").read_text()
    )
    goldens = json.loads((_REPO_ROOT / "tests" / "evals" / ".dataset.json").read_text())

    assert skill["skill_name"] == "runic-ogm", "skill name must match its directory"

    skill_prompts = {e["prompt"] for e in skill["evals"]}
    golden_inputs = {g["input"] for g in goldens}
    orphans = sorted(skill_prompts - golden_inputs)
    assert not orphans, (
        f"skill evals ask questions the DeepEval set does not: {orphans}"
    )


def test_eval_ids_are_unique() -> None:
    import json

    skill = json.loads(
        (_REPO_ROOT / "skill" / "runic-ogm" / "evals" / "evals.json").read_text()
    )
    ids = [e["id"] for e in skill["evals"]]
    assert len(set(ids)) == len(ids)
