"""Backend registry for multi-backend integration tests.

Reads ``RUNIC_TEST_BACKENDS`` (comma-separated, default ``falkordb``).
Each entry maps to a factory that produces a ready-to-use ``GraphDriver`` and
a teardown callable that drops the test graph.

FalkorDB is the only embedded backend (uses ``redislite.FalkorDB``). All
others connect to Docker Compose services via fixed local ports (or env-var
overrides).

Environment overrides
---------------------
``RUNIC_TEST_BACKENDS``        comma-separated backend names, e.g. ``falkordb,neo4j``
``RUNIC_NEO4J_URI``            default ``bolt://localhost:7687``
``RUNIC_MEMGRAPH_URI``         default ``bolt://localhost:7688``
``RUNIC_ARCADEDB_HOST``        default ``localhost``
``RUNIC_ARCADEDB_PORT``        default ``2424``
``RUNIC_AGE_HOST``             default ``localhost``
``RUNIC_AGE_PORT``             default ``5432``
"""

from __future__ import annotations

import base64
import contextlib
import os
import secrets
import urllib.request
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Shared FalkorDB server (session singleton)
#
# Call _set_shared_falkordb_server() once from a session-scoped conftest
# fixture so every test shares one embedded redislite process instead of
# creating a new one per test.  The per-test graph is still unique (via
# random_graph_name) and cleaned up by deleting the graph on teardown.
# ---------------------------------------------------------------------------

_SHARED_FALKORDB_SERVER: Any = None


def _set_shared_falkordb_server(server: Any) -> None:
    global _SHARED_FALKORDB_SERVER  # noqa: PLW0603
    _SHARED_FALKORDB_SERVER = server


# ---------------------------------------------------------------------------
# Enabled backend list
# ---------------------------------------------------------------------------


def enabled_backends() -> list[str]:
    raw = os.environ.get("RUNIC_TEST_BACKENDS", "falkordb")
    return [b.strip() for b in raw.split(",") if b.strip()]


# ---------------------------------------------------------------------------
# Per-backend driver factories
# ---------------------------------------------------------------------------


def _make_falkordb(graph_name: str) -> tuple[Any, Callable[[], None]]:
    try:
        from redislite import FalkorDB as _FalkorDB
    except ImportError:
        import pytest

        pytest.skip("falkordblite (redislite) not installed")

    if _SHARED_FALKORDB_SERVER is not None:
        db = _SHARED_FALKORDB_SERVER
        owns_server = False
    else:
        db = _FalkorDB(protocol=2)  # type: ignore[call-arg]
        owns_server = True

    g = db.select_graph(graph_name)

    from runic.orm.driver.falkordb import FalkorDBDriver

    driver = FalkorDBDriver(g, db)

    def cleanup() -> None:
        with contextlib.suppress(Exception):
            g.delete()
        if owns_server:
            with contextlib.suppress(Exception):
                db._cleanup()  # noqa: SLF001

    return driver, cleanup


def _make_neo4j(graph_name: str) -> tuple[Any, Callable[[], None]]:  # noqa: ARG001
    import pytest

    try:
        from neo4j import GraphDatabase
    except ImportError:
        pytest.skip("neo4j driver not installed")

    uri = os.environ.get("RUNIC_NEO4J_URI", "bolt://localhost:7687")
    host = uri.replace("bolt://", "").split(":")[0]
    port = int(uri.rsplit(":", 1)[-1])

    try:
        neo4j_driver = GraphDatabase.driver(uri, auth=None)
        neo4j_driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j not reachable at {uri}: {exc}")

    from runic.orm.driver.neo4j import create_neo4j_driver

    # Neo4j Community Edition only supports one database; use the default.
    # Per-test isolation is achieved by DETACH DELETE + index/constraint cleanup.
    driver = create_neo4j_driver(
        host=host,
        port=port,
        database="neo4j",
        username="",
        password="",
        encrypted=False,
    )

    def cleanup() -> None:
        with contextlib.suppress(Exception):
            neo4j_driver.execute_query("MATCH (n) DETACH DELETE n")
        with contextlib.suppress(Exception):
            neo4j_driver.close()

    return driver, cleanup


