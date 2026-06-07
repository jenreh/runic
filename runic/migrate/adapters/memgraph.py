"""Memgraph migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.introspect import LiveSchema
from runic.orm.driver.bolt import BoltDriver
from runic.orm.driver.memgraph import _MEMGRAPH_DIALECT, MemgraphDialect
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


class MemgraphAdapter(GraphAdapter):
    """Migration adapter for Memgraph accessed via Bolt protocol.

    Named index convention (must match :class:`~runic.orm.driver.memgraph.MemgraphDialect`):

    - **Fulltext** (text search) index name = ``{label}`` (e.g. ``Post``)
    - **Vector** index name = ``{label}_{prop}`` (e.g. ``Article_embedding``)
    - **Range** indexes via ``CREATE INDEX ON :{label}({prop})`` — idempotent in Memgraph

    Requires the MAGE ``text_search`` and ``vector_search`` modules for
    fulltext and vector search respectively.
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
        log.debug("Memgraph read_live_schema: returning empty schema")
        return LiveSchema(
            range_indexes=[],
            fulltext_indexes=[],
            vector_indexes=[],
            constraints=[],
        )

    def get_existing_specs(self) -> set[IndexSpec]:
        """Return empty set — Memgraph DDL is idempotent for range; others use try/except."""
        return set()

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

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if rel:
            cypher = f"CREATE INDEX ON :{label}({prop})"
        else:
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

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def delete_graph(self) -> None:
        log.warning(
            "Memgraph delete_graph: dropping all nodes and relationships in %r",
            self._database,
        )
        self.run_query("MATCH (n) DETACH DELETE n")

    def snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Memgraph snapshots are not supported via runic migrate."
        )

    def restore_snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Memgraph snapshot restore is not supported via runic migrate."
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
