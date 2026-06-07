"""Neo4j migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.neo4j import _NEO4J_DIALECT, Neo4jDialect
from runic.orm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)


class Neo4jAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for Neo4j 5.x accessed via Bolt protocol.

    Named index convention (must match :class:`~runic.orm.driver.neo4j.Neo4jDialect`):

    - **Fulltext** index name = ``{label}`` (e.g. ``Post``)
    - **Vector** index name = ``{label}_{prop}`` (e.g. ``Article_embedding``)
    - **Range** index name = ``{label}_{prop}`` (e.g. ``User_email``)
    - **Unique** constraint name = ``{label}_{prop}_unique``

    All DDL uses ``IF NOT EXISTS`` / ``IF EXISTS`` for idempotency.
    """

    _backend_name = "Neo4j"

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
        username: str = "neo4j",
        password: str = "",  # noqa: S107
        encrypted: bool = True,
        dialect: Neo4jDialect = _NEO4J_DIALECT,
    ) -> Neo4jAdapter:
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

    def fork(self, graph_name: str) -> Neo4jAdapter:
        """Return a new adapter targeting a different Neo4j database."""
        new_driver = BoltDriver(
            uri=self._driver.uri,
            auth=self._driver.auth,
            database=graph_name,
            dialect=_NEO4J_DIALECT,
            encrypted=True,
        )
        return Neo4jAdapter(new_driver, graph_name)

    # ------------------------------------------------------------------
    # DDL — entity types (no-op: Neo4j is schemaless)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    # ------------------------------------------------------------------
    # DDL — indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        entity = f"()-[n:{label}]->()" if rel else f"(n:{label})"
        cypher = f"CREATE INDEX {label}_{prop} IF NOT EXISTS FOR {entity} ON (n.{prop})"
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Neo4j create_range_index failed for %s.%s: %s", label, prop, exc
            )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        cypher = f"DROP INDEX {label}_{prop} IF EXISTS"
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("Neo4j drop_range_index failed for %s.%s: %s", label, prop, exc)

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        prop_list = ", ".join(f"n.{p}" for p in props)
        cypher = (
            f"CREATE FULLTEXT INDEX {label} IF NOT EXISTS "
            f"FOR (n:{label}) ON EACH [{prop_list}]"
        )
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Neo4j create_fulltext_index failed for %s %s: %s", label, props, exc
            )

    def drop_fulltext_index(self, label: str, *props: str) -> None:  # noqa: ARG002
        cypher = f"DROP INDEX {label} IF EXISTS"
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("Neo4j drop_fulltext_index failed for %s: %s", label, exc)

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,
        similarity: str,
        *,
        m: int = 16,  # noqa: ARG002
        ef_construction: int = 200,  # noqa: ARG002
        ef_runtime: int = 10,  # noqa: ARG002
    ) -> None:
        if dimension == 0:
            log.warning(
                "Neo4j create_vector_index: dimension=0 for %s.%s — "
                "pre-create the index with the correct dimension via Cypher DDL.",
                label,
                prop,
            )
            return
        cypher = (
            f"CREATE VECTOR INDEX {label}_{prop} IF NOT EXISTS FOR (n:{label}) ON (n.{prop}) "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dimension}, "
            f"`vector.similarity_function`: '{similarity}'}}}}"
        )
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Neo4j create_vector_index failed for %s.%s: %s", label, prop, exc
            )

    def drop_vector_index(self, label: str, prop: str) -> None:
        cypher = f"DROP INDEX {label}_{prop} IF EXISTS"
        log.info("Neo4j DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "Neo4j drop_vector_index failed for %s.%s: %s", label, prop, exc
            )

    # ------------------------------------------------------------------
    # DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            prop = props[0]
            name = f"{label}_{prop}_unique"
            cypher = (
                f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
            log.info("Neo4j DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "Neo4j create_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "Neo4j create_constraint: unsupported kind=%s entity=%s label=%s props=%s",
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
            name = f"{label}_{prop}_unique"
            cypher = f"DROP CONSTRAINT {name} IF EXISTS"
            log.info("Neo4j DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "Neo4j drop_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "Neo4j drop_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()
