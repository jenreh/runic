"""Unit tests for Phase-3 snapshot wiring in MigrationContext."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from runic.config import Config
from runic.context import MigrationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph(name: str = "social") -> MagicMock:
    # Use graph = MagicMock(); graph.name = name rather than MagicMock(name=name)
    # because `name` is a special Mock constructor param (sets repr only, not attribute).
    graph = MagicMock()
    graph.name = name
    return graph


def _make_db() -> MagicMock:
    db = MagicMock()
    db.list_graphs.return_value = []
    return db


def _make_ctx(
    tmp_path: Path,
    *,
    graph: MagicMock | None = None,
    db: MagicMock | None = None,
    versions: dict[str, str] | None = None,
) -> MigrationContext:
    if graph is None:
        graph = _make_graph()
    if db is None:
        db = _make_db()

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)

    if versions:
        for filename, content in versions.items():
            (versions_dir / filename).write_text(textwrap.dedent(content))

    graph.ro_query.return_value.result_set = []
    cfg = Config(script_location=tmp_path)
    return MigrationContext(cfg, db, graph)


_REV_A = "aaaaaaaaaaaa"


def _write_revision(
    versions_dir: Path,
    rev: str,
    down_revision: str | None = None,
    snapshot: bool = False,
    upgrade_body: str = "pass",
    downgrade_body: str = "pass",
) -> None:
    dr = repr(down_revision)
    content = textwrap.dedent(f"""\
        revision = {rev!r}
        down_revision = {dr}
        branch_labels = []
        depends_on = []
        irreversible = False
        snapshot = {snapshot!r}
        message = "rev {rev[:4]}"
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            {upgrade_body}

        def downgrade(op):
            {downgrade_body}
    """)
    (versions_dir / f"{rev}_rev.py").write_text(content)


# ---------------------------------------------------------------------------
# Test: snapshot called before upgrade when flag is set
# ---------------------------------------------------------------------------


def test_upgrade_calls_snapshot_when_flag_set(tmp_path: Path) -> None:
    graph = _make_graph("social")
    db = _make_db()
    db.list_graphs.return_value = ["social"]
    graph.ro_query.return_value.result_set = []

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_revision(versions_dir, _REV_A, snapshot=True)

    cfg = Config(script_location=tmp_path)
    ctx = MigrationContext(cfg, db, graph)

    ctx.upgrade(_REV_A)

    # snapshot() calls graph.copy with the premig name
    snap_name = f"social__premig_{_REV_A}"
    graph.copy.assert_called_once_with(snap_name)


def test_upgrade_no_snapshot_when_flag_false(tmp_path: Path) -> None:
    graph = _make_graph("social")
    db = _make_db()
    graph.ro_query.return_value.result_set = []

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_revision(versions_dir, _REV_A, snapshot=False)

    cfg = Config(script_location=tmp_path)
    ctx = MigrationContext(cfg, db, graph)

    ctx.upgrade(_REV_A)

    graph.copy.assert_not_called()


def test_upgrade_restores_snapshot_on_failure(tmp_path: Path) -> None:
    graph = _make_graph("social")
    db = _make_db()
    db.list_graphs.return_value = ["social"]
    graph.ro_query.return_value.result_set = []

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_revision(versions_dir, _REV_A, snapshot=True)

    cfg = Config(script_location=tmp_path)
    ctx = MigrationContext(cfg, db, graph)

    # Make upgrade() raise
    ctx._script_dir.get_revision(_REV_A).module.upgrade = lambda op: (
        _ for _ in ()
    ).throw(  # noqa: E731
        RuntimeError("boom")
    )

    with pytest.raises(RuntimeError, match="boom"):
        ctx.upgrade(_REV_A)

    snap_name = f"social__premig_{_REV_A}"
    # snapshot: graph.copy(snap_name)
    graph.copy.assert_called_once_with(snap_name)
    # restore: graph.delete() then snap_graph.copy("social") then snap_graph.delete()
    graph.delete.assert_called_once()
    snap_graph = db.select_graph(snap_name)
    snap_graph.copy.assert_called_once_with("social")
    snap_graph.delete.assert_called()


# ---------------------------------------------------------------------------
# Test: downgrade uses snapshot when snapshot graph exists
# ---------------------------------------------------------------------------


def test_downgrade_uses_snapshot_when_exists(tmp_path: Path) -> None:
    graph = _make_graph("social")
    db = _make_db()
    snap_name = f"social__premig_{_REV_A}"
    db.list_graphs.return_value = [snap_name]
    graph.ro_query.return_value.result_set = [[_REV_A]]

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_revision(versions_dir, _REV_A, snapshot=True)

    cfg = Config(script_location=tmp_path)
    ctx = MigrationContext(cfg, db, graph)

    # Track whether module.downgrade was called
    downgrade_called = []
    ctx._script_dir.get_revision(_REV_A).module.downgrade = lambda op: (
        downgrade_called.append(True)
    )  # noqa: E731

    ctx.downgrade("base")

    # restore_snapshot should have been used instead of downgrade()
    assert not downgrade_called, (
        "downgrade() should not have been called when snapshot exists"
    )
    snap_graph = db.select_graph(snap_name)
    snap_graph.copy.assert_called_once_with("social")
    snap_graph.delete.assert_called()


def test_downgrade_fallback_when_no_snapshot(tmp_path: Path) -> None:
    graph = _make_graph("social")
    db = _make_db()
    db.list_graphs.return_value = []  # no snapshot graphs
    graph.ro_query.return_value.result_set = [[_REV_A]]

    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_revision(versions_dir, _REV_A, snapshot=True)

    cfg = Config(script_location=tmp_path)
    ctx = MigrationContext(cfg, db, graph)

    downgrade_called = []
    ctx._script_dir.get_revision(_REV_A).module.downgrade = lambda op: (
        downgrade_called.append(True)
    )  # noqa: E731

    ctx.downgrade("base")

    assert downgrade_called, "downgrade() should be called when no snapshot exists"
    graph.delete.assert_not_called()
