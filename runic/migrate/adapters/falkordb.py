from __future__ import annotations

import logging
import time
from typing import Any

from runic.cypher import escape_identifier, escape_string
from runic.migrate import introspect
from runic.migrate.adapters import GraphAdapter
from runic.migrate.adapters._base import _encode_kv_list, _parse_kv_list
from runic.migrate.exceptions import ConstraintFailedError, ConstraintTimeoutError
from runic.migrate.introspect import LiveSchema
from runic.migrate.manifest import UniqueConstraint
from runic.ogm.driver.falkordb import FalkorDBDriver, FalkorDBResult
from runic.ogm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)

_POLL_RETRIES = 30
_POLL_INTERVAL = 0.5

# FalkorDB vector index similarity functions are a closed set; reject anything
# else early rather than interpolate an unknown value into the OPTIONS map.
_VECTOR_SIMILARITY_FUNCTIONS = frozenset({"euclidean", "cosine"})

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

    Query execution is routed through :class:`~runic.ogm.driver.falkordb.FalkorDBDriver`
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
        """Normalised query execution via OGM driver (result has .rows)."""
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

    # ------------------------------------------------------------------
    # DDL — entity types (no-op: FalkorDB is schemaless)
    # ------------------------------------------------------------------

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def read_live_schema(self) -> LiveSchema:
        return introspect.read_live_schema(self._graph)

    def introspect_schema(self) -> introspect.SchemaSnapshot:
        return introspect.introspect_graph(self._graph)

    def get_existing_specs(self) -> set[IndexSpec]:
        try:
            schema = self.read_live_schema()
        except Exception as exc:
            if "empty key" in str(exc).lower():
                log.debug("graph does not exist yet — returning empty spec set")
                return set()
            raise
        unique_pairs: set[tuple[str, str]] = set()
        specs: set[IndexSpec] = set()
        for con in schema.constraints:
            kind = "UNIQUE" if isinstance(con, UniqueConstraint) else "MANDATORY"
            for prop in con.props:
                specs.add(IndexSpec(label=con.label, property=prop, index_type=kind))
                if kind == "UNIQUE":
                    unique_pairs.add((con.label, prop))
        for ri in schema.range_indexes:
            if (ri.label, ri.prop) in unique_pairs:
                continue
            specs.add(IndexSpec(label=ri.label, property=ri.prop, index_type="RANGE"))
        for fi in schema.fulltext_indexes:
            for prop in fi.props:
                specs.add(
                    IndexSpec(label=fi.label, property=prop, index_type="FULLTEXT")
                )
        for vi in schema.vector_indexes:
            specs.add(IndexSpec(label=vi.label, property=vi.prop, index_type="VECTOR"))
        return specs

    # ------------------------------------------------------------------
    # Schema DDL — range indexes
    # ------------------------------------------------------------------

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        label_id = escape_identifier(label)
        prop_id = escape_identifier(prop)
        if rel:
            query = f"CREATE INDEX FOR ()-[r:{label_id}]->() ON (r.{prop_id})"
        else:
            query = f"CREATE INDEX FOR (n:{label_id}) ON (n.{prop_id})"
        log.info("creating range index on %s.%s", label, prop)
        self._driver.execute(query, {})

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        query = f"DROP INDEX ON :{escape_identifier(label)}({escape_identifier(prop)})"
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
        props_str = ", ".join(escape_string(p) for p in props)
        if language or stopwords:
            map_parts = [f"label: {escape_string(label)}"]
            if language:
                map_parts.append(f"language: {escape_string(language)}")
            if stopwords:
                sw = "[" + ", ".join(escape_string(w) for w in stopwords) + "]"
                map_parts.append(f"stopwords: {sw}")
            map_literal = "{" + ", ".join(map_parts) + "}"
            query = f"CALL db.idx.fulltext.createNodeIndex({map_literal}, {props_str})"
        else:
            query = (
                "CALL db.idx.fulltext.createNodeIndex("
                f"{escape_string(label)}, {props_str})"
            )
        log.info("creating fulltext index on %s %s", label, list(props))
        self._driver.execute(query, {})

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        log.info("dropping fulltext index on %s %s", label, list(props))
        label_id = escape_identifier(label)
        for prop in props:
            query = f"DROP FULLTEXT INDEX FOR (n:{label_id}) ON (n.{escape_identifier(prop)})"
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
        if similarity not in _VECTOR_SIMILARITY_FUNCTIONS:
            msg = (
                f"unsupported vector similarity function {similarity!r}; "
                f"expected one of {sorted(_VECTOR_SIMILARITY_FUNCTIONS)}"
            )
            raise ValueError(msg)
        label_id = escape_identifier(label)
        prop_id = escape_identifier(prop)
        options = (
            f"{{dimension: {dimension}, similarityFunction: {escape_string(similarity)}, "
            f"M: {m}, efConstruction: {ef_construction}, efRuntime: {ef_runtime}}}"
        )
        query = (
            f"CREATE VECTOR INDEX FOR (n:{label_id}) ON (n.{prop_id}) OPTIONS {options}"
        )
        log.info("creating vector index on %s.%s", label, prop)
        self._driver.execute(query, {})

    def drop_vector_index(self, label: str, prop: str) -> None:
        query = (
            f"DROP VECTOR INDEX FOR (n:{escape_identifier(label)}) "
            f"(n.{escape_identifier(prop)})"
        )
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
            self._graph.name,
            kind,
            entity,
            label,
            "PROPERTIES",
            prop_count,
            *props,
        )
        self._poll_constraint(label, props)

    def _poll_constraint(self, label: str, props: list[str]) -> None:
        target_props = list(props)
        for _ in range(_POLL_RETRIES):
            result = self._driver.execute("CALL db.constraints()", {})
            for row in result.rows:
                # Each row is a flat list of columns, consistent with
                # introspect.read_live_schema():
                #   [type, label, properties, entity_type, status]
                if not isinstance(row, (list, tuple)) or len(row) < 5:
                    continue
                if row[1] != label or list(row[2]) != target_props:
                    continue
                status = row[4]
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
            self._graph.name,
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

    def supports_snapshots(self) -> bool:
        return True

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


