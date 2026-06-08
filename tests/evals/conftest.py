"""Local conftest for the eval suite.

Overrides the parent tests/conftest.py autouse fixtures that require a live
FalkorDB (redislite) — evals run entirely via `claude -p` subprocess calls and
don't need any graph database.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _register_shared_falkordb() -> None:
    """No-op: evals don't need a live FalkorDB."""


@pytest.fixture(autouse=True)
def _restore_runic_marker():
    """No-op: evals don't create .runic marker files."""
    return
