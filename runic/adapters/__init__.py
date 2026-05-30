from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from runic.introspect import LiveSchema


@runtime_checkable
class GraphAdapter(Protocol):
    """Protocol all graph-database adapters must satisfy.

    The runic core depends only on this interface — no FalkorDB or any other
    concrete database client leaks into shared code.
    """

    @property
    def name(self) -> str: ...

    # Low-level query execution
    def run_query(self, query: str, params: dict | None = None) -> Any: ...
    def run_ro_query(self, query: str) -> Any: ...

    # Version tracking
    def get_version(self) -> list[str]: ...
    def set_version(self, revisions: list[str]) -> None: ...

    # Schema introspection
    def read_live_schema(self) -> LiveSchema: ...

    # Schema DDL
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

    # Snapshots
    def snapshot(self, snap_name: str) -> None: ...
    def restore_snapshot(self, snap_name: str) -> None: ...
    def snapshot_exists(self, snap_name: str) -> bool: ...


__all__ = ["GraphAdapter"]
