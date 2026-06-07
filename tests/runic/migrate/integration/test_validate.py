from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from runic.migrate.cli import app
from runic.migrate.context import Runic

runner = CliRunner()

_integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
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


def _make_runic(adapter: Any, tmp_path: Path, *, track_checksums: bool = True) -> Runic:
    _versions_dir(tmp_path)
    return Runic(adapter, tmp_path / "runic", track_checksums=track_checksums)


# ---------------------------------------------------------------------------
# validate() behaviour tests (live DB, multi-backend)
# ---------------------------------------------------------------------------


@_integration
def test_validate_returns_empty_when_no_migrations_applied(
    tmp_path: Path, migrate_adapter: Any
) -> None:
    ctx = _make_runic(migrate_adapter, tmp_path)
    assert ctx.validate() == []


@_integration
def test_validate_returns_empty_when_checksums_match(
    tmp_path: Path, migrate_adapter: Any
) -> None:
    versions = _versions_dir(tmp_path)
    _write_rev(versions, "aabbcc112233", None)
    ctx = _make_runic(migrate_adapter, tmp_path)
    ctx.upgrade("aabbcc112233")
    assert ctx.validate() == []


@_integration
def test_validate_detects_modified_script(tmp_path: Path, migrate_adapter: Any) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    ctx = _make_runic(migrate_adapter, tmp_path)
    ctx.upgrade("aabbcc112233")

    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")

    errors = ctx.validate()
    assert len(errors) == 1
    assert "aabbcc112233" in errors[0]
    assert "mismatch" in errors[0]


@_integration
def test_validate_skips_revisions_without_stored_checksum(
    tmp_path: Path, migrate_adapter: Any
) -> None:
    versions = _versions_dir(tmp_path)
    _write_rev(versions, "aabbcc112233", None)
    ctx = _make_runic(migrate_adapter, tmp_path)

    ctx.stamp("aabbcc112233")
    assert ctx.validate() == []


@_integration
def test_validate_disabled_when_track_checksums_false(
    tmp_path: Path, migrate_adapter: Any
) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    ctx = _make_runic(migrate_adapter, tmp_path, track_checksums=False)
    ctx.upgrade("aabbcc112233")
    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")
    assert ctx.validate() == []


@_integration
def test_validate_on_migrate_aborts_when_mismatch(
    tmp_path: Path, migrate_adapter: Any
) -> None:
    versions = _versions_dir(tmp_path)
    rev_path = _write_rev(versions, "aabbcc112233", None)
    _write_rev(versions, "bbbbbbbbbbbb", "aabbcc112233")
    ctx = _make_runic(migrate_adapter, tmp_path)
    ctx.upgrade("aabbcc112233")
    rev_path.write_text(rev_path.read_text() + "\n# tampered\n")

    with pytest.raises(ValueError, match="Checksum validation failed"):
        ctx.upgrade("bbbbbbbbbbbb", validate_on_migrate=True)


# ---------------------------------------------------------------------------
# CLI tests — runic validate (unit, no live DB)
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
