"""CLI tests for `runic baseline`."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(tmp_path: Path) -> Path:
    """Scaffold a minimal runic directory with a mock-backed env.py."""
    runic_dir = tmp_path / "runic"
    runic_dir.mkdir()
    (runic_dir / "versions").mkdir()
    (runic_dir / "env.py").write_text(
        textwrap.dedent(f"""\
            from unittest.mock import MagicMock
            from runic.migrate.adapters.falkordb import FalkorDBAdapter
            from runic.migrate.context import configure

            mock_db = MagicMock()
            mock_graph = MagicMock()
            mock_graph.name = "test_graph"
            mock_graph.ro_query.return_value.result_set = []

            configure(
                FalkorDBAdapter(mock_db, mock_graph),
                script_location="{runic_dir}",
            )
        """)
    )
    return runic_dir / "env.py"


def _mock_ctx(file_path: Path | None = None, rev_id: str = "abc123abc123") -> MagicMock:
    ctx = MagicMock()
    ctx.baseline.return_value = file_path
    ctx.current.return_value = rev_id
    return ctx


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_baseline_exits_0_and_prints_path_and_rev(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    fake_path = tmp_path / "runic" / "versions" / "abc123abc123_baseline.py"
    fake_path.touch()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=_mock_ctx(fake_path)),
    ):
        result = runner.invoke(
            app, ["baseline", "-m", "baseline", "--config", str(env)]
        )

    assert result.exit_code == 0, result.output
    assert "Generated:" in result.output
    assert "Stamped:" in result.output


def test_baseline_stamp_only_prints_stamp_only(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    ctx = _mock_ctx(file_path=None, rev_id="deadbeef1234")

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["baseline", "--stamp-only", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "Stamped:" in result.output
    assert "Generated:" not in result.output


# ---------------------------------------------------------------------------
# Already-managed guard
# ---------------------------------------------------------------------------


def test_baseline_already_managed_exits_nonzero(tmp_path: Path) -> None:
    from runic.exceptions import GraphAlreadyManagedError

    env = _make_env(tmp_path)
    ctx = MagicMock()
    ctx.baseline.side_effect = GraphAlreadyManagedError(
        "Graph already managed by runic.migrate. Use `runic upgrade` instead."
    )

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["baseline", "-m", "again", "--config", str(env)])

    assert result.exit_code != 0
    assert (
        "already managed" in result.output.lower()
        or "already managed"
        in (result.stderr if hasattr(result, "stderr") else "").lower()
    )


def test_baseline_already_managed_prints_error_message(tmp_path: Path) -> None:
    from runic.exceptions import GraphAlreadyManagedError

    env = _make_env(tmp_path)
    ctx = MagicMock()
    ctx.baseline.side_effect = GraphAlreadyManagedError(
        "Graph already managed by runic.migrate. Use `runic upgrade` instead."
    )

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["baseline", "--config", str(env)])

    combined = result.output + (result.stderr if hasattr(result, "stderr") else "")
    assert "Error:" in combined or "already managed" in combined.lower()
