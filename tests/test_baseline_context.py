"""Tests for Runic.baseline() — mocked graph, no live DB required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from runic.adapters.falkordb import FalkorDBAdapter
from runic.context import Runic
from runic.exceptions import GraphAlreadyManagedError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_graph() -> MagicMock:
    g = MagicMock()
    g.name = "test_graph"
    return g


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


def _unmanaged_graph(mock_graph: MagicMock) -> None:
    """Configure mock_graph so VersionNode.get() returns [] and introspection returns empty."""
    mock_graph.ro_query.return_value.result_set = []


def _managed_graph(mock_graph: MagicMock) -> None:
    """Configure mock_graph so VersionNode.get() returns a non-empty revision list."""

    def _ro_query_side(q: str) -> MagicMock:
        result = MagicMock()
        if "_FalkorMigrateVersion" in q:
            result.result_set = [["abc123abc123", None]]
        else:
            result.result_set = []
        return result

    mock_graph.ro_query.side_effect = _ro_query_side


def _make_ctx(mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path) -> Runic:
    return Runic(FalkorDBAdapter(mock_db, mock_graph), tmp_path)


# ---------------------------------------------------------------------------
# baseline() — file generation path
# ---------------------------------------------------------------------------


def test_baseline_unmanaged_graph_generates_file(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    path = ctx.baseline("baseline")
    assert path is not None
    assert path.exists()
    content = path.read_text()
    assert "down_revision = None" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_baseline_stamps_version_node(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    ctx.baseline("baseline")
    stamp_calls = [
        c for c in mock_graph.query.call_args_list if "_FalkorMigrateVersion" in str(c)
    ]
    assert stamp_calls, "expected at least one version-node stamp query"


def test_baseline_empty_graph_produces_pass_bodies(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    path = ctx.baseline("baseline")
    assert path is not None
    content = path.read_text()
    assert "pass" in content


def test_baseline_returns_file_path(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    path = ctx.baseline("baseline")
    assert path is not None
    assert path.suffix == ".py"
    assert "baseline" in path.name


# ---------------------------------------------------------------------------
# baseline() — already-managed guard
# ---------------------------------------------------------------------------


def test_baseline_already_managed_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _managed_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    with pytest.raises(GraphAlreadyManagedError, match="already managed"):
        ctx.baseline("baseline")


def test_baseline_already_managed_does_not_write_file(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _managed_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    versions_dir = tmp_path / "versions"
    with pytest.raises(GraphAlreadyManagedError):
        ctx.baseline("baseline")
    py_files = list(versions_dir.glob("*.py")) if versions_dir.exists() else []
    assert py_files == [], "no file should be written when guard triggers"


# ---------------------------------------------------------------------------
# baseline() — --stamp-only
# ---------------------------------------------------------------------------


def test_baseline_stamp_only_returns_none(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    result = ctx.baseline("baseline", stamp_only=True)
    assert result is None


def test_baseline_stamp_only_writes_no_file(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    ctx.baseline("baseline", stamp_only=True)
    versions_dir = tmp_path / "versions"
    py_files = list(versions_dir.glob("*.py")) if versions_dir.exists() else []
    assert py_files == []


def test_baseline_stamp_only_still_stamps(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _unmanaged_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    ctx.baseline("baseline", stamp_only=True)
    stamp_calls = [
        c for c in mock_graph.query.call_args_list if "_FalkorMigrateVersion" in str(c)
    ]
    assert stamp_calls, "stamp_only must still write the version node"


def test_baseline_stamp_only_already_managed_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    _managed_graph(mock_graph)
    ctx = _make_ctx(mock_graph, mock_db, tmp_path)
    with pytest.raises(GraphAlreadyManagedError):
        ctx.baseline("baseline", stamp_only=True)