def _make_memgraph(graph_name: str) -> tuple[Any, Callable[[], None]]:
    import pytest

    uri = os.environ.get("RUNIC_MEMGRAPH_URI", "bolt://localhost:7688")
    host = uri.replace("bolt://", "").split(":")[0]
    port = int(uri.rsplit(":", 1)[-1])

    try:
        from runic.orm.driver.memgraph import create_memgraph_driver

        # Memgraph does not support arbitrary named databases in the same way
        # as Neo4j — use the default database ("") and rely on DETACH DELETE
        # for per-test isolation.
        driver = create_memgraph_driver(
            host=host, port=port, database="", username="", password=""
        )
        driver.execute("RETURN 1", {})
    except Exception as exc:
        pytest.skip(f"Memgraph not reachable at {uri}: {exc}")

    def cleanup() -> None:
        with contextlib.suppress(Exception):
            driver.execute("MATCH (n) DETACH DELETE n", {})

    return driver, cleanup


def _arcadedb_http_command(
    http_host: str, http_port: int, password: str, command: str
) -> None:
    """Send a server management command to the ArcadeDB HTTP API."""
    url = f"http://{http_host}:{http_port}/api/v1/server"
    credentials = base64.b64encode(f"root:{password}".encode()).decode()
    body = f'{{"command": "{command}"}}'.encode()
    req = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        resp.read()


def _make_arcadedb(graph_name: str) -> tuple[Any, Callable[[], None]]:
    import pytest

    host = os.environ.get("RUNIC_ARCADEDB_HOST", "localhost")
    bolt_port = int(os.environ.get("RUNIC_ARCADEDB_PORT", "2424"))
    http_port = int(os.environ.get("RUNIC_ARCADEDB_HTTP_PORT", "2480"))
    password = os.environ.get("RUNIC_ARCADEDB_PASSWORD", "playwithdata")

    try:
        _arcadedb_http_command(
            host, http_port, password, f"create database {graph_name}"
        )
    except Exception as exc:
        pytest.skip(f"ArcadeDB not reachable at {host}:{http_port}: {exc}")

    try:
        from runic.orm.driver.arcadedb import create_arcadedb_driver

        driver = create_arcadedb_driver(
            host=host,
            port=bolt_port,
            database=graph_name,
            username="root",
            password=password,
        )
        driver.execute("RETURN 1", {})
    except Exception as exc:
        with contextlib.suppress(Exception):
            _arcadedb_http_command(
                host, http_port, password, f"drop database {graph_name}"
            )
        pytest.skip(f"ArcadeDB Bolt not reachable at {host}:{bolt_port}: {exc}")

    def cleanup() -> None:
        with contextlib.suppress(Exception):
            driver.close()
        with contextlib.suppress(Exception):
            _arcadedb_http_command(
                host, http_port, password, f"drop database {graph_name}"
            )

    return driver, cleanup


def _make_age(graph_name: str) -> tuple[Any, Callable[[], None]]:
    import pytest

    host = os.environ.get("RUNIC_AGE_HOST", "localhost")
    port = int(os.environ.get("RUNIC_AGE_PORT", "5432"))
    password = os.environ.get("RUNIC_AGE_PASSWORD", "postgres")

    try:
        from runic.orm.driver.age import create_age_driver

        driver = create_age_driver(
            host=host,
            port=port,
            database="postgres",
            graph=graph_name,
            username="postgres",
            password=password,
        )
        driver.execute("MATCH (n) RETURN n LIMIT 1", {})
    except Exception as exc:
        pytest.skip(f"Apache AGE not reachable at {host}:{port}: {exc}")

    def cleanup() -> None:
        with contextlib.suppress(Exception):
            driver.execute("MATCH (n) DETACH DELETE n", {})

    return driver, cleanup


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_FACTORIES: dict[str, Any] = {
    "falkordb": _make_falkordb,
    "neo4j": _make_neo4j,
    "memgraph": _make_memgraph,
    "arcadedb": _make_arcadedb,
    "age": _make_age,
}


def make_driver(backend: str, graph_name: str) -> tuple[Any, Callable[[], None]]:
    """Return ``(driver, cleanup)`` for the given *backend* and *graph_name*."""
    factory = _FACTORIES.get(backend)
    if factory is None:
        raise ValueError(
            f"Unknown test backend {backend!r}. Supported: {sorted(_FACTORIES)}"
        )
    return factory(graph_name)


def random_graph_name(prefix: str = "test") -> str:
    return f"{prefix}_{secrets.token_hex(6)}"
