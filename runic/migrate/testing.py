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


@pytest.fixture(scope="session")
def falkordb_server() -> Any:
    """Yield a single session-scoped redislite.FalkorDB instance.

    Reusing a single server process dramatically speeds up both startup and shutdown times,
    since we avoid spawning and reaping a new redis-server subprocess for every test.
    """
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)  # type: ignore[call-arg]
    yield db
    with contextlib.suppress(Exception):
        db._cleanup()  # noqa: SLF001


@pytest.fixture
def falkordb_graph(falkordb_server: Any) -> Any:
    """Yield (db, graph) backed by the shared falkordb_server.

    Uses distinct graph names to guarantee isolation between tests.
    """
    db = falkordb_server
    graph_name = f"test_{secrets.token_hex(6)}"
    graph = db.select_graph(graph_name)
    yield db, graph
    with contextlib.suppress(Exception):
        graph.delete()


@pytest.fixture
def runic_context(falkordb_graph: Any, tmp_path: Path) -> Any:
    """Yield a configured Runic instance backed by an ephemeral falkordblite graph."""
    from runic.migrate.adapters.falkordb import FalkorDBAdapter
    from runic.migrate.context import configure, get

    db, graph = falkordb_graph
    script_location = tmp_path / "runic"
    (script_location / "versions").mkdir(parents=True, exist_ok=True)
    configure(FalkorDBAdapter(db, graph), script_location=script_location)
    return get()
