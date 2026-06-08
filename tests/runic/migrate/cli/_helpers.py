"""Shared helpers for the per-command CLI tests."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()


def write_rev(versions_dir: Path, rev: str, down_revision: str | None = None) -> None:
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


def setup_two_branches(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a runic env with two branch heads; return (config_path, rev_a, rev_b)."""
    target = tmp_path / "runic"
    runner.invoke(app, ["init", str(target)])
    vd = target / "versions"
    rev_a = "aaa111aaa111"
    rev_b = "bbb222bbb222"
    write_rev(vd, rev_a)
    write_rev(vd, rev_b)
    return target / "env.py", rev_a, rev_b


def patched_ctx(preview_log: list[str] | None = None) -> MagicMock:
    mock_ctx = MagicMock()
    mock_ctx.preview_log = preview_log or []
    return mock_ctx


def mock_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.current.return_value = "abc123"
    ctx.get_revision_message.return_value = "some migration"
    ctx.preview_log = []
    return ctx
