"""Apache AGE driver, dialect, and result wrappers.

Apache AGE is a PostgreSQL extension that adds graph database capabilities
and supports openCypher queries.  Cypher is executed via the ``cypher()``
SQL function:

    SELECT * FROM cypher('graph', $$ CYPHER $$ [, params::agtype])
        AS (col0 agtype, ...);

This driver uses ``psycopg`` (psycopg3) for the PostgreSQL connection.
Parameters are serialised as a JSON / agtype map and passed as the third
argument to ``cypher()``, which makes them available inside the Cypher
query as ``$param_name`` references (identical to the runic ORM's ``$p0``
convention).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.orm.core.descriptors import FieldInfo

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agtype data structures
# ---------------------------------------------------------------------------


class _AGEVertexData:
    """Internal parsed agtype vertex."""

    __slots__ = ("id", "label", "properties")

    def __init__(self, id: Any, label: str, properties: dict[str, Any]) -> None:  # noqa: A002
        self.id = id
        self.label = label
        self.properties = properties


class _AGEEdgeData:
    """Internal parsed agtype edge."""

    __slots__ = ("end_id", "id", "label", "properties", "start_id")

    def __init__(
        self,
        id: Any,  # noqa: A002
        label: str,
        start_id: Any,
        end_id: Any,
        properties: dict[str, Any],
    ) -> None:
        self.id = id
        self.label = label
        self.start_id = start_id
        self.end_id = end_id
        self.properties = properties


def _parse_agtype(text: str) -> Any:
    """Parse an AGE agtype string representation into a Python value.

    Vertices arrive as ``{...}::vertex``, edges as ``{...}::edge``;
    arrays as ``[elem1, elem2, ...]`` (elements may carry their own ``::type``);
    plain scalars/maps are valid JSON.
    """
    text = text.strip()

    # AGE arrays: [elem1::vertex, elem2::vertex, ...]
    if text.startswith("["):
        inner = text[1:-1] if text.endswith("]") else text[1:]
        inner = inner.strip()
        if not inner:
            return []
        return [
            _parse_agtype(e.strip())
            for e in _split_agtype_array_elements(inner)
            if e.strip()
        ]

    if "::" in text:
        json_part, _, type_tag = text.rpartition("::")
        json_part = json_part.strip()
        if type_tag == "vertex":
            data: dict[str, Any] = json.loads(json_part)
            return _AGEVertexData(
                id=data.get("id"),
                label=data.get("label", ""),
                properties=data.get("properties") or {},
            )
        if type_tag == "edge":
            data = json.loads(json_part)
            return _AGEEdgeData(
                id=data.get("id"),
                label=data.get("label", ""),
                start_id=data.get("start_id"),
                end_id=data.get("end_id"),
                properties=data.get("properties") or {},
            )
        # Unknown typed literal — return decoded JSON body
        return json.loads(json_part)
    return json.loads(text)


def _serialize_param(val: Any) -> Any:
    """JSON serialiser for types that json.dumps() does not handle natively."""
    from datetime import datetime
    from enum import Enum

    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Enum):
        return val.value
    raise TypeError(f"Cannot serialise {type(val).__name__!r} to agtype")


# ---------------------------------------------------------------------------
# GraphNode / GraphEdge wrappers
# ---------------------------------------------------------------------------


class AGENode:
    """Wraps an :class:`_AGEVertexData` to conform to ``GraphNode``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: _AGEVertexData) -> None:
        self._raw = raw

    @property
    def element_id(self) -> Any:
        return self._raw.id

    @property
    def labels(self) -> list[str]:
        stored = self._raw.properties.get("_labels")
        return stored if isinstance(stored, list) else [self._raw.label]

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw.properties)


class AGEEdge:
    """Wraps an :class:`_AGEEdgeData` to conform to ``GraphEdge``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: _AGEEdgeData) -> None:
        self._raw = raw

    @property
    def type(self) -> str:
        return self._raw.label

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw.properties)


# ---------------------------------------------------------------------------
# GraphResult wrapper
# ---------------------------------------------------------------------------


class AGEResult:
    """Eagerly-collected AGE query result conforming to ``GraphResult``."""

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


# ---------------------------------------------------------------------------
# RETURN-clause parser (builds the AGE AS (...) column list)
# ---------------------------------------------------------------------------


def _split_at_top_level_commas(expr: str) -> list[str]:
    """Split *expr* by commas, ignoring commas inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in expr:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _split_agtype_array_elements(text: str) -> list[str]:
    """Split agtype array content by top-level commas.

    Unlike :func:`_split_at_top_level_commas`, this function tracks all bracket
    types (``{}``, ``[]``, ``()``) and quoted strings so it correctly splits
    agtype arrays of vertices/edges that contain nested JSON objects.
    """
    parts: list[str] = []
    depth = 0
    in_string = False
    escape_next = False
    current: list[str] = []

    for ch in text:
        if escape_next:
            current.append(ch)
            escape_next = False
        elif in_string:
            if ch == "\\":
                current.append(ch)
                escape_next = True
            elif ch == '"':
                current.append(ch)
                in_string = False
            else:
                current.append(ch)
        elif ch == '"':
            current.append(ch)
            in_string = True
        elif ch in "{[(":
            depth += 1
            current.append(ch)
        elif ch in "}])":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current))
    return parts


