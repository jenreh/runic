import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import runic.context as ctx_module
from runic.adapters.falkordb import FalkorDBAdapter
from runic.context import IrreversibleMigrationError, Runic


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


def _make_ctx(
    mock_graph: MagicMock,
    mock_db: MagicMock,
    tmp_versions: Path,
    preview: bool = False,
) -> Runic:
    return Runic(FalkorDBAdapter(mock_db, mock_graph), tmp_versions, preview=preview)


def test_current_returns_none_initially(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    assert ctx.current() is None


def test_upgrade_stamps_each_revision(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_upgrade_mid_failure_leaves_prior_stamped(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)

    call_count = 0

    def failing_upgrade(op: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("mid-migration failure")

    sd = ctx._script_dir
    sd.get_revision("aaaaaaaaaaaa").module.upgrade = failing_upgrade
    sd.get_revision("bbbbbbbbbbbb").module.upgrade = failing_upgrade

    with pytest.raises(RuntimeError, match="mid-migration failure"):
        ctx.upgrade("bbbbbbbbbbbb")

    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1


def test_downgrade_to_base_clears_version(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert stamp_calls


def test_downgrade_irreversible_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx._script_dir.get_revision("bbbbbbbbbbbb").irreversible = True
    with pytest.raises(IrreversibleMigrationError):
        ctx.downgrade("aaaaaaaaaaaa")


def test_downgrade_irreversible_with_force(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx._script_dir.get_revision("bbbbbbbbbbbb").irreversible = True
    ctx.downgrade("aaaaaaaaaaaa", force=True)


def test_downgrade_when_already_at_base(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")  # should be a no-op, no error


def test_upgrade_already_at_target(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 0


def test_module_configure_and_get(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    ctx_module._context = None
    ctx_module.configure(
        FalkorDBAdapter(mock_db, mock_graph),
        script_location=tmp_versions,
    )
    ctx = ctx_module.get()
    assert isinstance(ctx, Runic)


def test_module_get_raises_when_not_configured() -> None:
    ctx_module._context = None
    with pytest.raises(RuntimeError, match="not configured"):
        ctx_module.get()


def test_module_is_preview_false_when_not_configured() -> None:
    ctx_module._context = None
    assert ctx_module.is_preview() is False


def test_module_configure_with_env_path(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_path: Path
) -> None:
    ctx_module._context = None
    env_path = tmp_path / "runic" / "env.py"
    env_path.parent.mkdir()
    ctx_module.configure(
        FalkorDBAdapter(mock_db, mock_graph),
        _env_path=env_path,
    )
    ctx = ctx_module.get()
    assert ctx.script_location == tmp_path / "runic"


# ---------------------------------------------------------------------------
# +N / -N relative target tests
# ---------------------------------------------------------------------------


def test_upgrade_relative_plus1(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """upgrade('+1') from base should stop at first revision."""
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+1")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    # Only one revision should be stamped (aaaaaaaaaaaa)
    assert len(stamp_calls) == 1


def test_upgrade_relative_plus2_reaches_head(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """upgrade('+2') from base should stamp both revisions."""
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+2")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_upgrade_relative_plus_exceeds_chain_stops_at_head(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """upgrade('+99') when only 2 revisions available should reach head."""
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+99")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_downgrade_relative_minus1(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """downgrade('-1') from head should revert one step."""
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("-1")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    # One stamp: set to aaaaaaaaaaaa
    assert len(stamp_calls) == 1


def test_downgrade_relative_minus_exceeds_base(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """downgrade('-99') should reach base (clear version)."""
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("-99")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2  # stamp for each revision downgraded


def test_upgrade_relative_zero_is_noop(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """+0 resolves to current revision — no new revisions applied."""
    mock_graph.ro_query.return_value.result_set = [["aaaaaaaaaaaa"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("+0")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 0


def test_upgrade_relative_invalid_suffix_treated_as_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """+xyz is not a valid relative target — should be passed through and raise."""
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    from runic.script import RevisionNotFound

    with pytest.raises((RevisionNotFound, Exception)):
        ctx.upgrade("+xyz")


def test_downgrade_relative_zero_resolves_to_current(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """-0 resolves to the current revision — downgrading to where we already are."""
    mock_graph.ro_query.return_value.result_set = [["aaaaaaaaaaaa"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    # downgrade to itself is a no-op path (iterate_revisions returns empty)
    ctx.downgrade("-0")  # should not raise


def test_upgrade_relative_multiple_heads_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path, tmp_path: Path
) -> None:
    """+N with multiple heads raises MultipleHeadsError."""
    import textwrap

    from runic.exceptions import MultipleHeadsError

    # Add a second base-level revision (creates two heads)
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

    mock_graph.ro_query.return_value.result_set = []
    ctx = Runic(FalkorDBAdapter(mock_db, mock_graph), branched_dir)
    with pytest.raises(MultipleHeadsError):
        ctx.upgrade("+1")


def test_upgrade_partial_revision_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """upgrade() resolves a partial revision id prefix to the full id."""
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 2


def test_downgrade_partial_revision_id(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    """downgrade() resolves a partial revision id prefix to the full id."""
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("aaaa")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "v.revisions = $revisions" in q]
    assert len(stamp_calls) == 1
