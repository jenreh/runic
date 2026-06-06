"""Example 5 — Schema management with IndexManager and SchemaManager.

Demonstrates:
  - Declaring RANGE, FULLTEXT, and UNIQUE indexes via Field descriptors
  - IndexManager.create_indexes() / ensure_indexes()
  - SchemaManager.validate_schema() — diff between declared vs actual
  - SchemaManager.sync_schema() — create missing indexes
  - SchemaManager.get_schema_diff() — human-readable diff

NOTE: IndexManager and SchemaManager are FalkorDB-specific.  This example
      requires a live FalkorDB server (embedded redislite does not support
      index introspection).

Run against FalkorDB (live server):
    FALKORDB_HOST=localhost FALKORDB_PORT=6379 uv run python examples/orm/05_schema_management.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from runic.orm import Field, IndexManager, Node, SchemaManager  # noqa: E402

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
# Connection helper
# ---------------------------------------------------------------------------


def _connect() -> Any:
    host = os.getenv("FALKORDB_HOST", "")
    if host:
        from falkordb import FalkorDB

        db = FalkorDB(host=host, port=int(os.getenv("FALKORDB_PORT", "6379")))
    else:
        from redislite import FalkorDB  # type: ignore[no-redef]

        db = FalkorDB(protocol=2)
    return db.select_graph("example_schema")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> None:
    backend = os.getenv("RUNIC_BACKEND", "falkordb")
    if backend != "falkordb":
        log.warning(
            "IndexManager and SchemaManager are FalkorDB-only. Skipping (RUNIC_BACKEND=%s).",
            backend,
        )
        return

    graph = _connect()

    # --- IndexManager: create indexes for individual classes ---
    log.info("=== IndexManager ===")
    manager = IndexManager(graph)

    manager.create_indexes(Place, if_not_exists=True)
    log.info("Created Place indexes")

    manager.ensure_indexes(Event)
    log.info("Ensured Event indexes")

    # --- SchemaManager: validate ---
    log.info("=== SchemaManager — validate ===")
    schema = SchemaManager(graph)

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
