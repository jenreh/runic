"""runic.orm.driver — database driver and dialect Protocols (ISP-compliant)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from runic.orm.core.descriptors import FieldInfo


class GraphNode(Protocol):
    """Normalised graph node returned by any driver."""

    @property
    def element_id(self) -> Any: ...

    @property
    def labels(self) -> list[str]: ...

    @property
    def properties(self) -> dict[str, Any]: ...


class GraphEdge(Protocol):
    """Normalised graph edge/relationship returned by any driver."""

    @property
    def type(self) -> str: ...

    @property
    def properties(self) -> dict[str, Any]: ...


class GraphResult(Protocol):
    """Normalised query result returned by any driver."""

    @property
    def rows(self) -> list[list[Any]]: ...

    @property
    def columns(self) -> list[str]: ...


class GraphDialect(Protocol):
    """Strategy: all DB-specific Cypher clause and function generation."""

    def generated_id_where(self, alias: str, param: str) -> str:
        """Return ``WHERE id({alias}) = ...`` clause for generated-PK lookups."""
        ...

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:
        """Return the Cypher wrapping function name for *fi*, or ``None``."""
        ...

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:
        """Return the CALL/YIELD clause that opens a fulltext search query."""
        ...

    def vector_knn_start(
        self, alias: str, labels_str: str, type_name: str, field_name: str
    ) -> str:
        """Return the MATCH/CALL clause that opens a vector KNN query."""
        ...

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:
        """Return the score expression to append to the RETURN clause."""
        ...

    def wrap_node(self, raw: Any) -> GraphNode:
        """Wrap a raw driver node object into the ``GraphNode`` Protocol."""
        ...

    def wrap_edge(self, raw: Any) -> GraphEdge:
        """Wrap a raw driver edge object into the ``GraphEdge`` Protocol."""
        ...


class GraphDriver(Protocol):
    """Sync graph database driver Protocol."""

    @property
    def dialect(self) -> GraphDialect: ...

    def execute(self, cypher: str, params: dict[str, Any]) -> GraphResult: ...

    def close(self) -> None: ...


@runtime_checkable
class TransactionalGraphDriver(Protocol):
    """Sync driver that supports explicit ACID transactions.

    Drivers that implement this protocol (BoltDriver, AGEDriver) allow the
    ORM Session to wrap multi-query operations in a single database transaction.

    Drivers without native transaction support (FalkorDB) do NOT implement
    this protocol — each query is individually atomic at the DB level.

    Lifecycle::

        driver.begin()  # open a transaction
        driver.execute(...)  # run queries within the transaction
        driver.commit()  # commit all changes atomically
        # — or —
        driver.rollback()  # discard all changes since begin()
    """

    def begin(self) -> None:
        """Open a new transaction.

        Raises ``RuntimeError`` if a transaction is already active.
        """
        ...

    def commit(self) -> None:
        """Commit the active transaction.

        No-op when no transaction is active.
        """
        ...

    def rollback(self) -> None:
        """Roll back the active transaction.

        No-op when no transaction is active.
        """
        ...


class AsyncGraphDriver(Protocol):
    """Async graph database driver Protocol."""

    @property
    def dialect(self) -> GraphDialect: ...

    async def execute(self, cypher: str, params: dict[str, Any]) -> GraphResult: ...

    async def close(self) -> None: ...
