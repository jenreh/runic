from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()


def _stub_env(tmp_path: Path) -> Path:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    return env


def _mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.adapter = MagicMock()
    return ctx


def test_run_executes_py_script_without_recording(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    executed: list[str] = []

    script = tmp_path / "patch.py"
    script.write_text(
        textwrap.dedent("""\
            def upgrade(op):
                op.run_cypher("RETURN 1")
        """)
    )

    mock_ctx = _mock_ctx()
    # Capture what ops are called
    mock_ctx.adapter.run_query.side_effect = lambda q, p=None: executed.append(q)

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["run", str(script), "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "patch.py" in result.output
    # version node must NOT have been touched
    mock_ctx._version_node.set.assert_not_called()


def test_run_fails_for_missing_file(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    missing = tmp_path / "no_such.py"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["run", str(missing), "--config", str(env)])

    assert result.exit_code != 0
    assert "not found" in result.output


def test_run_fails_for_non_py_file(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    cypher = tmp_path / "patch.cypher"
    cypher.write_text("RETURN 1")

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["run", str(cypher), "--config", str(env)])

    assert result.exit_code != 0
    assert ".py" in result.output


def test_run_fails_when_no_upgrade_function(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    script = tmp_path / "bad.py"
    script.write_text("# no upgrade function\n")

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=_mock_ctx()),
    ):
        result = runner.invoke(app, ["run", str(script), "--config", str(env)])

    assert result.exit_code != 0
    assert "upgrade" in result.output