def _parse_return_columns(cypher: str) -> list[str]:
    """Extract SQL column names from the Cypher RETURN clause.

    Used to build ``AS (col0 agtype, ...)`` for the AGE ``cypher()`` call.
    Handles: simple alias (``RETURN n``), multi-alias (``RETURN n, m``),
    property projections (``RETURN n.name``), aggregation AS aliases
    (``RETURN count(*) AS cnt``), DISTINCT, and inline RETURN on the same
    line as the preceding clause.
    """
    # Search each line in reverse for the last RETURN keyword.
    # Using re.search (not re.match) so that inline "... RETURN n" is found
    # even when RETURN is not at the start of the line.
    lines = cypher.splitlines()
    return_expr = ""
    for line in reversed(lines):
        stripped = line.strip()
        m = re.search(r"\bRETURN\s+(.*)", stripped, re.IGNORECASE)
        if m:
            return_expr = m.group(1).strip()
            break

    if not return_expr:
        return ["result"]

    # Strip trailing ORDER BY / SKIP / LIMIT / UNION clauses before parsing columns.
    return_expr = re.split(
        r"\bORDER\s+BY\b|\bSKIP\b|\bLIMIT\b|\bUNION\b", return_expr, flags=re.IGNORECASE
    )[0].rstrip()

    # Strip DISTINCT keyword
    return_expr = re.sub(r"^DISTINCT\s+", "", return_expr, flags=re.IGNORECASE)

    cols: list[str] = []
    for i, item in enumerate(_split_at_top_level_commas(return_expr)):
        item = item.strip()
        # Explicit AS alias: "expr AS alias"
        as_m = re.search(r"\bAS\s+(\w+)\s*$", item, re.IGNORECASE)
        if as_m:
            cols.append(as_m.group(1))
            continue
        # Property access: "n.prop"
        dot_m = re.match(r"^\w+\.(\w+)$", item)
        if dot_m:
            cols.append(dot_m.group(1))
            continue
        # Simple identifier: "n"
        id_m = re.match(r"^(\w+)$", item)
        if id_m:
            cols.append(id_m.group(1))
            continue
        # Fallback: positional name
        cols.append(f"col{i}")

    return cols or ["result"]


# ---------------------------------------------------------------------------
# AGE connection setup helpers
# ---------------------------------------------------------------------------


def _setup_age_connection(conn: Any, graph_name: str) -> None:
    """Load AGE, configure search_path, and register the agtype type adapter."""
    from psycopg.adapt import Loader

    class _AgtypeLoader(Loader):
        def load(self, data: bytes | bytearray | memoryview) -> Any:
            text = (
                bytes(data).decode("utf-8")
                if isinstance(data, memoryview)
                else data.decode("utf-8")
            )
            return _parse_agtype(text)

    with conn.cursor() as cur:
        cur.execute("LOAD 'age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
        # Fetch the agtype OID and register a loader so psycopg decodes it.
        cur.execute("SELECT oid FROM pg_type WHERE typname = 'agtype'")
        row = cur.fetchone()
        if row:
            agtype_oid: int = row[0]
            conn.adapters.register_loader(agtype_oid, _AgtypeLoader)
        # Ensure the graph exists (AGE raises if it does not).
        cur.execute(
            "SELECT count(*) FROM ag_graph WHERE name = %s",
            (graph_name,),
        )
        result = cur.fetchone()
        if result and result[0] == 0:
            cur.execute(
                "SELECT * FROM create_graph(%s)",
                (graph_name,),
            )
            log.info("AGEDriver: created graph %r", graph_name)
    conn.commit()


# ---------------------------------------------------------------------------
# Dialect
# ---------------------------------------------------------------------------


class AGEDialect:
    """Strategy for Apache AGE-specific Cypher generation.

    Key differences from FalkorDB:
    - No ``toInteger()`` cast for ``id()``-based lookups
    - No ``vecf32()`` or ``intern()`` wrappers (raw Python values stored as-is)
    - Fulltext search: not supported natively (raises ``NotImplementedError``)
    - Vector KNN: not supported natively (raises ``NotImplementedError``)
    - Multi-label emulation: extra labels stored as ``_labels`` property array
    """

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def labels_clause(self, labels: list[str]) -> str:
        """AGE only supports one label per vertex — use the primary label."""
        return labels[0]

    def subtype_where(self, alias: str, labels: list[str]) -> str | None:
        """Return a WHERE condition filtering by emulated subtype labels."""
        if len(labels) > 1:
            return " AND ".join(f'"{lbl}" IN {alias}._labels' for lbl in labels[1:])
        return None

    def needs_labels_property(self) -> bool:
        """Signal to the mapper to inject ``_labels`` on CREATE for subtypes."""
        return True

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:  # noqa: ARG002
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Apache AGE does not support native Cypher fulltext search. "
            "Use PostgreSQL full-text search on the underlying tables instead."
        )

    def vector_knn_start(
        self,
        alias: str,  # noqa: ARG002
        labels_str: str,  # noqa: ARG002
        type_name: str,  # noqa: ARG002
        field_name: str,  # noqa: ARG002
    ) -> str:
        raise NotImplementedError(
            "Apache AGE does not support native Cypher vector KNN search. "
            "Use pgvector on the underlying PostgreSQL tables instead."
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Apache AGE does not support native Cypher vector KNN search."
        )

    def wrap_node(self, raw: Any) -> AGENode:
        return AGENode(raw)

    def wrap_edge(self, raw: Any) -> AGEEdge:
        return AGEEdge(raw)


