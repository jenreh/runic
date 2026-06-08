"""BoltDriver for neo4j-compatible databases (ArcadeDB, Neo4j) via neo4j Python driver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.ogm.driver import GraphDialect

log = logging.getLogger(__name__)


class BoltNode:
    """Wraps a ``neo4j.Node`` to conform to ``GraphNode``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def element_id(self) -> Any:
        # Use deprecated .id (int) for compatibility with ArcadeDB Bolt and neo4j <5
        return self._raw.id

    @property
    def labels(self) -> list[str]:
        return list(self._raw.labels)

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw)


class BoltEdge:
    """Wraps a ``neo4j.Relationship`` to conform to ``GraphEdge``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def type(self) -> str:
        return self._raw.type

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw)


class BoltResult:
    """Eagerly-collected Bolt query result conforming to ``GraphResult``."""

    __slots__ = ("_columns", "_rows")

    def __init__(self, rows: list[list[Any]], columns: list[str]) -> None:
        self._rows = rows
        self._columns = columns

    @property
    def rows(self) -> list[list[Any]]:
        return self._rows

    @property
    def columns(self) -> list[str]:
        return self._columns


class BoltDriver:
    """Sync Bolt driver for ArcadeDB, Neo4j, or any Bolt-compatible graph DB.

    Supports explicit ACID transactions via :class:`~runic.ogm.driver.TransactionalGraphDriver`.
    When no transaction is active, each ``execute()`` call opens its own Bolt
    session (auto-commit semantics).  Call ``begin()`` to start a transaction
    that spans multiple ``execute()`` calls, then ``commit()`` or ``rollback()``
    to end it.

    The OGM :class:`~runic.ogm.session.session.Session` drives this lifecycle
    automatically via lazy-begin: the first query inside a Session opens a
    transaction; ``Session.commit()`` / ``Session.rollback()`` close it.
    """

    def __init__(
        self,
        uri: str,
        auth: tuple[str, str],
        database: str,
        dialect: GraphDialect,
        *,
        encrypted: bool = True,
    ) -> None:
        import neo4j

        # NOTE: neo4j Python driver >= 5 removed the `encrypted=` kwarg; TLS is controlled by the URI scheme.
        if encrypted and uri.startswith("bolt://"):
            uri = uri.replace("bolt://", "bolt+s://", 1)
        elif not encrypted and uri.startswith(("bolt+s://", "bolt+ssc://")):
            uri = uri.replace("bolt+s://", "bolt://", 1).replace(
                "bolt+ssc://", "bolt://", 1
            )

        self._uri = uri
        self._auth = auth
        self._neo4j_driver = neo4j.GraphDatabase.driver(uri, auth=auth)
        self._database = database
        self._dialect = dialect
        # Active transaction state (None when outside a transaction)
        self._bolt_session: Any = None
        self._tx: Any = None

    @property
    def uri(self) -> str:
        return self._uri

    @property
    def auth(self) -> tuple[str, str]:
        return self._auth

    @property
    def dialect(self) -> GraphDialect:
        return self._dialect

    # ------------------------------------------------------------------
    # Transaction support (TransactionalGraphDriver)
    # ------------------------------------------------------------------

    def begin(self) -> None:
        """Open a Bolt session and begin an explicit transaction.

        Raises ``RuntimeError`` if a transaction is already active.
        """
        if self._tx is not None:
            raise RuntimeError(
                "BoltDriver: transaction already active; "
                "call commit() or rollback() before beginning a new one."
            )
        self._bolt_session = self._neo4j_driver.session(database=self._database)
        self._tx = self._bolt_session.begin_transaction()
        log.debug("BoltDriver: begun transaction")

    def commit(self) -> None:
        """Commit the active transaction and release the Bolt session.

        No-op when no transaction is active.
        """
        if self._tx is None:
            return
        try:
            self._tx.commit()
            log.debug("BoltDriver: transaction committed")
        finally:
            self._tx.close()
            self._tx = None
            if self._bolt_session is not None:
                self._bolt_session.close()
                self._bolt_session = None

    def rollback(self) -> None:
        """Roll back the active transaction and release the Bolt session.

        No-op when no transaction is active.
        """
        if self._tx is None:
            return
        try:
            self._tx.rollback()
            log.debug("BoltDriver: transaction rolled back")
        finally:
            self._tx.close()
            self._tx = None
            if self._bolt_session is not None:
                self._bolt_session.close()
                self._bolt_session = None

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, cypher: str, params: dict[str, Any]) -> BoltResult:
        if self._tx is not None:
            # Within an explicit transaction — use the active tx.
            result = self._tx.run(cypher, params)
            columns = list(result.keys())
            rows = [list(record.values()) for record in result]
            log.debug("BoltDriver executed (tx); %d row(s)", len(rows))
            return BoltResult(rows, columns)

        # No active transaction — open a per-query auto-commit session.
        with self._neo4j_driver.session(database=self._database) as session:
            result = session.run(cypher, params)  # ty: ignore[invalid-argument-type]
            columns = list(result.keys())
            rows = [list(record.values()) for record in result]
        log.debug("BoltDriver executed (auto); %d row(s)", len(rows))
        return BoltResult(rows, columns)

    def close(self) -> None:
        self._neo4j_driver.close()

    @classmethod
    def from_params(
        cls,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        dialect: GraphDialect,
        *,
        encrypted: bool = True,
    ) -> BoltDriver:
        uri = f"bolt://{host}:{port}"
        return cls(uri, (username, password), database, dialect, encrypted=encrypted)
