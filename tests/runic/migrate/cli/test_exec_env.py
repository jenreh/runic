"""CLI tests: _exec_env helper and env.py execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from runic.migrate.cli import app

from ._helpers import runner


def test_exec_env_executes_real_script(tmp_path: Path) -> None:
    from runic.migrate.cli import _exec_env

    sentinel = tmp_path / "ran.txt"
    env = tmp_path / "env.py"
    env.write_text(f"open({str(sentinel)!r}, 'w').close()\n")

    _exec_env(env)
    assert sentinel.exists()


def test_exec_env_injects_env_path_via_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import runic.migrate.context as ctx_module

    custom = tmp_path / "migrations"
    (custom / "versions").mkdir(parents=True)
    env = custom / "env.py"
    env.write_text(
        "from unittest.mock import MagicMock\n"
        "from runic.migrate import context\n"
        "context.configure(MagicMock())\n"
    )
    (tmp_path / ".runic").write_text(str(env) + "\n")
    monkeypatch.chdir(tmp_path)

    from runic.migrate.cli import _exec_env

    _exec_env(Path("runic/env.py"))

    assert ctx_module.get()._script_location == custom  # noqa: SLF001


def test_exec_env_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["upgrade", "--config", str(tmp_path / "nonexistent" / "env.py")],
    )
    assert result.exit_code != 0
