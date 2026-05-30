"""Tests for the `runic test` CLI command helpers and round-trip flow (Phase 3).

Uses falkordblite (embedded FalkorDB) to exercise the upgrade/downgrade/re-upgrade
logic that backs the CLI `runic test <rev>` command.
"""

from __future__ import annotations

import contextlib
import secrets
import textwrap
from pathlib import Path
from typing import Any

import pytest

from runic.cli import _constraint_count, _entity_count, _index_count

pytest.importorskip("redislite", reason="falkordblite (redislite) not installed")

from runic.adapters.falkordb import FalkorDBAdapter  # noqa: E402


def _write_rev(
    versions_dir: Path,
    rev: str,
    down_revision: str | None = None,
    *,
    upgrade_body: str = "pass",
    downgrade_body: str = "pass",
) -> None:
    dr = repr(down_revision)
    code = textwrap.dedent(f"""\
        revision = {rev!r}
        down_revision = {dr}
        branch_labels = []
        depends_on = []
        irreversible = False
        snapshot = False
        message = "rev {rev[:4]}"
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            {upgrade_body}

        def downgrade(op):
            {downgrade_body}
    """)
    (versions_dir / f"{rev}_rev.py").write_text(code)


@pytest.mark.integration
def test_migration_test_round_trip(falkordb_graph: Any, tmp_path: Path) -> None:
    """Upgrade → downgrade → re-upgrade produces consistent entity counts."""
    from runic.adapters.falkordb import FalkorDBAdapter
    from runic.context import Runic

    db, graph = falkordb_graph
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

    ephemeral_name = f"{graph.name}__test_{rev}_{secrets.token_hex(4)}"
    ephemeral_adapter = FalkorDBAdapter(db, db.select_graph(ephemeral_name))
    ctx = Runic(ephemeral_adapter, runic_dir)

    try:
        # Phase A — upgrade
        ctx.upgrade(target=rev)
        nodes_a = _entity_count(ephemeral_adapter)
        assert nodes_a == 1

        # Phase B — downgrade
        ctx.downgrade(target="base")
        nodes_b = _entity_count(ephemeral_adapter)
        assert nodes_b == 0

        # Phase C — idempotency re-upgrade
        ctx.upgrade(target=rev)
        nodes_c = _entity_count(ephemeral_adapter)
        assert nodes_c == nodes_a
    finally:
        with contextlib.suppress(Exception):
            ephemeral_adapter.delete_graph()


@pytest.mark.integration
def test_count_helpers(falkordb_graph: Any) -> None:
    """_entity_count, _index_count, _constraint_count return correct values."""
    db, graph = falkordb_graph
    adapter = FalkorDBAdapter(db, graph)

    assert _entity_count(adapter) == 0
    assert _index_count(adapter) == 0
    assert _constraint_count(adapter) == 0

    graph.query("CREATE (n:TestNode {x: 1})")
    assert _entity_count(adapter) == 1
