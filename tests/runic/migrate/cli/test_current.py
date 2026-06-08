"""CLI tests: current command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from runic.migrate.cli import app

from ._helpers import mock_ctx, runner


def test_current_shows_message_when_present(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = MagicMock()
    ctx.current.return_value = "aabbcc112233"
    ctx.get_revision_message.return_value = "add email index"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "aabbcc112233" in result.output
    assert "add email index" in result.output


def test_current_shows_none_when_no_revision(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = MagicMock()
    ctx.current.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "<none>" in result.output


def test_current_shows_only_id_when_no_message(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = MagicMock()
    ctx.current.return_value = "aabbcc112233"
    ctx.get_revision_message.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "aabbcc112233" in result.output
    assert "—" not in result.output


def test_current_prints_revision(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "abc123" in result.output


def test_current_prints_none(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()
    ctx.current.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "<none>" in result.output
