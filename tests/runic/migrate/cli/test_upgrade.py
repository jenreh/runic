"""CLI tests: upgrade command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runic.migrate.cli import app

from ._helpers import mock_ctx, patched_ctx, runner


def test_upgrade_missing_config_exits(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["upgrade", "--config", str(tmp_path / "nonexistent" / "env.py")]
    )
    assert result.exit_code != 0


def test_upgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--config", str(config)])

    assert result.exit_code == 0
    ctx.upgrade.assert_called_once_with(
        "head", validate_on_migrate=False, installed_by=None
    )


def test_upgrade_partial_revision_id(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "abc1", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.upgrade.assert_called_once_with(
        "abc1", validate_on_migrate=False, installed_by=None
    )


def test_upgrade_preview_with_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = patched_ctx(["CYPHER: CREATE INDEX FOR (n:Person) ON (n.email)"])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--preview", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "CYPHER" in result.output
    ctx.enable_preview.assert_called_once()


def test_upgrade_preview_no_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = patched_ctx([])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--preview", "--config", str(env)])

    assert result.exit_code == 0
    assert "nothing to upgrade" in result.output