# ---------------------------------------------------------------------------
# FalkorDBIndexAdapter — wraps raw FalkorDB graph handles
# ---------------------------------------------------------------------------

_INDEX_TYPES = frozenset({"RANGE", "FULLTEXT", "VECTOR", "UNIQUE"})


def _parse_existing_specs(graph: Any) -> set[IndexSpec]:
    """Parse live FalkorDB graph state and return all existing NODE index/constraint specs.

    Used by FalkorDBIndexAdapter for the raw-graph-handle backward-compat path.
    """
    specs: set[IndexSpec] = set()
    unique_pairs: set[tuple[str, str]] = set()

    try:
        for constraint in graph.list_constraints():
            if constraint.get("type") != "UNIQUE":
                continue
            if constraint.get("entitytype") != "NODE":
                continue
            lbl: str = constraint["label"]
            for prop in constraint.get("properties", []):
                specs.add(IndexSpec(label=lbl, property=prop, index_type="UNIQUE"))
                unique_pairs.add((lbl, prop))
    except Exception:
        log.debug("list_constraints() unavailable or failed")

    try:
        result = graph.list_indices()
        col_map: dict[str, int] = {col[1]: idx for idx, col in enumerate(result.header)}
        label_col = col_map.get("label", 0)
        types_col = col_map.get("types", 2)
        entitytype_col = col_map.get("entitytype", 6)

        for row in result.result_set:
            if row[entitytype_col] != "NODE":
                continue
            lbl = row[label_col]
            types_dict = row[types_col]
            for prop, type_list in types_dict.items():
                for idx_type in type_list:
                    if idx_type == "RANGE" and (lbl, prop) in unique_pairs:
                        continue
                    if idx_type in _INDEX_TYPES:
                        specs.add(
                            IndexSpec(label=lbl, property=prop, index_type=idx_type)
                        )
    except Exception:
        log.debug("list_indices() unavailable or failed")

    return specs


class FalkorDBIndexAdapter:
    """Adapts a raw FalkorDB graph handle to the IndexAdapter protocol.

    Auto-created by IndexManager when a raw graph handle (identified by the
    presence of ``create_node_range_index``) is passed — preserving backward
    compat for existing ``IndexManager(graph)`` call sites.  Prefer passing a
    :class:`FalkorDBAdapter` (from ``runic.migrate.adapters``) instead.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        self._graph.create_node_range_index(label, prop)

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        self._graph.drop_node_range_index(label, prop)

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        self._graph.create_node_fulltext_index(label, *props)

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        self._graph.drop_node_fulltext_index(label, *props)

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
        self._graph.create_node_vector_index(label, prop)

    def drop_vector_index(self, label: str, prop: str) -> None:
        self._graph.drop_node_vector_index(label, prop)

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            self._graph.create_node_unique_constraint(label, props[0])
        else:
            log.warning(
                "FalkorDB create_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            self._graph.drop_node_unique_constraint(label, props[0])
        else:
            log.warning(
                "FalkorDB drop_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    def get_existing_specs(self) -> set[IndexSpec]:
        return _parse_existing_specs(self._graph)
