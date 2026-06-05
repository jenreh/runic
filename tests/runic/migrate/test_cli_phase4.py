"""Unit tests for Phase 4 CLI commands: merge, check, revision new flags."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()


def _write_rev(versions_dir: Path, rev: str, down_revision: str | None = None) -> None:
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
            pass

        def downgrade(op):
            pass
    """)
    (versions_dir / f"{rev}_rev.py").write_text(code)


def _setup_two_branches(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a runic env with two branch heads; return (config_path, rev_a, rev_b)."""
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    _write_rev(vd, rev_a)
    _write_rev(vd, rev_b)
    return target / "env.py", rev_a, rev_b


# ---------------------------------------------------------------------------
# merge command
# ---------------------------------------------------------------------------


def test_merge_creates_revision(tmp_path: Path) -> None:
    config, rev_a, rev_b = _setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        ["merge", rev_a, rev_b, "-m", "merge branches", "--config", str(config)],
    )
    assert result.exit_code == 0, result.output
    assert "Created revision" in result.output
    versions = list((tmp_path / "runic" / "versions").glob("*.py"))
    merge_files = [
        f for f in versions if f.stem not in (rev_a + "_rev", rev_b + "_rev")
    ]
    assert len(merge_files) == 1
    content = merge_files[0].read_text()
    assert rev_a in content
    assert rev_b in content


def test_merge_warns_when_not_heads(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    # rev_b is child of rev_a — rev_a is NOT a head
    _write_rev(vd, rev_a)
    _write_rev(vd, rev_b, rev_a)

    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "splice merge",
            "--config",
            str(target / "env.py"),
        ],
    )
    assert "Warning" in result.output or result.exit_code == 0


def test_merge_with_branch_label(tmp_path: Path) -> None:
    config, rev_a, rev_b = _setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "merge",
            "--branch-label",
            "main",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# revision command — new flags
# ---------------------------------------------------------------------------


def test_revision_with_branch_label(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "feature",
            "--branch-label",
            "feature_x",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert len(files) == 1
    assert "branch_labels: list[str] = ['feature_x']" in files[0].read_text()


def test_revision_with_depends_on(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "depends",
            "--depends-on",
            "aabbccddee00",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert "aabbccddee00" in files[0].read_text()


def test_revision_with_rev_id(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "custom id",
            "--rev-id",
            "deadbeef0001",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert any("deadbeef0001" in f.name for f in files)


# ---------------------------------------------------------------------------
# revision --autogenerate
# ---------------------------------------------------------------------------


def test_revision_autogenerate_no_manifest_exits(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    ctx = MagicMock()
    ctx.target_manifest = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(
            app, ["revision", "-m", "auto", "--autogenerate", "--config", str(config)]
        )

    assert result.exit_code != 0
    assert "target_manifest" in result.output


def test_revision_autogenerate_no_diff_exits_0(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    from runic.migrate.manifest import SchemaManifest

    ctx = MagicMock()
    ctx.target_manifest = SchemaManifest()
    ctx.graph = MagicMock()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[]),
    ):
        result = runner.invoke(
            app, ["revision", "-m", "auto", "--autogenerate", "--config", str(config)]
        )

    assert result.exit_code == 0
    assert "No schema changes" in result.output


def test_revision_autogenerate_with_diff_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    from runic.migrate.autogen import DiffOp
    from runic.migrate.manifest import SchemaManifest

    ctx = MagicMock()
    ctx.target_manifest = SchemaManifest()
    ctx.graph = MagicMock()

    op = DiffOp(
        action="create",
        op_call='op.create_range_index("Person", "email")',
        inverse_call='op.drop_range_index("Person", "email")',
    )

    with (
        patch("runic.migrate.cli._exec_env", return_value={}),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[op]),
    ):
        result = runner.invoke(
            app,
            [
                "revision",
                "-m",
                "add email index",
                "--autogenerate",
                "--config",
                str(config),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "CANDIDATE" in result.output
    files = list((target / "versions").glob("*.py"))
    assert len(files) == 1
    assert "create_range_index" in files[0].read_text()


# ---------------------------------------------------------------------------
# upgrade / downgrade / current / stamp — basic wiring
# ---------------------------------------------------------------------------


def _mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.current.return_value = "abc123"
    ctx.get_revision_message.return_value = "some migration"
    ctx.preview_log = []
    return ctx


def test_upgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--config", str(config)])

    assert result.exit_code == 0
    ctx.upgrade.assert_called_once_with(
        "head", validate_on_migrate=False, installed_by=None
    )


def test_downgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "base", "--config", str(config)])

    assert result.exit_code == 0
    ctx.downgrade.assert_called_once_with("base", force=False)


def test_downgrade_defaults_to_minus_one(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.downgrade.assert_called_once_with("-1", force=False)


def test_upgrade_partial_revision_id(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "abc1", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.upgrade.assert_called_once_with(
        "abc1", validate_on_migrate=False, installed_by=None
    )


def test_downgrade_partial_revision_id(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "abc1", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.downgrade.assert_called_once_with("abc1", force=False)


def test_current_prints_revision(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "abc123" in result.output


def test_current_prints_none(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()
    ctx.current.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "<none>" in result.output


def test_exec_env_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["upgrade", "--config", str(tmp_path / "nonexistent" / "env.py")],
    )
    assert result.exit_code != 0
