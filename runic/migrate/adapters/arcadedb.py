"""ArcadeDB migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.orm.driver.arcadedb import ArcadeDBDialect
from runic.orm.driver.bolt import BoltDriver
from runic.orm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)

_ARCADE_DIALECT = ArcadeDBDialect()


class ArcadeDBAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for ArcadeDB accessed via Bolt protocol.

    ArcadeDB requires explicit type declarations before indexes can be created
    on empty collections.  ``create_vertex_type`` and ``create_edge_type``
    issue real DDL (``CREATE VERTEX/EDGE TYPE ... IF NOT EXISTS``).

    Vector indexes are created via the ArcadeDB HTTP management API, not
    openCypher DDL — ``create_vector_index`` logs a warning instead.
    """

    _backend_name = "ArcadeDB"

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
        username: str = "root",
        password: str = "",  # noqa: S107
    ) -> ArcadeDBAdapter:
        driver = BoltDriver.from_params(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            dialect=_ARCADE_DIALECT,
            encrypted=False,
        )
        return cls(driver, database)

    @property
    def name(self) -> str:
        return self._database

    def run_query(self, query: str, params: dict | None = None) -> Any:
        return self._driver.execute(query, params or {})

    def run_ro_query(self, query: str) -> Any:
        return self._driver.execute(query, {})

    def fork(self, graph_name: str) -> ArcadeDBAdapter:
        """Return a new adapter targeting a different ArcadeDB database."""
        new_driver = BoltDriver(
            uri=self._driver.uri,
            auth=self._driver.auth,
            database=graph_name,
            dialect=_ARCADE_DIALECT,
            encrypted=False,
        )
        return ArcadeDBAdapter(new_driver, graph_name)

    # ------------------------------------------------------------------
    # DDL — entity types (ArcadeDB requires explicit type creation)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:
        cypher = f"CREATE VERTEX TYPE `{label}` IF NOT EXISTS"
        log.info("ArcadeDB DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("ArcadeDB create_vertex_type failed for %s: %s", label, exc)

    def create_edge_type(self, type_name: str) -> None:
        cypher = f"CREATE EDGE TYPE `{type_name}` IF NOT EXISTS"
        log.info("ArcadeDB DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning("ArcadeDB create_edge_type failed for %s: %s", type_name, exc)

    # ------------------------------------------------------------------
    # DDL — indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        cypher = f"CREATE INDEX ON `{label}` ({prop})"
        log.info("ArcadeDB: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "ArcadeDB create_range_index failed for %s.%s: %s", label, prop, exc
            )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        cypher = f"DROP INDEX ON `{label}` ({prop})"
        log.info("ArcadeDB: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "ArcadeDB drop_range_index failed for %s.%s: %s", label, prop, exc
            )

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        props_str = ", ".join(props)
        cypher = f"CREATE FULLTEXT INDEX ON `{label}` ({props_str})"
        log.info("ArcadeDB DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "ArcadeDB create_fulltext_index failed for %s %s: %s", label, props, exc
            )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        props_str = ", ".join(props)
        cypher = f"DROP INDEX ON `{label}` ({props_str})"
        log.info("ArcadeDB DDL: %s", cypher)
        try:
            self.run_query(cypher)
        except Exception as exc:
            log.warning(
                "ArcadeDB drop_fulltext_index failed for %s %s: %s", label, props, exc
            )

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,  # noqa: ARG002
        similarity: str,  # noqa: ARG002
        *,
        m: int = 16,  # noqa: ARG002
        ef_construction: int = 200,  # noqa: ARG002
        ef_runtime: int = 10,  # noqa: ARG002
    ) -> None:
        log.warning(
            "ArcadeDB create_vector_index: %s.%s — "
            "use the ArcadeDB HTTP management API to create vector indexes.",
            label,
            prop,
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        log.warning(
            "ArcadeDB drop_vector_index: %s.%s — "
            "use the ArcadeDB HTTP management API to manage vector indexes.",
            label,
            prop,
        )

    # ------------------------------------------------------------------
    # DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            prop = props[0]
            cypher = f"CREATE INDEX ON `{label}` ({prop}) UNIQUE"
            log.info("ArcadeDB DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "ArcadeDB create_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "ArcadeDB create_constraint: unsupported kind=%s entity=%s label=%s props=%s",
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
            cypher = f"DROP INDEX ON `{label}` ({prop}) UNIQUE"
            log.info("ArcadeDB DDL: %s", cypher)
            try:
                self.run_query(cypher)
            except Exception as exc:
                log.warning(
                    "ArcadeDB drop_constraint failed for %s.%s: %s", label, prop, exc
                )
        else:
            log.warning(
                "ArcadeDB drop_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )
