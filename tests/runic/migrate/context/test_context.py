import logging
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import runic.migrate.context as ctx_module
from runic.migrate.adapters.falkordb import FalkorDBAdapter
from runic.migrate.context import IrreversibleMigrationError, Runic
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

    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    (versions / f"{rev2}_second.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev2!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "second"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

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


def _write_snapshot_revision(tmp_path: Path) -> Path:
    """A single revision that requests a pre-migration snapshot."""
    versions = tmp_path / "versions"
    versions.mkdir()
    rev = "aaaaaaaaaaaa"
    (versions / f"{rev}_snap.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = True
            message = "snap"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )
    return tmp_path


def _make_ctx(
    mock_graph: MagicMock,
    mock_db: MagicMock,
    path: Path,
    *,
    preview: bool = False,
) -> Runic:
    return Runic(FalkorDBAdapter(mock_db, mock_graph), path, preview=preview)


# ---------------------------------------------------------------------------
# Basic upgrade / downgrade / current
# ---------------------------------------------------------------------------


def test_current_returns_none_initially(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    assert ctx.current() is None


def test_upgrade_stamps_each_revision(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_upgrade_mid_failure_leaves_prior_stamped(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)

    call_count = 0

    def failing_upgrade(op: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("mid-migration failure")

    sd = ctx._script_dir  # noqa: SLF001
    sd.get_revision("aaaaaaaaaaaa").module.upgrade = failing_upgrade
    sd.get_revision("bbbbbbbbbbbb").module.upgrade = failing_upgrade

    with pytest.raises(RuntimeError, match="mid-migration failure"):
        ctx.upgrade("bbbbbbbbbbbb")

    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1


def test_upgrade_takes_snapshot_when_supported(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    mock_db.list_graphs.return_value = ["test_graph"]
    ctx = _make_ctx(mock_graph, mock_db, _write_snapshot_revision(tmp_path))
    ctx.upgrade("head")
    mock_graph.copy.assert_called_once()


def test_upgrade_skips_snapshot_when_unsupported(
    mock_graph: MagicMock,
    mock_db: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, _write_snapshot_revision(tmp_path))
    monkeypatch.setattr(ctx._adapter, "supports_snapshots", lambda: False)  # noqa: SLF001

    with caplog.at_level(logging.WARNING):
        ctx.upgrade("head")

    mock_graph.copy.assert_not_called()
    assert "does not support snapshots" in caplog.text


def test_downgrade_to_base_clears_version(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert stamp_calls


def test_downgrade_irreversible_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx._script_dir.get_revision("bbbbbbbbbbbb").irreversible = True  # noqa: SLF001
    with pytest.raises(IrreversibleMigrationError):
        ctx.downgrade("aaaaaaaaaaaa")


def test_downgrade_irreversible_with_force(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx._script_dir.get_revision("bbbbbbbbbbbb").irreversible = True  # noqa: SLF001
    ctx.downgrade("aaaaaaaaaaaa", force=True)


def test_downgrade_when_already_at_base(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")


def test_upgrade_already_at_target(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 0


# ---------------------------------------------------------------------------
# Module-level configure / get
# ---------------------------------------------------------------------------


def test_module_configure_and_get(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    ctx_module._context = None  # noqa: SLF001
    ctx_module.configure(
        FalkorDBAdapter(mock_db, mock_graph),
        script_location=tmp_versions,
    )
    ctx = ctx_module.get()
    assert isinstance(ctx, Runic)


def test_module_get_raises_when_not_configured() -> None:
    ctx_module._context = None  # noqa: SLF001
    with pytest.raises(RuntimeError, match="not configured"):
        ctx_module.get()


def test_module_is_preview_false_when_not_configured() -> None:
    ctx_module._context = None  # noqa: SLF001
    assert ctx_module.is_preview() is False


def test_module_configure_with_env_path(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    ctx_module._context = None  # noqa: SLF001
    env_path = tmp_path / "runic" / "env.py"
    env_path.parent.mkdir()
    ctx_module.configure(
        FalkorDBAdapter(mock_db, mock_graph),
        _env_path=env_path,
    )
    ctx = ctx_module.get()
    assert ctx.script_location == tmp_path / "runic"


# ---------------------------------------------------------------------------
# Relative target notation (+N / -N)
# ---------------------------------------------------------------------------


def test_upgrade_relative_plus1(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+1")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1


def test_upgrade_relative_plus2_reaches_head(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+2")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_upgrade_relative_plus_exceeds_chain_stops_at_head(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+99")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_downgrade_relative_minus1(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("-1")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1


def test_downgrade_relative_minus_exceeds_base(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("-99")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_upgrade_relative_zero_is_noop(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["aaaaaaaaaaaa"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+0")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 0


def test_upgrade_relative_invalid_suffix_treated_as_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    with pytest.raises(RevisionNotFound):
        ctx.upgrade("+xyz")


def test_downgrade_relative_zero_resolves_to_current(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["aaaaaaaaaaaa"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("-0")


def test_upgrade_relative_multiple_heads_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path, tmp_path: Path
) -> None:
    branched_dir = tmp_path / "branched"
    versions = branched_dir / "versions"
    versions.mkdir(parents=True)
    for rev, dr in [("aaaa11111111", None), ("bbbb22222222", None)]:
        (versions / f"{rev}_r.py").write_text(
            textwrap.dedent(f"""\
                revision = {rev!r}
                down_revision = {dr!r}
                branch_labels = []
                depends_on = []
                irreversible = False
                snapshot = False
                message = "r"
                from datetime import datetime
                create_date = datetime(2026, 1, 1)
                def upgrade(op): pass
                def downgrade(op): pass
            """)
        )

    mock_graph.query.return_value.result_set = []
    ctx = Runic(FalkorDBAdapter(mock_db, mock_graph), branched_dir)
    with pytest.raises(MultipleHeadsError):
        ctx.upgrade("+1")


def test_upgrade_partial_revision_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_downgrade_partial_revision_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("aaaa")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1


# ---------------------------------------------------------------------------
# Stamp operations
# ---------------------------------------------------------------------------


def test_stamp_base_calls_clear_no_migration(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("base")

    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 1

    params = mock_graph.query.call_args_list[-1][0][1]
    assert params["revisions"] == []


def test_stamp_heads_calls_set_multiple(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    ctx.stamp("heads")

    params = mock_graph.query.call_args[0][1]
    stamped = set(params["revisions"])
    assert stamped == {"bbbbbbbbbbbb", "cccccccccccc"}


def test_stamp_specific_revision(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("aaaaaaaaaaaa")

    params = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["aaaaaaaaaaaa"]


def test_stamp_unknown_revision_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    with pytest.raises(RevisionNotFound):
        ctx.stamp("zzzzzzzzzzzz")


def test_stamp_purge_clears_before_stamp(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.stamp("aaaaaaaaaaaa", purge=True)

    stamp_calls = [
        c[0][0]
        for c in mock_graph.query.call_args_list
        if "_FalkorMigrateVersion" in c[0][0]
    ]
    assert len(stamp_calls) >= 2


# ---------------------------------------------------------------------------
# Multiple-head guards
# ---------------------------------------------------------------------------


def test_upgrade_raises_multiple_heads(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    with pytest.raises(MultipleHeadsError):
        ctx.upgrade("head")


def test_upgrade_explicit_target_succeeds_with_multiple_heads(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_two_heads: Path
) -> None:
    mock_graph.query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_two_heads)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert stamp_calls