_AGE_DIALECT = AGEDialect()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class AGEDriver:
    """Sync driver for Apache AGE (PostgreSQL graph extension).

    Cypher queries are wrapped in the AGE ``cypher()`` SQL function and
    executed via a ``psycopg`` (psycopg3) connection.  Parameters are
    serialised as an agtype JSON map and passed as the third argument to
    ``cypher()``, making them accessible inside Cypher as ``$param_name``.

    Supports explicit ACID transactions via
    :class:`~runic.orm.driver.TransactionalGraphDriver`.  psycopg3 starts an
    implicit ``BEGIN`` on the first statement after each commit/rollback
    (``autocommit=False`` default); this driver's ``commit()`` / ``rollback()``
    map directly to ``conn.commit()`` / ``conn.rollback()``.  ``begin()`` is a
    documented no-op because psycopg3 manages the implicit transaction start
    automatically.

    The ORM :class:`~runic.orm.session.session.Session` drives this lifecycle:
    the first query in a Session opens a transaction implicitly; ``commit()`` /
    ``rollback()`` finalise it.

    AGE stores each vertex label as a separate PostgreSQL table; a vertex
    belongs to exactly one label fixed at creation time.  Multi-label
    operations (``SET n:New REMOVE n:Old``) are therefore not supported.

    Example
    -------
    ::

        driver = create_age_driver(
            host="localhost",
            port=5432,
            database="postgres",
            graph="my_graph",
            username="postgres",
            password="secret",
        )
        with Session(driver) as session:
            ...
    """

    supports_multi_label: bool = True

    def __init__(self, conn: Any, graph_name: str) -> None:
        self._conn = conn
        self._graph_name = graph_name

    @property
    def dialect(self) -> AGEDialect:
        return _AGE_DIALECT

    # ------------------------------------------------------------------
    # Transaction support (TransactionalGraphDriver)
    # ------------------------------------------------------------------

    def begin(self) -> None:
        """No-op: psycopg3 starts an implicit BEGIN on the first statement.

        Exists to satisfy the :class:`~runic.orm.driver.TransactionalGraphDriver`
        protocol so the ORM Session can detect transaction support via
        ``isinstance`` checks.
        """

    def commit(self) -> None:
        """Commit the active PostgreSQL transaction."""
        self._conn.commit()
        log.debug("AGEDriver: transaction committed on graph %r", self._graph_name)

    def rollback(self) -> None:
        """Roll back the active PostgreSQL transaction."""
        self._conn.rollback()
        log.debug("AGEDriver: transaction rolled back on graph %r", self._graph_name)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, cypher: str, params: dict[str, Any]) -> AGEResult:
        cols = _parse_return_columns(cypher)
        as_clause = ", ".join(f"{c} agtype" for c in cols)

        with self._conn.cursor() as cur:
            if params:
                params_json = json.dumps(params, default=_serialize_param)
                sql = (
                    f"SELECT * FROM cypher('{self._graph_name}', "  # noqa: S608
                    f"$age_q$ {cypher} $age_q$, "
                    f"%s::agtype) AS ({as_clause})"
                )
                cur.execute(sql, (params_json,))
            else:
                sql = (
                    f"SELECT * FROM cypher('{self._graph_name}', "  # noqa: S608
                    f"$age_q$ {cypher} $age_q$) AS ({as_clause})"
                )
                cur.execute(sql)

            columns = [d.name for d in (cur.description or [])]
            rows = [list(r) for r in cur.fetchall()]

        log.debug(
            "AGEDriver executed Cypher on %r; %d row(s)", self._graph_name, len(rows)
        )
        return AGEResult(rows, columns)

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_age_driver(
    host: str,
    port: int,
    database: str,
    graph: str,
    username: str,
    password: str,
) -> AGEDriver:
    """Create an :class:`AGEDriver` connected to a PostgreSQL+AGE instance.

    Parameters
    ----------
    host:
        PostgreSQL host name or IP address.
    port:
        PostgreSQL port (default is 5432).
    database:
        PostgreSQL database name.
    graph:
        AGE graph name within the database.
    username:
        PostgreSQL user name.
    password:
        PostgreSQL password.
    """
    import psycopg

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=username,
        password=password,
    )
    _setup_age_connection(conn, graph)
    return AGEDriver(conn, graph)
