"""Shared base class for runic migrate adapters with Cypher-based version tracking.

Provides concrete implementations of version tracking, checksum recording,
schema introspection stubs, and graph lifecycle operations.  Subclasses
must implement :attr:`name`, :meth:`run_query`, and :meth:`run_ro_query`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from runic.migrate.introspect import LiveSchema
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


@runtime_checkable
class IndexAdapter(Protocol):
    """Structural protocol satisfied by all runic migrate GraphAdapter subclasses.

    IndexManager and SchemaManager in runic.migrate.schema accept any object
    satisfying this protocol — no explicit ``implements`` declaration is needed.
    """

    def create_range_index(
        self, label: str, prop: str, *, rel: bool = False
    ) -> None: ...

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None: ...

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None: ...

    def drop_fulltext_index(self, label: str, *props: str) -> None: ...

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
    ) -> None: ...

    def drop_vector_index(self, label: str, prop: str) -> None: ...

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None: ...

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None: ...

    def create_vertex_type(self, label: str) -> None: ...

    def create_edge_type(self, type_name: str) -> None: ...

    def get_existing_specs(self) -> set[IndexSpec]: ...


class GraphAdapterBase(ABC):
    """Abstract base for runic migrate adapters.

    Provides shared implementations of version tracking, checksum recording,
    empty schema introspection, and graph lifecycle.  Subclasses set
    ``_backend_name`` and implement :attr:`name`, :meth:`run_query`,
    :meth:`run_ro_query`, and all DDL methods.
    """

    _backend_name: str = "Unknown"

    @property
    @abstractmethod
    def name(self) -> str:
        """The database / graph name this adapter targets."""
        ...

    @abstractmethod
    def run_query(self, query: str, params: dict | None = None) -> Any:
        """Execute a Cypher write query and return the result."""
        ...

    @abstractmethod
    def run_ro_query(self, query: str) -> Any:
        """Execute a read-only Cypher query and return the result."""
        ...

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
        log.debug("%s read_live_schema: returning empty schema", self._backend_name)
        return LiveSchema(
            range_indexes=[],
            fulltext_indexes=[],
            vector_indexes=[],
            constraints=[],
        )

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def delete_graph(self) -> None:
        log.warning(
            "%s delete_graph: dropping all vertices and edges in %r",
            self._backend_name,
            self.name,
        )
        self.run_query("MATCH (n) DETACH DELETE n")

    def snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            f"{self._backend_name} snapshots are not supported via runic migrate."
        )

    def restore_snapshot(self, snap_name: str) -> None:
        raise NotImplementedError(
            f"{self._backend_name} snapshot restore is not supported via runic migrate."
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
