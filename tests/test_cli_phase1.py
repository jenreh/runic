import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runic.cli import app

runner = CliRunner()


def _make_env(tmp_path: Path) -> Path:
    """Scaffold a minimal runic directory with two revisions."""
    runic_dir = tmp_path / "runic"
    runic_dir.mkdir()
    versions = runic_dir / "versions"
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
            message = "initial schema"
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
            message = "add email index"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    (runic_dir / "env.py").write_text("# stub env")
    return runic_dir / "env.py"


# ------------------------------------------------------------------
# history
# ------------------------------------------------------------------


def _mock_ctx(current: str | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.current.return_value = current
    return ctx


def test_history_contains_both_revisions(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["history", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "aaaaaaaaaaaa" in result.output
    assert "bbbbbbbbbbbb" in result.output


def test_history_newest_first(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["history", "--config", str(env)])
    assert result.exit_code == 0
    pos_bb = result.output.index("bbbbbbbbbbbb")
    pos_aa = result.output.index("aaaaaaaaaaaa")
    assert pos_bb < pos_aa


def test_history_marks_applied_revision_as_head(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx("bbbbbbbbbbbb")),
    ):
        result = runner.invoke(app, ["history", "--config", str(env)])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    head_line = next(l for l in lines if "(head)" in l)
    assert "bbbbbbbbbbbb" in head_line


def test_history_no_head_marker_when_nothing_applied(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx(None)),
    ):
        result = runner.invoke(app, ["history", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "(head)" not in result.output


def test_history_range(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(
            app, ["history", "--config", str(env), "--range", ":bbbbbbbbbbbb"]
        )
    assert result.exit_code == 0, result.output
    assert "bbbbbbbbbbbb" in result.output
    assert "aaaaaaaaaaaa" in result.output


# ------------------------------------------------------------------
# heads
# ------------------------------------------------------------------


def test_heads_contains_head_revision_id(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["heads", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "bbbbbbbbbbbb" in result.output


def test_heads_single_head_suffix(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["heads", "--config", str(env)])
    assert "single head" in result.output


# ------------------------------------------------------------------
# show
# ------------------------------------------------------------------


def test_show_includes_required_fields(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["show", "bbbbbbbbbbbb", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "Revision ID:" in result.output
    assert "Revises:" in result.output
    assert "Message:" in result.output
    assert "bbbbbbbbbbbb" in result.output


def test_show_by_prefix(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["show", "bbbb", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "bbbbbbbbbbbb" in result.output


def test_show_unknown_revision_nonzero_exit(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["show", "zzzzzzzzzzz", "--config", str(env)])
    assert result.exit_code != 0 or "not found" in result.output.lower()


# ------------------------------------------------------------------
# stamp
# ------------------------------------------------------------------


def test_stamp_base_exits_zero(tmp_path: Path) -> None:
    env = _make_env(tmp_path)

    mock_ctx = MagicMock()

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["stamp", "base", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "Stamped" in result.output
    mock_ctx.stamp.assert_called_once_with("base", purge=False)


def test_stamp_calls_no_migration_functions(tmp_path: Path) -> None:
    env = _make_env(tmp_path)

    mock_ctx = MagicMock()

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        runner.invoke(app, ["stamp", "base", "--config", str(env)])

    mock_ctx.upgrade.assert_not_called()
    mock_ctx.downgrade.assert_not_called()


def test_history_verbose_shows_create_date(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["history", "--config", str(env), "--verbose"])
    assert result.exit_code == 0, result.output
    assert "create_date" in result.output


def test_history_verbose_shows_down_revision(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["history", "--config", str(env), "--verbose"])
    assert result.exit_code == 0, result.output
    assert "down_revision" in result.output


def test_branches_no_branches_outputs_nothing(tmp_path: Path) -> None:
    """Linear chain has no branch points — branches command outputs nothing."""
    env = _make_env(tmp_path)
    result = runner.invoke(app, ["branches", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == ""


def test_branches_shows_branch_point(tmp_path: Path) -> None:
    """When two revisions share the same down_revision, branches shows it."""
    runic_dir = tmp_path / "runic2"
    runic_dir.mkdir()
    versions = runic_dir / "versions"
    versions.mkdir()

    (versions / "aaaaaaaaaaaa_base.py").write_text(
        'revision = "aaaaaaaaaaaa"\ndown_revision = None\nbranch_labels = []\n'
        'depends_on = []\nirreversible = False\nsnapshot = False\nmessage = "base"\n'
        "from datetime import datetime\ncreate_date = datetime(2026, 1, 1)\n"
        "def upgrade(op): pass\ndef downgrade(op): pass\n"
    )
    (versions / "bbbbbbbbbbbb_b1.py").write_text(
        'revision = "bbbbbbbbbbbb"\ndown_revision = "aaaaaaaaaaaa"\nbranch_labels = []\n'
        'depends_on = []\nirreversible = False\nsnapshot = False\nmessage = "b1"\n'
        "from datetime import datetime\ncreate_date = datetime(2026, 1, 2)\n"
        "def upgrade(op): pass\ndef downgrade(op): pass\n"
    )
    (versions / "cccccccccccc_b2.py").write_text(
        'revision = "cccccccccccc"\ndown_revision = "aaaaaaaaaaaa"\nbranch_labels = []\n'
        'depends_on = []\nirreversible = False\nsnapshot = False\nmessage = "b2"\n'
        "from datetime import datetime\ncreate_date = datetime(2026, 1, 3)\n"
        "def upgrade(op): pass\ndef downgrade(op): pass\n"
    )
    (runic_dir / "env.py").write_text("# stub")

    env = runic_dir / "env.py"
    result = runner.invoke(app, ["branches", "--config", str(env)])
    assert result.exit_code == 0, result.output
    assert "aaaaaaaaaaaa" in result.output


def test_stamp_purge_flag(tmp_path: Path) -> None:
    env = _make_env(tmp_path)

    mock_ctx = MagicMock()

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(
            app, ["stamp", "aaaaaaaaaaaa", "--purge", "--config", str(env)]
        )

    assert result.exit_code == 0
    mock_ctx.stamp.assert_called_once_with("aaaaaaaaaaaa", purge=True)
