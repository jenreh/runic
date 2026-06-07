"""CLI command tests: init, revision, upgrade, downgrade, current, merge, exec-env."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _write_rev(versions_dir: Path, rev: str, down_revision: str | None = None) -> None:
    dr = repr(down_revision)
    code = textwrap.dedent(f"""\
        revision = {rev!r}
        down_revision = {dr}
        branch_labels = []
        depends_on = []
        irreversible = False
        snapshot = False
        message = "rev {rev[:4]}"
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            pass

        def downgrade(op):
            pass
    """)
    (versions_dir / f"{rev}_rev.py").write_text(code)


def _setup_two_branches(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a runic env with two branch heads; return (config_path, rev_a, rev_b)."""
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    _write_rev(vd, rev_a)
    _write_rev(vd, rev_b)
    return target / "env.py", rev_a, rev_b


def _patched_ctx(preview_log: list[str] | None = None) -> MagicMock:
    mock_ctx = MagicMock()
    mock_ctx.preview_log = preview_log or []
    return mock_ctx


def _mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.current.return_value = "abc123"
    ctx.get_revision_message.return_value = "some migration"
    ctx.preview_log = []
    return ctx


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# revision command
# ---------------------------------------------------------------------------


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
    from runic.migrate.script import ScriptDirectory

    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    runner.invoke(app, ["revision", "-m", "first", "--config", str(config)])
    runner.invoke(app, ["revision", "-m", "second", "--config", str(config)])

    sd = ScriptDirectory.load(target)
    assert len(sd._revisions) == 2  # noqa: SLF001
    head = sd.head()
    assert head is not None
    head_rev = sd.get_revision(head)
    assert head_rev.down_revision is not None


def test_revision_with_branch_label(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "feature",
            "--branch-label",
            "feature_x",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert len(files) == 1
    assert "branch_labels: list[str] = ['feature_x']" in files[0].read_text()


def test_revision_with_depends_on(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "depends",
            "--depends-on",
            "aabbccddee00",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert "aabbccddee00" in files[0].read_text()


def test_revision_with_rev_id(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"
    result = runner.invoke(
        app,
        [
            "revision",
            "-m",
            "custom id",
            "--rev-id",
            "deadbeef0001",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    files = list((target / "versions").glob("*.py"))
    assert any("deadbeef0001" in f.name for f in files)


# ---------------------------------------------------------------------------
# revision --autogenerate
# ---------------------------------------------------------------------------


def test_revision_autogenerate_no_manifest_exits(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    ctx = MagicMock()
    ctx.target_manifest = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(
            app, ["revision", "-m", "auto", "--autogenerate", "--config", str(config)]
        )

    assert result.exit_code != 0
    assert "target_manifest" in result.output


def test_revision_autogenerate_no_diff_exits_0(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    from runic.migrate.manifest import SchemaManifest

    ctx = MagicMock()
    ctx.target_manifest = SchemaManifest()
    ctx.graph = MagicMock()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[]),
    ):
        result = runner.invoke(
            app, ["revision", "-m", "auto", "--autogenerate", "--config", str(config)]
        )

    assert result.exit_code == 0
    assert "No schema changes" in result.output


def test_revision_autogenerate_with_diff_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    config = target / "env.py"

    from runic.migrate.autogen import DiffOp
    from runic.migrate.manifest import SchemaManifest

    ctx = MagicMock()
    ctx.target_manifest = SchemaManifest()
    ctx.graph = MagicMock()

    op = DiffOp(
        action="create",
        op_call='op.create_range_index("Person", "email")',
        inverse_call='op.drop_range_index("Person", "email")',
    )

    with (
        patch("runic.migrate.cli._exec_env", return_value={}),
        patch("runic.migrate.context.get", return_value=ctx),
        patch("runic.migrate.introspect.read_live_schema", return_value=MagicMock()),
        patch("runic.migrate.autogen.diff_schema", return_value=[op]),
    ):
        result = runner.invoke(
            app,
            [
                "revision",
                "-m",
                "add email index",
                "--autogenerate",
                "--config",
                str(config),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "CANDIDATE" in result.output
    files = list((target / "versions").glob("*.py"))
    assert len(files) == 1
    assert "create_range_index" in files[0].read_text()


# ---------------------------------------------------------------------------
# upgrade command
# ---------------------------------------------------------------------------


def test_upgrade_missing_config_exits(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["upgrade", "--config", str(tmp_path / "nonexistent" / "env.py")]
    )
    assert result.exit_code != 0


def test_upgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

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
    ctx = _mock_ctx()

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
    mock_ctx = _patched_ctx(["CYPHER: CREATE INDEX FOR (n:Person) ON (n.email)"])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
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
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["upgrade", "--preview", "--config", str(env)])

    assert result.exit_code == 0
    assert "nothing to upgrade" in result.output


# ---------------------------------------------------------------------------
# downgrade command
# ---------------------------------------------------------------------------


def test_downgrade_calls_context(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

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
    ctx = _mock_ctx()

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
    ctx = _mock_ctx()

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
    mock_ctx = _patched_ctx(["DROP RANGE INDEX: DROP INDEX ON :Person(email)"])

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
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
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
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


# ---------------------------------------------------------------------------
# current command
# ---------------------------------------------------------------------------


def test_current_shows_message_when_present(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.current.return_value = "aabbcc112233"
    mock_ctx.get_revision_message.return_value = "add email index"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
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
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "<none>" in result.output


def test_current_shows_only_id_when_no_message(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.current.return_value = "aabbcc112233"
    mock_ctx.get_revision_message.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(env)])

    assert result.exit_code == 0
    assert "aabbcc112233" in result.output
    assert "—" not in result.output


def test_current_prints_revision(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "abc123" in result.output


def test_current_prints_none(tmp_path: Path) -> None:
    config = tmp_path / "env.py"
    config.write_text("")
    ctx = _mock_ctx()
    ctx.current.return_value = None

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=ctx),
    ):
        result = runner.invoke(app, ["current", "--config", str(config)])

    assert "<none>" in result.output


# ---------------------------------------------------------------------------
# merge command
# ---------------------------------------------------------------------------


def test_merge_creates_revision(tmp_path: Path) -> None:
    config, rev_a, rev_b = _setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        ["merge", rev_a, rev_b, "-m", "merge branches", "--config", str(config)],
    )
    assert result.exit_code == 0, result.output
    assert "Created revision" in result.output
    versions = list((tmp_path / "runic" / "versions").glob("*.py"))
    merge_files = [
        f for f in versions if f.stem not in (rev_a + "_rev", rev_b + "_rev")
    ]
    assert len(merge_files) == 1
    content = merge_files[0].read_text()
    assert rev_a in content
    assert rev_b in content


def test_merge_warns_when_not_heads(tmp_path: Path) -> None:
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    _write_rev(vd, rev_a)
    _write_rev(vd, rev_b, rev_a)

    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "splice merge",
            "--config",
            str(target / "env.py"),
        ],
    )
    assert "Warning" in result.output or result.exit_code == 0


def test_merge_with_branch_label(tmp_path: Path) -> None:
    config, rev_a, rev_b = _setup_two_branches(tmp_path)
    result = runner.invoke(
        app,
        [
            "merge",
            rev_a,
            rev_b,
            "-m",
            "merge",
            "--branch-label",
            "main",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# exec-env
# ---------------------------------------------------------------------------


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
