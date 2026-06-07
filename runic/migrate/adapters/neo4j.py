"""Neo4j migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.introspect import LiveSchema
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.neo4j import _NEO4J_DIALECT, Neo4jDialect
from runic.orm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)

_VERSION_LABEL = "_RunicMigrateVersion"
_GET_VERSION_QUERY = f"MATCH (v:{_VERSION_LABEL}) RETURN v.revisions"
_SET_VERSION_QUERY = (
    f"MERGE (v:{_VERSION_LABEL} {{singleton: true}})"
    " SET v.revisions = $revisions, v.applied_at = timestamp()"
)
_GET_TRACKING_QUERY = f"MATCH (v:{_VERSION_LABEL}) RETURN v.checksums, v.installed_by"
_SET_TRACKING_QUERY = (
    f"MERGE (v:{_VERSION_LABEL} {{singleton: true}})"
    " SET v.checksums = $checksums, v.installed_by = $installed_by"
)


def _parse_kv_list(items: list | None) -> dict[str, str]:
    if not items:
        return {}
    result: dict[str, str] = {}
    for item in items:
        if item:
            k, _, v = str(item).partition(":")
            result[k] = v
    return result


def _encode_kv_list(d: dict[str, str]) -> list[str]:
    return [f"{k}:{v}" for k, v in d.items()]


class Neo4jAdapter(GraphAdapter):
    """Migration adapter for Neo4j 5.x accessed via Bolt protocol.

    Named index convention (must match :class:`~runic.orm.driver.neo4j.Neo4jDialect`):

    - **Fulltext** index name = ``{label}`` (e.g. ``Post``)
    - **Vector** index name = ``{label}_{prop}`` (e.g. ``Article_embedding``)
    - **Range** index name = ``{label}_{prop}`` (e.g. ``User_email``)
    - **Unique** constraint name = ``{label}_{prop}_unique``

    All DDL uses ``IF NOT EXISTS`` / ``IF EXISTS`` for idempotency.
    """

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
    # Version tracking
    # ------------------------------------------------------------------

    def get_version(self) -> list[str]:
        result = self.run_ro_query(_GET_VERSION_QUERY)
        if result.rows:
            revisions = result.rows[0][0]
            if isinstance(revisions, list):
                return [str(r) for r in revisions]
            if revisions is not None:
                return str(revisions).split(",")
        return []

    def set_version(self, revisions: list[str]) -> None:
        self.run_query(_SET_VERSION_QUERY, {"revisions": revisions})

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def read_live_schema(self) -> LiveSchema:
        log.debug(
            "Neo4j read_live_schema: returning empty schema (introspect via SHOW INDEXES)"
        )
        return LiveSchema(
            range_indexes=[],
            fulltext_indexes=[],
            vector_indexes=[],
            constraints=[],
        )

    def get_existing_specs(self) -> set[IndexSpec]:
        """Return empty set — Neo4j DDL uses IF NOT EXISTS for idempotency."""
        return set()

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
        cypher = f"CREATE FULLTEXT INDEX {label} IF NOT EXISTS FOR (n:{label}) ON EACH [{prop_list}]"
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
            cypher = f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
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

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def delete_graph(self) -> None:
        log.warning(
            "Neo4j delete_graph: dropping all nodes and relationships in %r",
            self._database,
        )
        self.run_query("MATCH (n) DETACH DELETE n")

    def snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Neo4j snapshots are not supported via runic migrate."
        )

    def restore_snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Neo4j snapshot restore is not supported via runic migrate."
        )

    def snapshot_exists(self, snap_name: str) -> bool:  # noqa: ARG002
        return False

    # ------------------------------------------------------------------
    # Checksum tracking
    # ------------------------------------------------------------------

    def get_checksums(self) -> dict[str, str]:
        result = self.run_ro_query(_GET_TRACKING_QUERY)
        if result.rows:
            return _parse_kv_list(result.rows[0][0])
        return {}

    def set_checksum(
        self, rev_id: str, checksum: str, installed_by: str | None = None
    ) -> None:
        current = self.get_checksums()
        current[rev_id] = checksum
        current_by = self.get_installed_by()
        if installed_by:
            current_by[rev_id] = installed_by
        self.run_query(
            _SET_TRACKING_QUERY,
            {
                "checksums": _encode_kv_list(current),
                "installed_by": _encode_kv_list(current_by),
            },
        )

    def get_installed_by(self) -> dict[str, str]:
        result = self.run_ro_query(_GET_TRACKING_QUERY)
        if result.rows and len(result.rows[0]) > 1:
            return _parse_kv_list(result.rows[0][1])
        return {}
