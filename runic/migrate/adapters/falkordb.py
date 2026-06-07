from __future__ import annotations

import logging
import time
from typing import Any

from runic.migrate import introspect
from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import _encode_kv_list, _parse_kv_list
from runic.migrate.exceptions import ConstraintFailedError, ConstraintTimeoutError
from runic.migrate.introspect import LiveSchema
from runic.orm.driver.falkordb import FalkorDBDriver, FalkorDBResult

log = logging.getLogger(__name__)

_POLL_RETRIES = 30
_POLL_INTERVAL = 0.5

_VERSION_LABEL = "_FalkorMigrateVersion"
_GET_VERSION_QUERY = f"MATCH (v:{_VERSION_LABEL}) RETURN v.revisions, v.revision"
_SET_VERSION_QUERY = (
    f"MERGE (v:{_VERSION_LABEL} {{singleton: true}})"
    " SET v.revisions = $revisions, v.applied_at = timestamp()"
)
_GET_TRACKING_QUERY = f"MATCH (v:{_VERSION_LABEL}) RETURN v.checksums, v.installed_by"
_SET_TRACKING_QUERY = (
    f"MERGE (v:{_VERSION_LABEL} {{singleton: true}})"
    " SET v.checksums = $checksums, v.installed_by = $installed_by"
)


