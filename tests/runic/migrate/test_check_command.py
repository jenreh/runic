"""Unit tests for the `runic check` CLI command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runic.migrate.autogen import DiffOp
from runic.migrate.cli import app
from runic.migrate.manifest import RangeIndex, SchemaManifest

runner = CliRunner()


def _make_ctx(manifest: SchemaManifest | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.target_manifest = manifest
    ctx.graph = MagicMock()
    return ctx


def test_check_exits_0_when_no_diff(tmp_path: Path) -> None:
    env_py = tmp_path / "env.py"
    env_py.write_text("")

    manifest = SchemaManifest(range_indexes=[RangeIndex("Person", "email")])
    ctx = _make_ctx(manifest)

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[]),
    ):
        result = runner.invoke(app, ["check", "--config", str(env_py)])

    assert result.exit_code == 0
    assert "up-to-date" in result.output


def test_check_exits_1_when_pending_ops(tmp_path: Path) -> None:
    env_py = tmp_path / "env.py"
    env_py.write_text("")

    manifest = SchemaManifest(range_indexes=[RangeIndex("Person", "email")])
    ctx = _make_ctx(manifest)

    pending_op = DiffOp(
        action="create",
        op_call='op.create_range_index("Person", "email")',
        inverse_call='op.drop_range_index("Person", "email")',
    )

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[pending_op]),
    ):
        result = runner.invoke(app, ["check", "--config", str(env_py)])

    assert result.exit_code == 1
    assert "create_range_index" in result.output


def test_check_exits_1_when_no_manifest(tmp_path: Path) -> None:
    env_py = tmp_path / "env.py"
    env_py.write_text("")

    ctx = _make_ctx(manifest=None)

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["check", "--config", str(env_py)])

    assert result.exit_code == 1
    assert "target_manifest" in result.output
