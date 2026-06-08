"""CLI tests: revision command, including --autogenerate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from runic.migrate.cli import app

from ._helpers import runner


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
