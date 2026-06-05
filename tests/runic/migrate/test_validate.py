from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from runic.migrate.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Unit tests — runic.migrate.validate()
# ---------------------------------------------------------------------------


def _versions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "runic" / "versions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_rev(versions: Path, rev_id: str, parent: str | None, body: str = "") -> Path:
    content = textwrap.dedent(f"""\
        revision = {rev_id!r}
        down_revision = {parent!r}
        branch_labels = []
        depends_on = []
        irreversible = False
        snapshot = False
        message = "migration {rev_id}"
        from datetime import datetime
        create_date = datetime(2026, 1, 1)

        def upgrade(op):
            {body or "pass"}

        def downgrade(op):
            pass
    """)
    p = versions / f"{rev_id}_migration.py"
    p.write_text(content)
    return p


def _make_runic(tmp_path: Path, *, track_checksums: bool = True):
    """Create a Runic context. Call AFTER writing any revision files so ScriptDirectory loads them."""
    from runic.migrate.adapters.falkordb import FalkorDBAdapter
    from runic.migrate.context import Runic

    try:
        from redislite import FalkorDB

        db = FalkorDB(protocol=2)
    except ImportError:
        pytest.skip("falkordblite (redislite) not installed")

    import secrets

    graph = db.select_graph(f"test_{secrets.token_hex(4)}")
    adapter = FalkorDBAdapter(db, graph)
    _versions_dir(tmp_path)
    return Runic(adapter, tmp_path / "runic", track_checksums=track_checksums), adapter


def test_validate_returns_empty_when_no_migrations_applied(tmp_path: Path) -> None:
    ctx, _ = _make_runic(tmp_path)
    assert ctx.validate() == []


def test_validate_returns_empty_when_checksums_match(tmp_path: Path) -> None:
    versions = _versions_dir(tmp_path)
    _write_rev(versions, "aabbcc112233", None)
    ctx, _ = _make_runic(tmp_path)
    ctx.upgrade("aabbcc112233")
    assert ctx.validate() == []


def test_validate_detects_modified_script(tmp_path: Path) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    ctx, _ = _make_runic(tmp_path)
    ctx.upgrade("aabbcc112233")

    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")

    errors = ctx.validate()
    assert len(errors) == 1
    assert "aabbcc112233" in errors[0]
    assert "mismatch" in errors[0]


def test_validate_skips_revisions_without_stored_checksum(tmp_path: Path) -> None:
    """Pre-checksum deployments: stamp without recording checksum — must not error."""
    versions = _versions_dir(tmp_path)
    _write_rev(versions, "aabbcc112233", None)
    ctx, _ = _make_runic(tmp_path)

    ctx.stamp("aabbcc112233")
    assert ctx.validate() == []


def test_validate_disabled_when_track_checksums_false(tmp_path: Path) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    ctx, _ = _make_runic(tmp_path, track_checksums=False)
    ctx.upgrade("aabbcc112233")
    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")
    assert ctx.validate() == []


def test_validate_on_migrate_aborts_when_mismatch(tmp_path: Path) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    _write_rev(versions, "bbbbbbbbbbbb", "aabbcc112233")
    ctx, _ = _make_runic(tmp_path)
    ctx.upgrade("aabbcc112233")
    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")

    with pytest.raises(ValueError, match="Checksum validation failed"):
        ctx.upgrade("bbbbbbbbbbbb", validate_on_migrate=True)


# ---------------------------------------------------------------------------
# CLI tests — runic validate
# ---------------------------------------------------------------------------


def test_validate_cli_passes(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.validate.return_value = []

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["validate", "--config", str(env)])

    assert result.exit_code == 0
    assert "valid" in result.output


def test_validate_cli_fails_on_mismatch(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("# stub")
    mock_ctx = MagicMock()
    mock_ctx.validate.return_value = ["aabbcc112233: checksum mismatch"]

    with (
        patch("runic.migrate.cli._exec_env"),
        patch("runic.migrate.context.get", return_value=mock_ctx),
    ):
        result = runner.invoke(app, ["validate", "--config", str(env)])

    assert result.exit_code != 0
