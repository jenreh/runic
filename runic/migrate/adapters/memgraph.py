"""Memgraph migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import GraphAdapterBase
from runic.ogm.driver.bolt import BoltDriver
from runic.ogm.driver.memgraph import _MEMGRAPH_DIALECT, MemgraphDialect
from runic.ogm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)


class MemgraphAdapter(GraphAdapterBase, GraphAdapter):
    """Migration adapter for Memgraph accessed via Bolt protocol.

    Named index convention (must match :class:`~runic.ogm.driver.memgraph.MemgraphDialect`):

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

    def execute(self, cypher: str, params: dict[str, Any]) -> Any:
        return self._driver.execute(cypher, params)

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
        self._execute_ddl(f"CREATE INDEX ON :{label}({prop})")

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        self._execute_ddl(f"DROP INDEX ON :{label}({prop})")

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        # Memgraph TEXT INDEX is whole-label; index name = label (matches MemgraphDialect)
        if len(props) > 1:
            log.warning(
                "Memgraph text indexes cover the full label — "
                "multiple props %s on %s map to one whole-label index",
                props,
                label,
            )
        self._execute_ddl(f"CREATE TEXT INDEX {label} ON :{label}")

    def drop_fulltext_index(self, label: str, *props: str) -> None:  # noqa: ARG002
        self._execute_ddl(f"DROP TEXT INDEX {label}")

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
        self._execute_ddl(cypher)

    def drop_vector_index(self, label: str, prop: str) -> None:
        self._execute_ddl(f"DROP VECTOR INDEX {label}_{prop}")

    # ------------------------------------------------------------------
    # DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            prop = props[0]
            self._execute_ddl(
                f"CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE"
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
            self._execute_ddl(
                f"DROP CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE"
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
        specs: set[IndexSpec] = set()
        try:
            result = self.run_ro_query("SHOW INDEX INFO")
            for row in result.rows:
                idx_type, label, prop = row[0], row[1], row[2]
                if idx_type == "label+property" and prop:
                    specs.add(IndexSpec(label=label, property=prop, index_type="RANGE"))
        except Exception as exc:
            log.warning("Memgraph SHOW INDEX INFO failed: %s", exc)
        try:
            result = self.run_ro_query("SHOW CONSTRAINT INFO")
            for row in result.rows:
                con_type, label, props = row[0], row[1], row[2]
                kind = (
                    "UNIQUE"
                    if con_type == "unique"
                    else "MANDATORY"
                    if con_type == "exists"
                    else None
                )
                if not kind:
                    continue
                prop_list = props if isinstance(props, list) else [props]
                for prop in prop_list:
                    specs.add(IndexSpec(label=label, property=prop, index_type=kind))
        except Exception as exc:
            log.warning("Memgraph SHOW CONSTRAINT INFO failed: %s", exc)
        return specs
