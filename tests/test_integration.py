"""Integration tests for runic using falkordblite (embedded FalkorDB).

Guarded by pytest.importorskip so the suite skips cleanly when the package
is not installed (e.g. in CI without falkordblite).

Run exclusively:
    uv run pytest tests/test_integration.py -v -m integration
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")

from runic.config import Config  # noqa: E402
from runic.context import IrreversibleMigrationError, MigrationContext  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity_count(graph: Any) -> int:
    res = graph.query(
        "MATCH (n) WHERE NOT n:_FalkorMigrateVersion RETURN count(n) AS c"
    )
    return int(res.result_set[0][0]) if res.result_set else 0


def _index_count(graph: Any) -> int:
    res = graph.query("CALL db.indexes() YIELD label RETURN count(label) AS c")
    return int(res.result_set[0][0]) if res.result_set else 0


def _write_rev(
    versions_dir: Path,
    rev: str,
    down_revision: str | None = None,
    *,
    snapshot: bool = False,
    irreversible: bool = False,
    upgrade_body: str = "pass",
    downgrade_body: str = "pass",
) -> None:
    dr = repr(down_revision)
    code = textwrap.dedent(f"""\
        revision = {rev!r}
        down_revision = {dr}
        branch_labels = []
        depends_on = []
        irreversible = {irreversible!r}
        snapshot = {snapshot!r}
        message = "rev {rev[:4]}"
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            {upgrade_body}

        def downgrade(op):
            {downgrade_body}
    """)
    (versions_dir / f"{rev}_rev.py").write_text(code)


def _versions_dir(tmp_path: Path) -> Path:
    """Create and return the versions directory."""
    vd = tmp_path / "runic" / "versions"
    vd.mkdir(parents=True, exist_ok=True)
    return vd


def _make_ctx(db: Any, graph: Any, tmp_path: Path) -> MigrationContext:
    """Create a MigrationContext; call AFTER writing migration scripts."""
    script_location = tmp_path / "runic"
    return MigrationContext(Config(script_location=script_location), db, graph)


_R1 = "aa11bb22cc33"
_R2 = "dd44ee55ff66"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_upgrade_downgrade_round_trip(falkordb_graph: Any, tmp_path: Path) -> None:
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)

    _write_rev(
        vd,
        _R1,
        upgrade_body="op.create_range_index('Person', 'email')",
        downgrade_body="op.drop_range_index('Person', 'email')",
    )
    _write_rev(
        vd,
        _R2,
        down_revision=_R1,
        upgrade_body="op.run_cypher(\"CREATE (n:Person {name: 'Alice'})\")",
        downgrade_body='op.run_cypher("MATCH (n:Person) DELETE n")',
    )

    ctx = _make_ctx(db, graph, tmp_path)
    ctx.upgrade("head")
    assert _index_count(graph) == 1
    assert _entity_count(graph) == 1

    ctx.downgrade("base")
    assert _index_count(graph) == 0
    assert _entity_count(graph) == 0


@pytest.mark.integration
def test_idempotency(falkordb_graph: Any, tmp_path: Path) -> None:
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)

    _write_rev(
        vd,
        _R1,
        upgrade_body=(
            "op.run_cypher("
            "\"MERGE (n:Counter {id: 'x'}) SET n.count = coalesce(n.count, 0) + 1\""
            ")"
        ),
        downgrade_body='op.run_cypher("MATCH (n:Counter) DELETE n")',
    )

    ctx = _make_ctx(db, graph, tmp_path)
    ctx.upgrade("head")
    count_after_first = _entity_count(graph)

    # Second upgrade on the same context — already at head, should be no-op
    ctx.upgrade("head")
    count_after_second = _entity_count(graph)

    assert count_after_first == count_after_second


@pytest.mark.integration
def test_snapshot_auto_restore_on_failure(falkordb_graph: Any, tmp_path: Path) -> None:
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)
    snap_name = f"{graph.name}__premig_{_R1}"

    # Write a revision whose upgrade creates a node (successful step)
    _write_rev(
        vd,
        _R1,
        snapshot=True,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body="pass",
    )

    ctx = _make_ctx(db, graph, tmp_path)

    # Patch upgrade to call the real cypher then raise
    original = ctx._script_dir.get_revision(_R1).module.upgrade

    def _failing_upgrade(op: Any) -> None:
        original(op)
        raise RuntimeError("intentional failure")

    ctx._script_dir.get_revision(_R1).module.upgrade = _failing_upgrade

    with pytest.raises(RuntimeError, match="intentional failure"):
        ctx.upgrade(_R1)

    # Snapshot should have been restored → 0 nodes
    assert _entity_count(graph) == 0

    # Snapshot graph should be cleaned up after restore
    assert snap_name not in db.list_graphs()


@pytest.mark.integration
def test_snapshot_downgrade_uses_snapshot(falkordb_graph: Any, tmp_path: Path) -> None:
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)
    snap_name = f"{graph.name}__premig_{_R1}"

    _write_rev(
        vd,
        _R1,
        snapshot=True,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body='op.run_cypher("MATCH (n:Foo) DELETE n")',
    )

    ctx = _make_ctx(db, graph, tmp_path)
    ctx.upgrade(_R1)
    assert snap_name in db.list_graphs()
    assert _entity_count(graph) == 1

    ctx.downgrade("base")

    # Snapshot used as fast path → snapshot graph deleted after restore
    assert snap_name not in db.list_graphs()
    assert _entity_count(graph) == 0


@pytest.mark.integration
def test_irreversible_raises(falkordb_graph: Any, tmp_path: Path) -> None:
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)

    _write_rev(
        vd,
        _R1,
        irreversible=True,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body="pass",
    )

    ctx = _make_ctx(db, graph, tmp_path)
    ctx.upgrade(_R1)

    with pytest.raises(IrreversibleMigrationError):
        ctx.downgrade("base")

    # force=True should proceed without error
    ctx.downgrade("base", force=True)
