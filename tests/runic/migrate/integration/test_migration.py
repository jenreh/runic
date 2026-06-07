"""Integration tests for the migration engine.

Exercises the full upgrade/downgrade/round-trip lifecycle against live graph
backends. The FalkorDB-specific snapshot/baseline tests require falkordblite
(redislite). Multi-backend round-trip tests run against every configured backend
via the ``migrate_adapter`` fixture.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from runic.migrate.context import IrreversibleMigrationError, Runic

_integration = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    vd = tmp_path / "runic" / "versions"
    vd.mkdir(parents=True, exist_ok=True)
    return vd


def _make_ctx_falkordb(db: Any, graph: Any, tmp_path: Path) -> Runic:
    from runic.migrate.adapters.falkordb import FalkorDBAdapter

    script_location = tmp_path / "runic"
    return Runic(FalkorDBAdapter(db, graph), script_location)


def _entity_count_raw(graph: Any) -> int:
    res = graph.query(
        "MATCH (n) WHERE NOT n:_FalkorMigrateVersion RETURN count(n) AS c"
    )
    return int(res.result_set[0][0]) if res.result_set else 0


def _index_count(graph: Any) -> int:
    res = graph.query("CALL db.indexes() YIELD label RETURN count(label) AS c")
    return int(res.result_set[0][0]) if res.result_set else 0


_R1 = "aa11bb22cc33"
_R2 = "dd44ee55ff66"

# ---------------------------------------------------------------------------
# Multi-backend round-trip tests
# ---------------------------------------------------------------------------


@_integration
def test_migration_round_trip(migrate_adapter: Any, tmp_path: Path) -> None:
    """Upgrade → downgrade → re-upgrade produces consistent entity counts."""
    from runic.migrate.cli import _entity_count

    runic_dir = tmp_path / "runic"
    versions_dir = runic_dir / "versions"
    versions_dir.mkdir(parents=True)

    rev = "aabbcc112233"
    _write_rev(
        versions_dir,
        rev,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body='op.run_cypher("MATCH (n:Foo) DELETE n")',
    )

    ctx = Runic(migrate_adapter, runic_dir)

    ctx.upgrade(target=rev)
    nodes_a = _entity_count(migrate_adapter)
    assert nodes_a == 1

    ctx.downgrade(target="base")
    nodes_b = _entity_count(migrate_adapter)
    assert nodes_b == 0

    ctx.upgrade(target=rev)
    nodes_c = _entity_count(migrate_adapter)
    assert nodes_c == nodes_a


@_integration
def test_count_helpers(migrate_adapter: Any) -> None:
    """_entity_count returns 0 on an empty graph."""
    from runic.migrate.cli import _entity_count

    assert _entity_count(migrate_adapter) == 0


# ---------------------------------------------------------------------------
# FalkorDB-specific integration tests (snapshot, baseline, irreversible)
# ---------------------------------------------------------------------------


@_integration
def test_upgrade_downgrade_round_trip(falkordb_graph: Any, tmp_path: Path) -> None:
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
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

    ctx = _make_ctx_falkordb(db, graph, tmp_path)
    ctx.upgrade("head")
    assert _index_count(graph) == 1
    assert _entity_count_raw(graph) == 1

    ctx.downgrade("base")
    assert _index_count(graph) == 0
    assert _entity_count_raw(graph) == 0


@_integration
def test_idempotency(falkordb_graph: Any, tmp_path: Path) -> None:
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
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

    ctx = _make_ctx_falkordb(db, graph, tmp_path)
    ctx.upgrade("head")
    count_after_first = _entity_count_raw(graph)

    ctx.upgrade("head")
    count_after_second = _entity_count_raw(graph)

    assert count_after_first == count_after_second


@_integration
def test_snapshot_auto_restore_on_failure(falkordb_graph: Any, tmp_path: Path) -> None:
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)
    snap_name = f"{graph.name}__premig_{_R1}"

    _write_rev(
        vd,
        _R1,
        snapshot=True,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body="pass",
    )

    ctx = _make_ctx_falkordb(db, graph, tmp_path)

    original = ctx._script_dir.get_revision(_R1).module.upgrade  # noqa: SLF001

    def _failing_upgrade(op: Any) -> None:
        original(op)
        raise RuntimeError("intentional failure")

    ctx._script_dir.get_revision(_R1).module.upgrade = _failing_upgrade  # noqa: SLF001

    with pytest.raises(RuntimeError, match="intentional failure"):
        ctx.upgrade(_R1)

    assert _entity_count_raw(graph) == 0
    assert snap_name not in db.list_graphs()


@_integration
def test_snapshot_downgrade_uses_snapshot(
    falkordb_graph: Any, tmp_path: Path
) -> None:
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
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

    ctx = _make_ctx_falkordb(db, graph, tmp_path)
    ctx.upgrade(_R1)
    assert snap_name in db.list_graphs()
    assert _entity_count_raw(graph) == 1

    ctx.downgrade("base")

    assert snap_name not in db.list_graphs()
    assert _entity_count_raw(graph) == 0


@_integration
def test_baseline_round_trip(falkordb_graph: Any, tmp_path: Path) -> None:
    """Baseline-generated revision must run cleanly upgrade→downgrade on a fresh graph."""
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
    from runic.migrate.adapters.falkordb import FalkorDBAdapter

    db, graph = falkordb_graph
    script_location = tmp_path / "runic"
    script_location.mkdir(parents=True, exist_ok=True)

    source_adapter = FalkorDBAdapter(db, graph)
    source_adapter.create_range_index("Movie", "title")
    source_adapter.create_fulltext_index("Article", "body")

    ctx = Runic(source_adapter, script_location)
    generated_path = ctx.baseline("baseline")
    assert generated_path is not None
    assert generated_path.exists()
    assert ctx.current() is not None

    content = generated_path.read_text()
    assert "create_range_index" in content
    assert "create_fulltext_index" in content

    fresh_graph_name = f"{graph.name}__baseline_fresh"
    fresh_adapter = source_adapter.fork(fresh_graph_name)
    try:
        fresh_ctx = Runic(fresh_adapter, script_location)
        fresh_ctx.upgrade("head")
        assert _index_count(fresh_adapter._graph) >= 1  # noqa: SLF001
        fresh_ctx.downgrade("base")
        assert _index_count(fresh_adapter._graph) == 0
    finally:
        try:
            fresh_adapter.delete_graph()
        except Exception:
            pass


@_integration
def test_irreversible_raises(falkordb_graph: Any, tmp_path: Path) -> None:
    pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")
    db, graph = falkordb_graph
    vd = _versions_dir(tmp_path)

    _write_rev(
        vd,
        _R1,
        irreversible=True,
        upgrade_body='op.run_cypher("CREATE (n:Foo {x: 1})")',
        downgrade_body="pass",
    )

    ctx = _make_ctx_falkordb(db, graph, tmp_path)
    ctx.upgrade(_R1)

    with pytest.raises(IrreversibleMigrationError):
        ctx.downgrade("base")

    ctx.downgrade("base", force=True)
