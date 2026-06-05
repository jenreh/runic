import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.falkordb import FalkorDBAdapter
from runic.migrate.context import Runic
from runic.migrate.exceptions import MultipleHeadsError
from runic.migrate.script import RevisionNotFound


@pytest.fixture
def mock_graph() -> MagicMock:
    graph = MagicMock()
    graph.name = "test_graph"
    return graph


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def tmp_versions(tmp_path: Path) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir()

    for rev, down, msg, day in [
        ("aaaaaaaaaaaa", None, "first", 1),
        ("bbbbbbbbbbbb", "aaaaaaaaaaaa", "second", 2),
    ]:
        (versions / f"{rev}_{msg}.py").write_text(
            textwrap.dedent(f"""\
                revision = {rev!r}
                down_revision = {down!r}
                branch_labels = []
                depends_on = []
                irreversible = False
                snapshot = False
                message = {msg!r}
                from datetime import datetime
                create_date = datetime(2026, 1, {day})

                def upgrade(op):
                    pass

                def downgrade(op):
                    pass
            """)
        )
    return tmp_path


@pytest.fixture
def tmp_two_heads(tmp_path: Path) -> Path:
    """A → B and A → C (two heads)."""
    versions = tmp_path / "versions"
    versions.mkdir()

    for rev, down, msg, day in [
        ("aaaaaaaaaaaa", None, "base", 1),
        ("bbbbbbbbbbbb", "aaaaaaaaaaaa", "branch-b", 2),
        ("cccccccccccc", "aaaaaaaaaaaa", "branch-c", 3),
    ]:
        (versions / f"{rev}_{msg}.py").write_text(
            textwrap.dedent(f"""\
                revision = {rev!r}
                down_revision = {down!r}
                branch_labels = []
                depends_on = []
                irreversible = False
                snapshot = False
                message = {msg!r}
                from datetime import datetime
                create_date = datetime(2026, 1, {day})

                def upgrade(op):
                    pass

                def downgrade(op):
                    pass
            """)
        )
    return tmp_path


def _make_ctx(mock_graph: MagicMock, mock_db: MagicMock, path: Path) -> Runic:
    return Runic(FalkorDBAdapter(mock_db, mock_graph), path)


# ------------------------------------------------------------------
# stamp
# ------------------------------------------------------------------


def test_stamp_base_calls_clear_no_migration(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("base")

    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 1

    # Verify no upgrade/downgrade modules were invoked (no op calls beyond stamp).
    # The stamp should have called set_multiple([]) which sets revisions=[].
    params = mock_graph.query.call_args_list[-1][0][1]
    assert params["revisions"] == []


def test_stamp_heads_calls_set_multiple(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    ctx.stamp("heads")

    params = mock_graph.query.call_args[0][1]
    stamped = set(params["revisions"])
    assert stamped == {"bbbbbbbbbbbb", "cccccccccccc"}


def test_stamp_specific_revision(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("aaaaaaaaaaaa")

    params = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["aaaaaaaaaaaa"]


def test_stamp_unknown_revision_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    with pytest.raises(RevisionNotFound):
        ctx.stamp("zzzzzzzzzzzz")


def test_stamp_purge_clears_before_stamp(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("aaaaaaaaaaaa", purge=True)

    # Two query calls: clear() + set()
    stamp_calls = [
        c[0][0]
        for c in mock_graph.query.call_args_list
        if "_FalkorMigrateVersion" in c[0][0]
    ]
    assert len(stamp_calls) >= 2


# ------------------------------------------------------------------
# upgrade raises when multiple heads
# ------------------------------------------------------------------


def test_upgrade_raises_multiple_heads(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    with pytest.raises(MultipleHeadsError):
        ctx.upgrade("head")


def test_upgrade_explicit_target_succeeds_with_multiple_heads(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert stamp_calls
