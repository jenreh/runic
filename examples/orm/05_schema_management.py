"""Example 5 — Schema management with IndexManager and SchemaManager.

Demonstrates:
  - Declaring RANGE, FULLTEXT, and UNIQUE indexes via Field descriptors
  - IndexManager.create_indexes() / ensure_indexes()
  - SchemaManager.validate_schema() — diff between declared vs actual
  - SchemaManager.sync_schema() — create missing indexes
  - SchemaManager.get_schema_diff() — human-readable diff
  - Using create_adapter() as the primary pattern (works for all backends)

Run against FalkorDB:
    uv run python examples/orm/05_schema_management.py

Run against Neo4j:
    RUNIC_BACKEND=neo4j NEO4J_PASSWORD=secret uv run python examples/orm/05_schema_management.py

Run against Memgraph:
    RUNIC_BACKEND=memgraph uv run python examples/orm/05_schema_management.py
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.migrate import IndexManager, SchemaManager  # noqa: E402
from runic.migrate.adapters import GraphAdapter, create_adapter  # noqa: E402
from runic.orm import Field, Node  # noqa: E402

# ---------------------------------------------------------------------------
# Models with index declarations
# ---------------------------------------------------------------------------


class Place(Node, labels=["Place"]):
    id: str
    name: str = Field(index_type="FULLTEXT")  # fulltext index
    slug: str = Field(unique=True)  # unique constraint
    latitude: float | None = Field(index=True, default=None)  # range index
    longitude: float | None = Field(index=True, default=None)  # range index
    category: str | None = Field(index=True, default=None)  # range index


class Event(Node, labels=["Event"]):
    id: str
    title: str = Field(index_type="FULLTEXT")
    start_date: str = Field(index=True)
    venue_id: str | None = Field(index=True, default=None)


# ---------------------------------------------------------------------------
# Adapter factory
# ---------------------------------------------------------------------------


def _make_adapter() -> GraphAdapter:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend == "falkordb":
        host = os.getenv("FALKORDB_HOST", "")
        if host:
            return create_adapter(
                "falkordb",
                host=host,
                port=int(os.getenv("FALKORDB_PORT", "6379")),
                graph_name="example_schema",
            )
        # Embedded fallback via redislite
        from falkordb import FalkorDB

        try:
            from redislite import FalkorDB as _RedisFalkorDB  # type: ignore[no-redef]

            _db = _RedisFalkorDB(protocol=2)
        except ImportError:
            _db = FalkorDB()
        from runic.migrate.adapters.falkordb import FalkorDBAdapter

        return FalkorDBAdapter(_db, _db.select_graph("example_schema"))
    if backend == "neo4j":
        return create_adapter(
            "neo4j",
            host=os.getenv("NEO4J_HOST", "localhost"),
            port=int(os.getenv("NEO4J_PORT", "7687")),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
            username=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", ""),
            encrypted=False,
        )
    if backend == "memgraph":
        return create_adapter(
            "memgraph",
            host=os.getenv("MEMGRAPH_HOST", "localhost"),
            port=int(os.getenv("MEMGRAPH_PORT", "7687")),
            database=os.getenv("MEMGRAPH_DATABASE", "memgraph"),
        )
    raise ValueError(f"Unsupported RUNIC_BACKEND={backend!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    adapter = _make_adapter()
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    log.info("Backend: %s", backend)

    # --- IndexManager: create indexes for individual classes ---
    log.info("=== IndexManager ===")
    manager = IndexManager(adapter)

    manager.create_indexes(Place, if_not_exists=True)
    log.info("Created Place indexes")

    manager.ensure_indexes(Event)
    log.info("Ensured Event indexes")

    # --- SchemaManager: validate ---
    log.info("=== SchemaManager — validate ===")
    schema = SchemaManager(adapter)

    result = schema.validate_schema([Place, Event])
    log.info("is_valid: %s", result.is_valid)
    if result.missing_indexes:
        log.info("Missing: %s", result.missing_indexes)
    if result.extra_indexes:
        log.info("Extra:   %s", result.extra_indexes)

    # --- SchemaManager: sync (create missing only) ---
    log.info("=== SchemaManager — sync ===")
    schema.sync_schema([Place, Event], drop_extra=False)

    result2 = schema.validate_schema([Place, Event])
    log.info("After sync — is_valid: %s", result2.is_valid)

    # --- SchemaManager: diff ---
    log.info("=== SchemaManager — diff ===")
    diff = schema.get_schema_diff([Place, Event])
    log.info("Schema diff:\n%s", diff)

    # --- SchemaManager: info ---
    log.info("=== SchemaManager — info ===")
    info = schema.get_schema_info([Place, Event])
    log.info("Schema info:\n%s", info)


if __name__ == "__main__":
    run()