class FalkorDBAdapter(GraphAdapter):
    """GraphAdapter implementation for FalkorDB (standalone or embedded via falkordblite).

    Query execution is routed through :class:`~runic.orm.driver.falkordb.FalkorDBDriver`
    so results are normalised to ``GraphResult.rows`` — consistent with Bolt adapters.
    The raw ``db`` and ``graph`` references are kept only for FalkorDB-specific migration
    operations (constraint DDL via Redis commands, snapshot copy/delete).
    """

    def __init__(self, db: Any, graph: Any) -> None:
        self._db = db
        self._graph = graph
        self._driver = FalkorDBDriver(graph)

    @classmethod
    def from_url(
        cls,
        url: str,
        graph_name: str,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> FalkorDBAdapter:
        from falkordb import FalkorDB

        kwargs: dict = {"protocol": 2}
        if username is not None:
            kwargs["username"] = username
        if password is not None:
            kwargs["password"] = password
        db = FalkorDB.from_url(url, **kwargs)
        return cls(db, db.select_graph(graph_name))

    @classmethod
    def from_params(
        cls,
        graph_name: str,
        *,
        host: str = "localhost",
        port: int = 6379,
        username: str | None = None,
        password: str | None = None,
    ) -> FalkorDBAdapter:
        from falkordb import FalkorDB

        kwargs: dict = {"host": host, "port": port}
        if username is not None:
            kwargs["username"] = username
        if password is not None:
            kwargs["password"] = password
        db = FalkorDB(**kwargs)
        return cls(db, db.select_graph(graph_name))

    def fork(self, graph_name: str) -> FalkorDBAdapter:
        """Return a sibling adapter on the same connection for a different graph name."""
        return FalkorDBAdapter(self._db, self._db.select_graph(graph_name))

    # ------------------------------------------------------------------
    # GraphAdapter Protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._graph.name  # type: ignore[no-any-return]

    def execute(self, cypher: str, params: dict[str, Any]) -> FalkorDBResult:
        """Normalised query execution via ORM driver (result has .rows)."""
        return self._driver.execute(cypher, params)

    def run_query(self, query: str, params: dict | None = None) -> FalkorDBResult:
        return self._driver.execute(query, params or {})

    def run_ro_query(self, query: str) -> FalkorDBResult:
        return self._driver.execute(query, {})

    def run_command(self, *args: Any) -> Any:
        return self._db.execute_command(*args)

    # ------------------------------------------------------------------
    # Version tracking
    # ------------------------------------------------------------------

    def get_version(self) -> list[str]:
        try:
            result = self._driver.execute(_GET_VERSION_QUERY, {})
        except Exception as exc:
            if "empty key" in str(exc).lower():
                return []
            raise
        rows = result.rows
        if not rows:
            return []
        row = rows[0]
        col0 = row[0]
        col1 = row[1] if len(row) > 1 else None

        if isinstance(col0, list):
            return [r for r in col0 if r is not None]
        if isinstance(col0, str):
            return [col0]
        if isinstance(col1, str):
            return [col1]
        return []

    def set_version(self, revisions: list[str]) -> None:
        log.info("stamping versions: %s", revisions)
        self._driver.execute(_SET_VERSION_QUERY, {"revisions": revisions})

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def read_live_schema(self) -> LiveSchema:
        return introspect.read_live_schema(self._graph)

    # ------------------------------------------------------------------
    # Schema DDL — range indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if rel:
            query = f"CREATE INDEX FOR ()-[r:{label}]->() ON (r.{prop})"
        else:
            query = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        log.info("creating range index on %s.%s", label, prop)
        self._driver.execute(query, {})

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        query = f"DROP INDEX ON :{label}({prop})"
        log.info("dropping range index on %s.%s", label, prop)
        self._driver.execute(query, {})

    # ------------------------------------------------------------------
    # Schema DDL — fulltext indexes
    # ------------------------------------------------------------------

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None:
        if language or stopwords:
            map_parts = [f"label: '{label}'"]
            if language:
                map_parts.append(f"language: '{language}'")
            if stopwords:
                sw = "[" + ", ".join(f"'{w}'" for w in stopwords) + "]"
                map_parts.append(f"stopwords: {sw}")
            map_literal = "{" + ", ".join(map_parts) + "}"
            props_str = ", ".join(f"'{p}'" for p in props)
            query = f"CALL db.idx.fulltext.createNodeIndex({map_literal}, {props_str})"
        else:
            props_str = ", ".join(f"'{p}'" for p in props)
            query = f"CALL db.idx.fulltext.createNodeIndex('{label}', {props_str})"
        log.info("creating fulltext index on %s %s", label, list(props))
        self._driver.execute(query, {})

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        log.info("dropping fulltext index on %s %s", label, list(props))
        for prop in props:
            query = f"DROP FULLTEXT INDEX FOR (n:{label}) ON (n.{prop})"
            self._driver.execute(query, {})

    # ------------------------------------------------------------------
    # Schema DDL — vector indexes
    # ------------------------------------------------------------------

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
        options = (
            f"{{dimension: {dimension}, similarityFunction: '{similarity}', "
            f"M: {m}, efConstruction: {ef_construction}, efRuntime: {ef_runtime}}}"
        )
        query = f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.{prop}) OPTIONS {options}"
        log.info("creating vector index on %s.%s", label, prop)
        self._driver.execute(query, {})

    def drop_vector_index(self, label: str, prop: str) -> None:
        query = f"DROP VECTOR INDEX FOR (n:{label}) (n.{prop})"
        log.info("dropping vector index on %s.%s", label, prop)
        self._driver.execute(query, {})

    # ------------------------------------------------------------------
    # Schema DDL — constraints
    # ------------------------------------------------------------------

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE":
            for prop in props:
                self.create_range_index(label, prop)
        prop_count = str(len(props))
        log.info("creating %s constraint on %s %s %s", kind, entity, label, props)
        self._db.execute_command(
            "GRAPH.CONSTRAINT",
            "CREATE",
            label,
            kind,
            entity,
            label,
            "PROPERTIES",
            prop_count,
            *props,
        )
        self._poll_constraint(label, props)

    def _poll_constraint(self, label: str, props: list[str]) -> None:
        for _ in range(_POLL_RETRIES):
            result = self._driver.execute("CALL db.constraints()", {})
            for row in result.rows:
                entry = row[0]
                status = entry[4] if isinstance(entry, (list, tuple)) else str(entry)
                if status == "FAILED":
                    raise ConstraintFailedError(f"constraint on {label}.{props} failed")
                if status == "OPERATIONAL":
                    return
            time.sleep(_POLL_INTERVAL)
        raise ConstraintTimeoutError(
            f"constraint on {label}.{props} did not become OPERATIONAL"
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        prop_count = str(len(props))
        log.info("dropping %s constraint on %s %s %s", kind, entity, label, props)
        self._db.execute_command(
            "GRAPH.CONSTRAINT",
            "DROP",
            label,
            kind,
            entity,
            label,
            "PROPERTIES",
            prop_count,
            *props,
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def snapshot(self, snap_name: str) -> None:
        # GRAPH.COPY fails on an empty key; initialize graph if it doesn't exist yet
        if self._graph.name not in self._db.list_graphs():
            self._driver.execute("RETURN 1", {})
        self._graph.copy(snap_name)
        log.debug("snapshot taken: %s → %s", self._graph.name, snap_name)

    def restore_snapshot(self, snap_name: str) -> None:
        snap_graph = self._db.select_graph(snap_name)
        self._graph.delete()
        snap_graph.copy(self._graph.name)
        snap_graph.delete()
        log.debug("snapshot restored: %s → %s", snap_name, self._graph.name)

    def snapshot_exists(self, snap_name: str) -> bool:
        return snap_name in self._db.list_graphs()

    # ------------------------------------------------------------------
    # Checksum & attribution tracking
    # ------------------------------------------------------------------

    def _get_tracking(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (checksums, installed_by) dicts from the version node."""
        try:
            result = self._driver.execute(_GET_TRACKING_QUERY, {})
        except Exception as exc:
            if "empty key" in str(exc).lower():
                return {}, {}
            raise
        rows = result.rows
        if not rows:
            return {}, {}
        row = rows[0]
        checksums = _parse_kv_list(row[0] if row[0] is not None else None)
        installed = _parse_kv_list(
            row[1] if len(row) > 1 and row[1] is not None else None
        )
        return checksums, installed

    def get_checksums(self) -> dict[str, str]:
        checksums, _ = self._get_tracking()
        return checksums

    def get_installed_by(self) -> dict[str, str]:
        _, installed = self._get_tracking()
        return installed

    def set_checksum(
        self, rev_id: str, checksum: str, installed_by: str | None = None
    ) -> None:
        checksums, installed = self._get_tracking()
        checksums[rev_id] = checksum
        if installed_by is not None:
            installed[rev_id] = installed_by
        self._driver.execute(
            _SET_TRACKING_QUERY,
            {
                "checksums": _encode_kv_list(checksums),
                "installed_by": _encode_kv_list(installed),
            },
        )
        log.debug("recorded checksum for revision %s", rev_id)

    def delete_graph(self) -> None:
        """Delete the underlying graph (used for ephemeral test cleanup)."""
        self._graph.delete()
