from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from runic.cli import app

runner = CliRunner()


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


def test_revision_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app, ["revision", "-m", "add email index", "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    assert "Created revision" in result.output
    version_files = list((target / "versions").glob("*.py"))
    assert len(version_files) == 1
    content = version_files[0].read_text()
    assert "add email index" in content
    assert "down_revision = None" in content


def test_revision_links_to_head(tmp_path: Path) -> None:
    from runic.script import ScriptDirectory

    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result1 = runner.invoke(app, ["revision", "-m", "first", "--config", str(config)])
    assert result1.exit_code == 0
    result2 = runner.invoke(app, ["revision", "-m", "second", "--config", str(config)])
    assert result2.exit_code == 0

    sd = ScriptDirectory.load(target)
    assert len(sd._revisions) == 2
    head = sd.head()
    assert head is not None
    head_rev = sd.get_revision(head)
    assert head_rev.down_revision is not None


def test_upgrade_missing_config_exits(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["upgrade", "--config", str(tmp_path / "nonexistent" / "env.py")]
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _resolve_config — .runic marker file
# ---------------------------------------------------------------------------


def test_resolve_config_returns_existing_path(tmp_path: Path) -> None:
    from runic.cli import _resolve_config

    env = tmp_path / "runic" / "env.py"
    env.parent.mkdir(parents=True)
    env.write_text("# stub")
    assert _resolve_config(env) == env


def test_resolve_config_uses_marker_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runic.cli import _resolve_config

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
    from runic.cli import _resolve_config

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
    """runic info --mode LOCAL resolves via .runic when dir != runic/."""
    custom = tmp_path / "migrations"
    (custom / "versions").mkdir(parents=True)
    env = custom / "env.py"
    env.write_text("# stub")
    (tmp_path / ".runic").write_text(str(env) + "\n")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["info", "--mode", "LOCAL"])
    assert result.exit_code == 0, result.output
    assert "Local revisions" in result.output


# ---------------------------------------------------------------------------
# upgrade --preview
# ---------------------------------------------------------------------------


def _patched_ctx(preview_log: list[str] | None = None) -> MagicMock:
    mock_ctx = MagicMock()
    mock_ctx.preview_log = preview_log or []
    return mock_ctx


def test_upgrade_preview_with_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = _patched_ctx(["CYPHER: CREATE INDEX FOR (n:Person) ON (n.email)"])

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--preview", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "CYPHER" in result.output
    mock_ctx.enable_preview.assert_called_once()


def test_upgrade_preview_no_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = _patched_ctx([])

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--preview", "--config", str(env)])

    assert result.exit_code == 0
    assert "nothing to upgrade" in result.output


# ---------------------------------------------------------------------------
# downgrade --preview
# ---------------------------------------------------------------------------


def test_downgrade_preview_with_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = _patched_ctx(["DROP RANGE INDEX: DROP INDEX ON :Person(email)"])

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(
            app, ["downgrade", "base", "--preview", "--config", str(env)]
        )

    assert result.exit_code == 0, result.output
    assert "DROP" in result.output
    mock_ctx.enable_preview.assert_called_once()


def test_downgrade_preview_no_ops(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = _patched_ctx([])

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(
            app, ["downgrade", "base", "--preview", "--config", str(env)]
        )

    assert result.exit_code == 0
    assert "nothing to downgrade" in result.output


# ---------------------------------------------------------------------------
# current — with message
# ---------------------------------------------------------------------------


def test_current_shows_message_when_present(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.current.return_value = "aabbcc112233"
    mock_ctx.get_revision_message.return_value = "add email index"

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "aabbcc112233" in result.output
    assert "add email index" in result.output


def test_current_shows_none_when_no_revision(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.current.return_value = None

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "<none>" in result.output


def test_current_shows_only_id_when_no_message(tmp_path: Path) -> None:
    """When get_revision_message returns None, current shows id only (no dash)."""
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.current.return_value = "aabbcc112233"
    mock_ctx.get_revision_message.return_value = None

    with (
        patch("runic.cli._exec_env"),
        patch("runic.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "aabbcc112233" in result.output
    assert "—" not in result.output


def test_exec_env_executes_real_script(tmp_path: Path) -> None:
    """_exec_env runs the env.py and any side-effects take place."""
    from runic.cli import _exec_env

    sentinel = tmp_path / "ran.txt"
    env = tmp_path / "env.py"
    env.write_text(f"open({str(sentinel)!r}, 'w').close()\n")

    _exec_env(env)
    assert sentinel.exists()
