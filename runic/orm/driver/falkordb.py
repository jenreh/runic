"""FalkorDB driver, dialect, and result wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.orm.core.descriptors import FieldInfo


class FalkorDBNode:
    """Wraps a ``falkordb.Node`` to conform to ``GraphNode``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def element_id(self) -> Any:
        return self._raw.id

    @property
    def labels(self) -> list[str]:
        return list(self._raw.labels)

    @property
    def properties(self) -> dict[str, Any]:
        return self._raw.properties


class FalkorDBEdge:
    """Wraps a ``falkordb.Edge`` to conform to ``GraphEdge``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def type(self) -> str:
        return self._raw.type

    @property
    def properties(self) -> dict[str, Any]:
        return self._raw.properties


class FalkorDBResult:
    """Wraps a ``falkordb.QueryResult`` to conform to ``GraphResult``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def rows(self) -> list[list[Any]]:
        return self._raw.result_set

    @property
    def columns(self) -> list[str]:
        header = getattr(self._raw, "header", None) or []
        cols: list[str] = []
        for col in header:
            if isinstance(col, (list, tuple)) and len(col) >= 2:
                cols.append(str(col[1]))
            else:
                cols.append(str(col))
        return cols


class FalkorDBDialect:
    """Strategy implementation for FalkorDB-specific Cypher generation."""

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = toInteger(${param})"

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:
        if fi.field.converter is not None:
            fn = getattr(fi.field.converter, "cypher_fn", None)
            if fn:
                return fn
        if fi.field.interned:
            return "intern"
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:
        return (
            f"CALL db.idx.fulltext.queryNodes('{label}', ${query_param}) "
            f"YIELD node AS {alias}"
        )

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,
        type_name: str,  # noqa: ARG002
        field_name: str,  # noqa: ARG002
    ) -> str:
        return f"MATCH ({alias}:{labels_str})"

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:
        return f"vecf32({alias}.{field_name}) <-> vecf32($__knn_vec) AS __score"

    def wrap_node(self, raw: Any) -> FalkorDBNode:
        return FalkorDBNode(raw)

    def wrap_edge(self, raw: Any) -> FalkorDBEdge:
        return FalkorDBEdge(raw)


_DIALECT = FalkorDBDialect()


class FalkorDBDriver:
    """Sync driver wrapping a FalkorDB graph handle."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def falkordb_connection(self) -> tuple[Any, Any]:
        """Return (db, graph) for use by the FalkorDB migration adapter."""
        return self._graph.connection, self._graph

    @property
    def dialect(self) -> FalkorDBDialect:
        return _DIALECT

    def execute(self, cypher: str, params: dict[str, Any]) -> FalkorDBResult:
        return FalkorDBResult(self._graph.query(cypher, params))

    def close(self) -> None:
        pass


class AsyncFalkorDBDriver:
    """Async driver wrapping an async FalkorDB graph handle."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    @property
    def dialect(self) -> FalkorDBDialect:
        return _DIALECT

    async def execute(self, cypher: str, params: dict[str, Any]) -> FalkorDBResult:
        return FalkorDBResult(await self._graph.query(cypher, params))

    async def close(self) -> None:
        pass


def create_falkordb_driver(host: str, port: int, graph: str) -> FalkorDBDriver:
    """Create a :class:`FalkorDBDriver` from connection parameters.

    Parameters
    ----------
    host:
        FalkorDB host name or IP address.
    port:
        FalkorDB port (default Redis port is 6379).
    graph:
        Name of the graph to select.
    """
    from falkordb import FalkorDB

    db = FalkorDB(host=host, port=port)
    return FalkorDBDriver(db.select_graph(graph))
