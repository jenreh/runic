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


def _write_revisions(tmp_path: Path) -> Path:
    """Create two revision files under tmp_path/runic/versions/."""
    versions = tmp_path / "runic" / "versions"
    versions.mkdir(parents=True)

    rev1 = "aabbcc112233"
    rev2 = "ddeeff445566"
    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)
            def upgrade(op): pass
            def downgrade(op): pass
        """)
    )
    (versions / f"{rev2}_second.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev2!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "second"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)
            def upgrade(op): pass
            def downgrade(op): pass
        """)
    )
    return tmp_path / "runic" / "env.py"


def test_info_local_requires_no_db(tmp_path: Path) -> None:
    config = _write_revisions(tmp_path)
    config.write_text("# stub")

    # No _exec_env patching needed — LOCAL must not connect
    result = runner.invoke(app, ["info", "--mode", "LOCAL", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "Local revisions" in result.output
    assert "2" in result.output


def test_info_remote_shows_applied(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    mock_ctx = MagicMock()
    mock_ctx._version_node.get.return_value = ["aabbcc112233"]
    mock_ctx.get_revision_message.return_value = "first"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["info", "--mode", "REMOTE", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "aabbcc112233" in result.output


def test_info_remote_shows_none_when_no_revision(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)
    mock_ctx = MagicMock()
    mock_ctx._version_node.get.return_value = []

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["info", "--mode", "REMOTE", "--config", str(env)])

    assert result.exit_code == 0
    assert "<none>" in result.output


def test_info_compare_shows_pending_and_applied(tmp_path: Path) -> None:
    env = _stub_env(tmp_path)

    from datetime import UTC, datetime

    from runic.migrate.script import Revision, RevisionInfo

    rev1_info = RevisionInfo(
        revision="aabbcc112233",
        down_revision=None,
        message="first",
        create_date=datetime(2026, 1, 1, tzinfo=UTC),
        is_head=False,
        is_branch_point=False,
    )
    rev2_info = RevisionInfo(
        revision="ddeeff445566",
        down_revision="aabbcc112233",
        message="second",
        create_date=datetime(2026, 1, 2, tzinfo=UTC),
        is_head=True,
        is_branch_point=False,
    )

    rev2_rev = Revision(
        revision="ddeeff445566",
        down_revision="aabbcc112233",
        branch_labels=[],
        depends_on=[],
        irreversible=False,
        snapshot=False,
        message="second",
        create_date=datetime(2026, 1, 2, tzinfo=UTC),
        path=Path("dummy.py"),
        module=MagicMock(),
    )

    mock_ctx = MagicMock()
    mock_ctx._version_node.get.return_value = ["aabbcc112233"]
    mock_ctx.get_revision_message.return_value = "first"
    mock_ctx.get_history.return_value = [rev2_info, rev1_info]
    mock_ctx._script_dir.topological_upgrade_path.return_value = [rev2_rev]
    mock_ctx.adapter.name = "my_graph"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["info", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "Pending  : 1" in result.output
    assert "Applied  : 1 of 2" in result.output
    assert "my_graph" in result.output


def test_info_compare_warns_when_pending_undeterminable(tmp_path: Path) -> None:
    """A broken revision graph must surface a warning, not a clean status."""
    env = _stub_env(tmp_path)

    from runic.migrate.exceptions import MultipleHeadsError

    mock_ctx = MagicMock()
    mock_ctx._version_node.get.return_value = ["aabbcc112233"]
    mock_ctx.get_history.return_value = []
    mock_ctx._script_dir.topological_upgrade_path.side_effect = MultipleHeadsError(
        "multiple heads"
    )
    mock_ctx.adapter.name = "g"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["info", "--config", str(env)])

    assert result.exit_code == 0, result.output
    assert "cannot determine pending revisions" in result.output


def test_info_compare_default_mode(tmp_path: Path) -> None:
    """--mode defaults to COMPARE."""
    env = _stub_env(tmp_path)
    mock_ctx = MagicMock()
    mock_ctx._version_node.get.return_value = []
    mock_ctx.get_history.return_value = []
    mock_ctx._script_dir.topological_upgrade_path.return_value = []
    mock_ctx.adapter.name = "g"

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["info", "--config", str(env)])

    assert result.exit_code == 0
    assert "Database" in result.output
