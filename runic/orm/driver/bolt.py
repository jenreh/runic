"""BoltDriver for neo4j-compatible databases (ArcadeDB, Neo4j) via neo4j Python driver."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.orm.driver import GraphDialect

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
    """Sync Bolt driver for ArcadeDB, Neo4j, or any Bolt-compatible graph DB."""

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

        self._uri = uri
        self._auth = auth
        self._neo4j_driver = neo4j.GraphDatabase.driver(
            uri, auth=auth, encrypted=encrypted
        )
        self._database = database
        self._dialect = dialect

    @property
    def uri(self) -> str:
        return self._uri

    @property
    def auth(self) -> tuple[str, str]:
        return self._auth

    @property
    def dialect(self) -> GraphDialect:
        return self._dialect

    def execute(self, cypher: str, params: dict[str, Any]) -> BoltResult:
        with self._neo4j_driver.session(database=self._database) as session:
            result = session.run(cypher, params)  # ty: ignore[invalid-argument-type]
            columns = list(result.keys())
            rows = [list(record.values()) for record in result]
        log.debug("BoltDriver executed query; %d row(s) returned", len(rows))
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
