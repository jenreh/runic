"""Tests for runic.migrate.baseline() and the op-call renderer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.falkordb import FalkorDBAdapter
from runic.migrate.context import Runic
from runic.migrate.exceptions import GraphAlreadyManagedError
from runic.migrate.introspect import (
    ConstraintSpec,
    IndexSpec,
    OpCall,
    SchemaSnapshot,
    full_downgrade_ops,
    full_upgrade_ops,
)
from runic.migrate.script import ScriptDirectory, render_op_body

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
    mock_graph.query.return_value.result_set = []


def _managed_graph(mock_graph: MagicMock) -> None:
    def _query_side(q: str, params: dict | None = None) -> MagicMock:
        result = MagicMock()
        if "_FalkorMigrateVersion" in q:
            result.result_set = [["abc123abc123", None]]
        else:
            result.result_set = []
        return result

    mock_graph.query.side_effect = _query_side


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


# ---------------------------------------------------------------------------
# render_op_body — op-call rendering
# ---------------------------------------------------------------------------


def test_render_empty_ops_is_pass() -> None:
    assert render_op_body([]).strip() == "pass"


def test_render_range_index_node() -> None:
    ops = [OpCall("create_range_index", ("Person", "email"), {})]
    body = render_op_body(ops)
    assert "op.create_range_index('Person', 'email')" in body


def test_render_range_index_rel() -> None:
    ops = [OpCall("create_range_index", ("PURCHASED", "purchased_at"), {"rel": True})]
    body = render_op_body(ops)
    assert "rel=True" in body
    assert "create_range_index" in body


def test_render_fulltext_multi_prop() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Article", ["title", "body"], "FULLTEXT", "NODE")],
        constraints=[],
    )
    body = render_op_body(full_upgrade_ops(snapshot))
    assert "create_fulltext_index" in body
    assert "title" in body
    assert "body" in body


def test_render_vector_is_commented() -> None:
    snapshot = SchemaSnapshot(
        indexes=[
            IndexSpec(
                "Product",
                ["embedding"],
                "VECTOR",
                "NODE",
                options={"dimension": 128, "similarityFunction": "cosine"},
            )
        ],
        constraints=[],
    )
    body = render_op_body(full_upgrade_ops(snapshot))
    lines = [ln.strip() for ln in body.splitlines()]
    assert any(ln.startswith("#") and "create_vector_index" in ln for ln in lines)
    assert any("verify options manually" in ln for ln in lines)


def test_render_unique_constraint() -> None:
    ops = [OpCall("create_constraint", ("UNIQUE", "NODE", "Person", ["email"]), {})]
    body = render_op_body(ops)
    assert "create_constraint" in body
    assert "'UNIQUE'" in body
    assert "'Person'" in body


def test_render_section_comments_in_upgrade() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    body = render_op_body(full_upgrade_ops(snapshot))
    assert "# --- Indexes ---" in body
    assert "# --- Constraints ---" in body


def test_render_downgrade_order_constraints_before_indexes() -> None:
    """The rendered downgrade body must drop constraints before their backing indexes."""
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    body = render_op_body(full_downgrade_ops(snapshot))
    lines = body.splitlines()
    drop_constraint_idx = next(
        (i for i, ln in enumerate(lines) if "drop_constraint" in ln), None
    )
    drop_index_idx = next(
        (i for i, ln in enumerate(lines) if "drop_range_index" in ln), None
    )
    assert drop_constraint_idx is not None
    assert drop_index_idx is not None
    assert drop_constraint_idx < drop_index_idx, (
        "drop_constraint must precede drop_range_index in downgrade body"
    )


def test_render_down_revision_none_in_generated_file(tmp_path: Path) -> None:
    snapshot = SchemaSnapshot(indexes=[], constraints=[])
    sd = ScriptDirectory()
    path = sd.create(
        "baseline",
        None,
        tmp_path,
        upgrade_body=render_op_body(full_upgrade_ops(snapshot)),
        downgrade_body=render_op_body(full_downgrade_ops(snapshot)),
    )
    content = path.read_text()
    assert "down_revision = None" in content
