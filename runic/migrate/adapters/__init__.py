from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from runic.migrate.introspect import LiveSchema


@runtime_checkable
class GraphAdapter(Protocol):
    """Protocol all graph-database adapters must satisfy.

    The runic core depends only on this interface — no FalkorDB or any other
    concrete database client leaks into shared code.

    Note: ``LiveSchema`` (returned by ``read_live_schema``) is currently parsed
    from FalkorDB's ``CALL db.indexes()`` / ``CALL db.constraints()`` output in
    ``runic.migrate.introspect``.  A future adapter must override ``read_live_schema``
    and may supply its own introspection logic.
    """

    @property
    def name(self) -> str: ...

    # Low-level query execution
    def run_query(self, query: str, params: dict | None = None) -> Any: ...
    def run_ro_query(self, query: str) -> Any: ...

    # Sibling adapter for a different graph/database on the same connection
    def fork(self, graph_name: str) -> GraphAdapter: ...

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

    # Checksum & attribution tracking
    def get_checksums(self) -> dict[str, str]: ...
    def set_checksum(
        self, rev_id: str, checksum: str, installed_by: str | None = None
    ) -> None: ...
    def get_installed_by(self) -> dict[str, str]: ...


def create_adapter(backend: str, **kwargs: Any) -> GraphAdapter:
    """Instantiate a named adapter from keyword arguments.

    Two connection variants are supported for ``"falkordb"``:

    **URL variant** — credentials embedded in the connection string::

        create_adapter(
            "falkordb", url="falkor://:mypassword@localhost:6379", graph_name="my_graph"
        )

    **Params variant** — explicit host/port/auth kwargs::

        create_adapter(
            "falkordb",
            host="localhost",
            port=6379,
            username="myuser",
            password="mypassword",
            graph_name="my_graph",
        )
    """
    if backend == "falkordb":
        from runic.migrate.adapters.falkordb import FalkorDBAdapter

        graph_name = kwargs["graph_name"]
        if "url" in kwargs:
            return FalkorDBAdapter.from_url(
                kwargs["url"],
                graph_name,
                username=kwargs.get("username"),
                password=kwargs.get("password"),
            )
        return FalkorDBAdapter.from_params(
            graph_name,
            host=kwargs.get("host", "localhost"),
            port=int(kwargs.get("port", 6379)),
            username=kwargs.get("username"),
            password=kwargs.get("password"),
        )
    raise KeyError(f"Unknown adapter backend {backend!r}. Supported: 'falkordb'")


__all__ = ["GraphAdapter", "create_adapter"]
