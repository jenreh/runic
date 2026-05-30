from pathlib import Path

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
    assert "FalkorDB" in env_content
    assert "context.configure" in env_content
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
