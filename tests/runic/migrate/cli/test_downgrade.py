"""CLI tests: downgrade command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runic.migrate.cli import app

from ._helpers import mock_ctx, patched_ctx, runner


def test_downgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()

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
    ctx = mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.downgrade.assert_called_once_with("-1", force=False)


def test_downgrade_partial_revision_id(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "abc1", "--config", str(config)])

    assert result.exit_code == 0, result.output
    ctx.downgrade.assert_called_once_with("abc1", force=False)


def test_downgrade_preview_with_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = patched_ctx(["DROP RANGE INDEX: DROP INDEX ON :Person(email)"])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(
            app, ["downgrade", "base", "--preview", "--config", str(env)]
        )

    assert result.exit_code == 0, result.output
    assert "DROP" in result.output
    ctx.enable_preview.assert_called_once()


def test_downgrade_preview_no_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    ctx = patched_ctx([])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(
            app, ["downgrade", "base", "--preview", "--config", str(env)]
        )

    assert result.exit_code == 0
    assert "nothing to downgrade" in result.output


def test_downgrade_via_marker_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "migrations"
    (custom / "versions").mkdir(parents=True)
    env = custom / "env.py"
    env.write_text("# stub")
    (tmp_path / ".runic").write_text(str(env) + "\n")
    monkeypatch.chdir(tmp_path)

    ctx = MagicMock()
    ctx.preview_log = []

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["downgrade", "base"])

    assert result.exit_code == 0, result.output
    ctx.downgrade.assert_called_once_with("base", force=False)
