import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import runic.context as ctx_module
from runic.config import Config
from runic.context import IrreversibleMigrationError, MigrationContext


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


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
) -> MigrationContext:
    cfg = Config(script_location=tmp_versions)
    return MigrationContext(cfg, mock_db, mock_graph, preview=preview)


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
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
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
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 1


def test_downgrade_to_base_clears_version(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
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
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 0


def test_module_configure_and_get(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    ctx_module._context = None
    ctx_module.configure(
        connection=mock_db,
        graph=mock_graph,
        script_location=tmp_versions,
    )
    ctx = ctx_module.get()
    assert isinstance(ctx, MigrationContext)


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
        connection=mock_db,
        graph=mock_graph,
        _env_path=env_path,
    )
    ctx = ctx_module.get()
    assert ctx._config.script_location == tmp_path / "runic"
