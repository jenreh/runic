"""ArcadeDB migration adapter using the Bolt protocol via the neo4j Python driver."""

from __future__ import annotations

import logging
from typing import Any

from runic.migrate.adapters import GraphAdapter
from runic.migrate.introspect import LiveSchema
from runic.orm.driver.arcadedb import ArcadeDBDialect
from runic.orm.driver.bolt import BoltDriver

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

_ARCADE_DIALECT = ArcadeDBDialect()


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


class ArcadeDBAdapter(GraphAdapter):
    """Migration adapter for ArcadeDB accessed via Bolt protocol."""

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
            "ArcadeDB read_live_schema: returning empty schema (not yet implemented)"
        )
        return LiveSchema(
            range_indexes=[],
            fulltext_indexes=[],
            vector_indexes=[],
            constraints=[],
        )

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

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None:
        raise NotImplementedError(
            "ArcadeDB fulltext index creation via runic migrate is not yet supported."
        )

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        raise NotImplementedError(
            "ArcadeDB fulltext index drop via runic migrate is not yet supported."
        )

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,
        similarity: str,
        *,
        m: int = 16,
        ef_construction: int = 200,
        ef_runtime: int = 10,
    ) -> None:
        raise NotImplementedError(
            "ArcadeDB vector index creation via runic migrate is not yet supported."
        )

    def drop_vector_index(self, label: str, prop: str) -> None:
        raise NotImplementedError(
            "ArcadeDB vector index drop via runic migrate is not yet supported."
        )

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        raise NotImplementedError(
            "ArcadeDB constraint creation via runic migrate is not yet supported."
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        raise NotImplementedError(
            "ArcadeDB constraint drop via runic migrate is not yet supported."
        )

    def delete_graph(self) -> None:
        log.warning(
            "ArcadeDB delete_graph: dropping all vertices and edges in %r",
            self._database,
        )
        self.run_query("MATCH (n) DETACH DELETE n")

    def snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "ArcadeDB snapshots are not yet supported via runic migrate."
        )

    def restore_snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            "ArcadeDB snapshot restore is not yet supported via runic migrate."
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
