import textwrap
from collections.abc import Generator
from pathlib import Path

import pytest

# Expose falkordblite-backed fixtures for all tests that need a live graph.
from runic.migrate.testing import falkordb_graph, runic_context  # noqa: F401


@pytest.fixture(autouse=True)
def _restore_runic_marker() -> Generator[None]:
    """Prevent test runs from contaminating the project-root .runic marker file."""
    marker = Path(".runic")
    original = marker.read_text() if marker.exists() else None
    yield  # type: ignore[misc]
    if original is None:
        marker.unlink(missing_ok=True)
    else:
        marker.write_text(original)


@pytest.fixture
def tmp_versions(tmp_path: Path) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir()

    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
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
            message = "second migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    return tmp_path
