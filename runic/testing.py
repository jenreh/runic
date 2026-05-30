from __future__ import annotations

import contextlib
import secrets
from pathlib import Path
from typing import Any

import pytest

# falkordblite (PyPI) installs as the redislite module; the module name differs
# from the package name intentionally (it bundles an embedded Redis+FalkorDB).
try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False


@pytest.fixture
def falkordb_graph() -> Any:
    """Yield (db, graph) backed by falkordblite; tears down after the test.

    Requires falkordblite (installed as redislite) to be available.
    Uses protocol=2 to work around a redis-py 8.0 maintenance-notifications
    incompatibility with unix-socket connections used by the embedded server.
    """
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)  # type: ignore[call-arg]
    graph_name = f"test_{secrets.token_hex(6)}"
    graph = db.select_graph(graph_name)
    yield db, graph
    with contextlib.suppress(Exception):
        graph.delete()


@pytest.fixture
def runic_context(falkordb_graph: Any, tmp_path: Path) -> Any:
    """Yield a configured MigrationContext backed by an ephemeral falkordblite graph."""
    from runic.context import configure, get

    db, graph = falkordb_graph
    script_location = tmp_path / "runic"
    (script_location / "versions").mkdir(parents=True, exist_ok=True)
    configure(db, graph, script_location=script_location)
    return get()
