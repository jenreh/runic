"""runic.ogm.driver — database driver and dialect Protocols (ISP-compliant)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldInfo


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


class CypherFeature:
    """Names of Cypher constructs whose support varies by backend.

    Backends implement different subsets of Cypher, and the differences are not
    discoverable from the query — a statement using one simply fails at the
    driver with a syntax error naming a character. Naming the constructs lets
    the builder refuse to emit Cypher a backend cannot parse, and say which
    construct and which backend, before the query is sent.
    """

    RELATIONSHIP_ALTERNATION = "relationship_alternation"
    """``[:A|B]`` — one pattern matching either type. Absent on Apache AGE."""

    UNDIRECTED_MERGE = "undirected_merge"
    """``MERGE (a)-[r:T]-(b)`` without an arrow. Absent on FalkorDB."""

    PROCEDURE_CALL = "procedure_call"
    """``CALL … YIELD`` for arbitrary procedures. Absent on ArcadeDB and AGE."""

    FULLTEXT_SEARCH = "fulltext_search"
    """A fulltext index queryable from Cypher. Absent on ArcadeDB and AGE."""

    VECTOR_SEARCH = "vector_search"
    """A vector index queryable from Cypher. Absent on AGE."""


def dialect_supports(dialect: Any, feature: str) -> bool:
    """Return whether *dialect* supports *feature*, assuming yes when unstated.

    Dialects declare only their gaps, so a backend that says nothing is taken
    to support the construct — which keeps the common case quiet and puts the
    burden on the backend that is unusual.
    """
    if dialect is None:
        return True
    unsupported = getattr(dialect, "unsupported_features", frozenset())
    return feature not in unsupported


def require_feature(dialect: Any, feature: str, construct: str) -> None:
    """Raise if *dialect* cannot parse *construct*, naming both.

    Emitting Cypher a backend rejects produces a driver-level syntax error
    pointing at a character, which says nothing about which builder call caused
    it. This turns that into a sentence.
    """
    if dialect_supports(dialect, feature):
        return
    backend = type(dialect).__name__.removesuffix("Dialect")
    msg = (
        f"{backend} does not support {construct}. "
        f"Express the query without it, or drop to a backend-specific "
        f"statement via session.execute()."
    )
    raise NotImplementedError(msg)


class GraphDialect(Protocol):
    """Strategy: all DB-specific Cypher clause and function generation."""

    unsupported_features: frozenset[str]
    """Cypher constructs this backend cannot parse. Empty for most backends."""

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
    OGM Session to wrap multi-query operations in a single database transaction.

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
