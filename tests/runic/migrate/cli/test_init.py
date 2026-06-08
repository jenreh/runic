"""CLI tests: init command and .runic config-marker resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from runic.migrate.cli import app

from ._helpers import runner


def test_init_creates_files(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "env.py").exists()
    assert (target / "script.py.mako").exists()
    assert (target / "versions").is_dir()
    assert (target / "versions" / ".gitkeep").exists()


def test_init_fails_if_exists_without_force(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    target.mkdir()
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_init_with_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    target.mkdir()
    result = runner.invoke(app, ["init", "--force", str(target)])
    assert result.exit_code == 0
    assert (target / "env.py").exists()


def test_init_env_py_content(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    env_content = (target / "env.py").read_text()
    assert "create_adapter" in env_content
    assert '"falkordb"' in env_content
    assert "context.configure(" in env_content
    assert "FALKORDB_URL" in env_content


# ---------------------------------------------------------------------------
# _resolve_config — .runic marker file
# ---------------------------------------------------------------------------


def test_resolve_config_returns_existing_path(tmp_path: Path) -> None:
    from runic.migrate.cli import _resolve_config

    env = tmp_path / "runic" / "env.py"
    env.parent.mkdir(parents=True)
    env.write_text("# stub")
    assert _resolve_config(env) == env


def test_resolve_config_uses_marker_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runic.migrate.cli import _resolve_config

    custom = tmp_path / "migrations"
    custom.mkdir()
    env = custom / "env.py"
    env.write_text("# stub")
    (tmp_path / ".runic").write_text(str(env) + "\n")

    monkeypatch.chdir(tmp_path)
    assert _resolve_config(Path("runic/env.py")) == env


def test_resolve_config_no_marker_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runic.migrate.cli import _resolve_config

    monkeypatch.chdir(tmp_path)
    original = Path("runic/env.py")
    assert _resolve_config(original) == original


def test_init_writes_marker_for_custom_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "migrations"])
    assert result.exit_code == 0, result.output
    marker = tmp_path / ".runic"
    assert marker.exists()
    assert "migrations/env.py" in marker.read_text()


def test_init_no_marker_for_default_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "runic"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".runic").exists()


def test_info_local_uses_marker_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "migrations"
    (custom / "versions").mkdir(parents=True)
    env = custom / "env.py"
    env.write_text("# stub")
    (tmp_path / ".runic").write_text(str(env) + "\n")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["info", "--mode", "LOCAL"])
    assert result.exit_code == 0, result.output
    assert "Local revisions" in result.output
