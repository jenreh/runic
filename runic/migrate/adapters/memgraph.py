"""Memgraph migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.memgraph import _MEMGRAPH_DIALECT, MemgraphDialect
from runic.orm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)


class MemgraphAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for Memgraph accessed via Bolt protocol.

    Named index convention (must match :class:`~runic.orm.driver.memgraph.MemgraphDialect`):

    - **Fulltext** (text search) index name = ``{label}`` (e.g. ``Post``)
    - **Vector** index name = ``{label}_{prop}`` (e.g. ``Article_embedding``)
    - **Range** indexes via ``CREATE INDEX ON :{label}({prop})`` — idempotent in Memgraph

    Requires the MAGE ``text_search`` and ``vector_search`` modules for
    fulltext and vector search respectively.
    """

    _backend_name = "Memgraph"

    def __init__(self, driver: BoltDriver, database: str) -> None:
        self._driver = driver
        self._database = database

    @classmethod
    def from_params(
        cls,
        database: str,
        *,
        host: str = "localhost",
        port: int = 7687,
        username: str = "",
        password: str = "",  # noqa: S107
        encrypted: bool = False,
        dialect: MemgraphDialect = _MEMGRAPH_DIALECT,
    ) -> MemgraphAdapter:
        driver = BoltDriver.from_params(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            dialect=dialect,
            encrypted=encrypted,
        )
        return cls(driver, database)

    @property
    def name(self) -> str:
        return self._database

    def run_query(self, query: str, params: dict | None = None) -> Any:
        return self._driver.execute(query, params or {})

    def run_ro_query(self, query: str) -> Any:
        return self._driver.execute(query, {})

    def fork(self, graph_name: str) -> MemgraphAdapter:
        """Return a new adapter targeting a different Memgraph database."""
        new_driver = BoltDriver(
            uri=self._driver.uri,
            auth=self._driver.auth,
            database=graph_name,
            dialect=_MEMGRAPH_DIALECT,
            encrypted=False,
        )
        return MemgraphAdapter(new_driver, graph_name)

    # ------------------------------------------------------------------
    # DDL — entity types (no-op: Memgraph is schemaless)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    # ------------------------------------------------------------------
    # DDL — indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        cypher = f"CREATE INDEX ON :{label}({prop})"
        log.info("Memgraph DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Memgraph create_range_index failed for %s.%s: %s", label, prop, exc
            )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        cypher = f"DROP INDEX ON :{label}({prop})"
        log.info("Memgraph DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Memgraph drop_range_index failed for %s.%s: %s", label, prop, exc
            )

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        # Memgraph TEXT INDEX is whole-label; index name = label (matches MemgraphDialect)
        cypher = f"CREATE TEXT INDEX {label} ON :{label}"
        log.info("Memgraph DDL: %s", cypher)
        if len(props) > 1:
            log.warning(
                "Memgraph text indexes cover the full label — "
                "multiple props %s on %s map to one whole-label index",
                props,
                label,
            )
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("Memgraph create_fulltext_index failed for %s: %s", label, exc)

    def drop_fulltext_index(self, label: str, *props: str) -> None:  # noqa: ARG002
        cypher = f"DROP TEXT INDEX {label}"
        log.info("Memgraph DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("Memgraph drop_fulltext_index failed for %s: %s", label, exc)

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,
        similarity: str,
        *,
        m: int = 16,
        ef_construction: int = 200,
        ef_runtime: int = 10,  # noqa: ARG002
    ) -> None:
        if dimension == 0:
            log.warning(
                "Memgraph create_vector_index: dimension=0 for %s.%s — "
                "pre-create the index with the correct dimension via Cypher DDL.",
                label,
                prop,
            )
            return
        cypher = (
            f"CREATE VECTOR INDEX {label}_{prop} ON :{label}({prop}) WITH CONFIG "
            f'{{"dimension": {dimension}, "capacity": 1000, "metric": "{similarity}", '
            f'"resize_coefficient": 2, "m": {m}, "ef_construction": {ef_construction}}}'
        )
        log.info("Memgraph DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Memgraph create_vector_index failed for %s.%s: %s", label, prop, exc
            )

    def drop_vector_index(self, label: str, prop: str) -> None:
        cypher = f"DROP VECTOR INDEX {label}_{prop}"
        log.info("Memgraph DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Memgraph drop_vector_index failed for %s.%s: %s", label, prop, exc
            )

    # ------------------------------------------------------------------
    # DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            prop = props[0]
            cypher = f"CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE"
            log.info("Memgraph DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "Memgraph create_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "Memgraph create_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            prop = props[0]
            cypher = f"DROP CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE"
            log.info("Memgraph DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "Memgraph drop_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "Memgraph drop_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()
