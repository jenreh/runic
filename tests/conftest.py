import contextlib
import textwrap
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# Load test backend config from .env.test before any fixture params are resolved.
# Shell-set env vars are NOT overridden — they always take precedence.
load_dotenv(Path(__file__).parent.parent / ".env.test", override=False)

# Expose falkordblite-backed fixtures for all tests that need a live graph.
# Kept for backward-compatibility during transition; new tests use graph_driver.
from runic.migrate.testing import (  # noqa: E402, F401
    falkordb_graph,
    falkordb_server,
    runic_context,
)
from tests._backends import (  # noqa: E402
    _set_shared_falkordb_server,
    enabled_backends,
    make_driver,
    random_graph_name,
)


@pytest.fixture(scope="session", autouse=True)
def _register_shared_falkordb(request: pytest.FixtureRequest) -> None:
    """Wire the session-scoped embedded FalkorDB into _backends.

    Ensures all tests share one redislite process instead of starting a new
    one per test — critical for startup/shutdown performance.
    Only registers when falkordb is an active backend to avoid pulling in
    redislite on neo4j/memgraph-only runs.
    """
    if "falkordb" not in enabled_backends():
        return
    server = request.getfixturevalue("falkordb_server")
    _set_shared_falkordb_server(server)


@pytest.fixture(params=enabled_backends())
def graph_driver(request: pytest.FixtureRequest) -> Iterator[Any]:
    """Parametrized fixture yielding a ready GraphDriver for each enabled backend.

    Controlled by the ``RUNIC_TEST_BACKENDS`` env var (default: ``falkordb``).
    Backends that are unreachable are skipped automatically.
    Tests marked ``requires_multi_label`` are skipped for backends that only
    support single-label nodes (e.g. Apache AGE).
    """
    backend: str = request.param
    graph_name = random_graph_name(prefix=f"test_{backend}")
    driver, cleanup = make_driver(backend, graph_name)
    if request.node.get_closest_marker("requires_multi_label") and not getattr(
        driver, "supports_multi_label", True
    ):
        cleanup()
        pytest.skip(f"Backend {backend!r} does not support multi-label nodes")
    dialect = getattr(driver, "dialect", None)
    if request.node.get_closest_marker("requires_geo_update") and not getattr(
        dialect, "supports_geo_update", True
    ):
        cleanup()
        pytest.skip(
            f"Backend {backend!r} does not support SET n.prop = point() via Bolt"
        )
    yield driver
    cleanup()


@pytest.fixture(params=enabled_backends())
def migrate_context(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Any]:
    """Parametrized fixture yielding a configured RunicContext for each enabled backend."""

    from runic.migrate.context import configure, get

    backend: str = request.param
    graph_name = random_graph_name(prefix=f"migrate_{backend}")
    driver, cleanup = make_driver(backend, graph_name)

    if backend == "falkordb":
        from runic.migrate.adapters.falkordb import FalkorDBAdapter

        db_and_graph = _get_falkordb_db_and_graph(driver)
        if db_and_graph is None:
            pytest.skip("FalkorDB adapter requires (db, graph) tuple")
            return
        db, graph = db_and_graph
        adapter: Any = FalkorDBAdapter(db, graph)
    elif backend == "neo4j":
        from runic.migrate.adapters.neo4j import Neo4jAdapter

        adapter = Neo4jAdapter(driver, graph_name)
    elif backend == "memgraph":
        from runic.migrate.adapters.memgraph import MemgraphAdapter

        adapter = MemgraphAdapter(driver, graph_name)
    elif backend == "age":
        from runic.migrate.adapters.age import AGEAdapter

        adapter = AGEAdapter(driver, graph_name)
    else:
        pytest.skip(f"No migrate adapter for backend {backend!r}")
        return

    script_location = tmp_path / "runic"
    (script_location / "versions").mkdir(parents=True, exist_ok=True)
    configure(adapter, script_location=script_location)

    yield get()
    cleanup()


@pytest.fixture(params=enabled_backends())
def migrate_adapter(request: pytest.FixtureRequest) -> Iterator[Any]:
    """Parametrized fixture yielding a GraphAdapter for each enabled backend.

    Unlike ``migrate_context``, this fixture does NOT configure a Runic context.
    Use it in migrate tests that need to control the script location themselves
    (e.g. when writing migration scripts before loading the context).
    """
    backend: str = request.param
    graph_name = random_graph_name(prefix=f"madapter_{backend}")
    driver, cleanup = make_driver(backend, graph_name)

    if backend == "falkordb":
        from runic.migrate.adapters.falkordb import FalkorDBAdapter

        db_and_graph = _get_falkordb_db_and_graph(driver)
        if db_and_graph is None:
            pytest.skip("FalkorDB adapter requires (db, graph) tuple")
            return
        db, graph = db_and_graph
        adapter: Any = FalkorDBAdapter(db, graph)
    elif backend == "neo4j":
        from runic.migrate.adapters.neo4j import Neo4jAdapter

        adapter = Neo4jAdapter(driver, graph_name)
    elif backend == "memgraph":
        from runic.migrate.adapters.memgraph import MemgraphAdapter

        adapter = MemgraphAdapter(driver, graph_name)
    elif backend == "age":
        from runic.migrate.adapters.age import AGEAdapter

        adapter = AGEAdapter(driver, graph_name)
    else:
        pytest.skip(f"No migrate adapter for backend {backend!r}")
        return

    yield adapter
    cleanup()


def _get_falkordb_db_and_graph(driver: Any) -> tuple[Any, Any] | None:
    """Extract (db, graph) from a FalkorDB driver for the migrate adapter."""
    with contextlib.suppress(AttributeError):
        return driver._graph.connection, driver._graph  # type: ignore[attr-defined]  # noqa: SLF001
    return None


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
