"""Unit tests for merge revision creation and topological upgrade path."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from runic.adapters.falkordb import FalkorDBAdapter
from runic.script import ScriptDirectory


def _write_rev(
    versions_dir: Path,
    rev: str,
    down_revision: str | tuple | None = None,
    message: str = "",
) -> None:
    dr = repr(down_revision)
    code = textwrap.dedent(f"""\
        revision = {rev!r}
        down_revision = {dr}
        branch_labels = []
        depends_on = []
        irreversible = False
        snapshot = False
        message = {message!r}
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            pass

        def downgrade(op):
            pass
    """)
    (versions_dir / f"{rev}_rev.py").write_text(code)


def _make_sd(tmp_path: Path) -> tuple[ScriptDirectory, Path]:
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    return ScriptDirectory.load(tmp_path), versions_dir


# ---------------------------------------------------------------------------
# create() with tuple down_revision
# ---------------------------------------------------------------------------


def test_create_merge_revision(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, "r1r1r1r1r1r1")
    _write_rev(vd, "r2r2r2r2r2r2")
    sd = ScriptDirectory.load(tmp_path)

    path = sd.create(
        "merge branches",
        ("r1r1r1r1r1r1", "r2r2r2r2r2r2"),
        tmp_path,
        rev_id="aabbccddee00",
    )
    content = path.read_text()
    assert "down_revision = ('r1r1r1r1r1r1', 'r2r2r2r2r2r2')" in content


# ---------------------------------------------------------------------------
# topological_upgrade_path — linear chain
# ---------------------------------------------------------------------------


def test_topological_path_linear(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, "aaaaaaaaaaaa")
    _write_rev(vd, "bbbbbbbbbbbb", "aaaaaaaaaaaa")
    _write_rev(vd, "cccccccccccc", "bbbbbbbbbbbb")
    sd = ScriptDirectory.load(tmp_path)

    topo = sd.topological_upgrade_path(None, "cccccccccccc")
    linear = sd.iterate_revisions(None, "cccccccccccc")

    assert [r.revision for r in topo] == [r.revision for r in linear]


# ---------------------------------------------------------------------------
# topological_upgrade_path — merge scenario
# ---------------------------------------------------------------------------

_A = "aaaaaaa00001"
_B = "bbbbbbb00002"
_C = "ccccccc00003"
_M = "mmmmmmm00004"


def test_topological_path_merge(tmp_path: Path) -> None:
    """A→B, A→C, M(down_revision=(B,C)). From [A], path should be [B,C,M] or [C,B,M]."""
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, _A)
    _write_rev(vd, _B, _A)
    _write_rev(vd, _C, _A)
    _write_rev(vd, _M, (_B, _C))
    sd = ScriptDirectory.load(tmp_path)

    result = sd.topological_upgrade_path([_A], _M)
    revs = [r.revision for r in result]

    assert _M == revs[-1], "merge revision must be last"
    assert set(revs) == {_B, _C, _M}


def test_topological_path_from_both_heads(tmp_path: Path) -> None:
    """DB is at [B, C]. Upgrading to M should return only [M]."""
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, _A)
    _write_rev(vd, _B, _A)
    _write_rev(vd, _C, _A)
    _write_rev(vd, _M, (_B, _C))
    sd = ScriptDirectory.load(tmp_path)

    result = sd.topological_upgrade_path([_B, _C], _M)
    assert [r.revision for r in result] == [_M]


def test_topological_path_already_at_target(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, _A)
    _write_rev(vd, _B, _A)
    sd = ScriptDirectory.load(tmp_path)

    result = sd.topological_upgrade_path([_A, _B], _B)
    assert result == []


def test_topological_path_from_none(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    _write_rev(vd, _A)
    _write_rev(vd, _B, _A)
    sd = ScriptDirectory.load(tmp_path)

    result = sd.topological_upgrade_path(None, _B)
    assert [r.revision for r in result] == [_A, _B]


# ---------------------------------------------------------------------------
# version node collapses after merge
# ---------------------------------------------------------------------------


def test_upgrade_context_merges_version_node(tmp_path: Path) -> None:
    """After applying merge revision M, VersionNode.get() should return [M]."""
    vd = tmp_path / "versions"
    vd.mkdir(parents=True)
    _write_rev(vd, _A)
    _write_rev(vd, _B, _A)
    _write_rev(vd, _C, _A)
    _write_rev(vd, _M, (_B, _C))

    from runic.context import Runic

    # Mock DB and graph
    graph = MagicMock()
    graph.name = "test_merge_graph"
    db = MagicMock()
    db.list_graphs.return_value = []

    # Version node: start at [B, C]
    get_result = MagicMock()
    get_result.result_set = [[[_B, _C], None]]
    graph.ro_query.return_value = get_result
    graph.query.return_value = MagicMock(result_set=[[0]])

    ctx = Runic(FalkorDBAdapter(db, graph), tmp_path)

    with patch.object(ctx._version_node, "set_multiple") as mock_set_multiple:  # noqa: SLF001
        ctx.upgrade(_M)

    # Last stamped value should collapse to [M]
    assert mock_set_multiple.called, "set_multiple should have been called"
    assert mock_set_multiple.call_args_list[-1].args[0] == [_M]


# ---------------------------------------------------------------------------
# create() with branch_labels and depends_on
# ---------------------------------------------------------------------------


def test_create_with_branch_labels(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    path = sd.create(
        "feature",
        None,
        tmp_path,
        branch_labels=["feature_x"],
        rev_id="ff00ff00ff00",
    )
    content = path.read_text()
    assert "branch_labels: list[str] = ['feature_x']" in content


def test_create_with_upgrade_downgrade_body(tmp_path: Path) -> None:
    sd, vd = _make_sd(tmp_path)
    path = sd.create(
        "add index",
        None,
        tmp_path,
        upgrade_body='    op.create_range_index("X", "y")',
        downgrade_body='    op.drop_range_index("X", "y")',
        rev_id="aabb00001122",
    )
    content = path.read_text()
    assert 'op.create_range_index("X", "y")' in content
    assert 'op.drop_range_index("X", "y")' in content
