"""Apache AGE migration adapter.

Apache AGE stores graph data inside PostgreSQL, so migration version-tracking
nodes are created as AGE vertices (not PostgreSQL tables).  The adapter
executes Cypher through the AGE ``cypher()`` SQL function and delegates
agtype decoding to the :mod:`runic.orm.driver.age` module.
"""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.introspect import LiveSchema
from runic.orm.driver.age import AGEDialect, AGEDriver
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

_AGE_DIALECT = AGEDialect()


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


class AGEAdapter(GraphAdapter):
    """Migration adapter for Apache AGE (PostgreSQL graph extension)."""

    def __init__(self, driver: AGEDriver, graph_name: str) -> None:
        self._driver = driver
        self._graph_name = graph_name

    @classmethod
    def from_params(
        cls,
        graph: str,
        *,
        host: str = "localhost",
        port: int = 5432,
        database: str = "postgres",
        username: str = "postgres",
        password: str = "",  # noqa: S107
    ) -> AGEAdapter:
        from runic.orm.driver.age import create_age_driver

        driver = create_age_driver(
            host=host,
            port=port,
            database=database,
            graph=graph,
            username=username,
            password=password,
        )
        return cls(driver, graph)

    @property
    def name(self) -> str:
        return self._graph_name

    def run_query(self, query: str, params: dict | None = None) -> Any:
        result = self._driver.execute(query, params or {})
        # AGEDriver no longer auto-commits; the adapter owns the transaction
        # lifecycle for write operations (not managed by an ORM Session here).
        self._driver.commit()
        return result

    def run_ro_query(self, query: str) -> Any:
        return self._driver.execute(query, {})

    def fork(self, graph_name: str) -> AGEAdapter:
        """Return a new adapter targeting a different AGE graph on the same connection."""
        new_driver = AGEDriver(self._driver._conn, graph_name)  # noqa: SLF001
        return AGEAdapter(new_driver, graph_name)

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

    def read_live_schema(self) -> LiveSchema:
        log.debug(
            "AGEAdapter read_live_schema: returning empty schema (not yet implemented)"
        )
        return LiveSchema(
            range_indexes=[],
            fulltext_indexes=[],
            vector_indexes=[],
            constraints=[],
        )

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        # AGE does not expose a direct Cypher DDL for per-property indexes;
        # indices are created on the underlying PostgreSQL edge/vertex tables.
        log.warning(
            "AGEAdapter create_range_index: AGE does not support Cypher-level "
            "range index creation for %s.%s — create a B-tree index on the "
            "underlying PostgreSQL table manually.",
            label,
            prop,
        )

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        log.warning(
            "AGEAdapter drop_range_index: AGE does not support Cypher-level "
            "range index drops for %s.%s.",
            label,
            prop,
        )

    def get_existing_specs(self) -> set[IndexSpec]:
        """Return empty set — AGE indexes are PostgreSQL-level, not introspectable via Cypher."""
        return set()

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        log.warning(
            "AGEAdapter create_fulltext_index: AGE does not support Cypher-level "
            "fulltext index creation for %s %s — "
            "use PostgreSQL full-text search on the underlying tables.",
            label,
            props,
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        log.warning(
            "AGEAdapter drop_fulltext_index: AGE does not support Cypher-level "
            "fulltext index drops for %s %s.",
            label,
            props,
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
            "AGEAdapter create_vector_index: AGE does not support Cypher-level "
            "vector index creation for %s.%s — "
            "use pgvector on the underlying PostgreSQL tables.",
            label,
            prop,
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        log.warning(
            "AGEAdapter drop_vector_index: AGE does not support Cypher-level "
            "vector index drops for %s.%s.",
            label,
            prop,
        )

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "AGEAdapter create_constraint: AGE does not support Cypher-level "
            "constraint creation (kind=%s entity=%s label=%s props=%s) — "
            "use PostgreSQL constraints on the underlying tables.",
            kind,
            entity,
            label,
            props,
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        log.warning(
            "AGEAdapter drop_constraint: AGE does not support Cypher-level "
            "constraint drops (kind=%s entity=%s label=%s props=%s).",
            kind,
            entity,
            label,
            props,
        )

    def delete_graph(self) -> None:
        log.warning(
            "AGEAdapter delete_graph: dropping all vertices and edges in %r",
            self._graph_name,
        )
        self.run_query("MATCH (n) DETACH DELETE n")

    def snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Apache AGE snapshots are not yet supported via runic migrate."
        )

    def restore_snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "Apache AGE snapshot restore is not yet supported via runic migrate."
        )

    def snapshot_exists(self, snap_name: str) -> bool:  # noqa: ARG002
        return False

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
