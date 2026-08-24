"""Amazon Neptune Analytics dialect and driver.

Neptune Analytics has no Bolt endpoint — queries go over HTTPS through the
``neptune-graph`` AWS API (``boto3`` client, ``execute_query``), which is
always SigV4-authenticated by boto3 itself.  Results arrive as JSON: rows are
objects keyed by RETURN alias, with nodes and relationships serialised as
``{"~id", "~entityType", "~labels"/"~type", "~properties"}`` documents.

Vector similarity is native (``CALL neptune.algo.vectors.topK.byEmbedding``),
but embeddings live in the graph's **single vector index** (dimension fixed at
graph creation), *not* in node properties.  Session-managed writes of runic
``Vector`` model fields therefore append ``CALL neptune.algo.vectors.upsert``
to the same statement automatically (see
:meth:`NeptuneAnalyticsDialect.vector_sync_clause`), keeping the index in
sync.  Pass ``sync_vectors=False`` to the driver for graphs created without a
vector index, and use :meth:`NeptuneAnalyticsDriver.upsert_vector` for
embeddings written outside the Session (raw Cypher, bulk loads).

Implemented against AWS's documented behaviour (2026-08) but **not yet
live-verified** — Neptune Analytics has no local emulator.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from runic.cypher import UNIVERSAL_RESERVED_VARIABLES
from runic.ogm.driver import CypherFeature, yield_as

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldInfo

log = logging.getLogger(__name__)


def _serialize_param(val: Any) -> Any:
    """JSON serialiser for types that json.dumps() does not handle natively."""
    from datetime import datetime
    from enum import Enum

    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, Enum):
        return val.value
    raise TypeError(f"Cannot serialise {type(val).__name__!r} for Neptune Analytics")


def _jsonable_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return *params* with datetime/Enum values reduced to JSON-native types."""
    return json.loads(json.dumps(params, default=_serialize_param))


# ---------------------------------------------------------------------------
# GraphNode / GraphEdge / GraphResult wrappers
# ---------------------------------------------------------------------------


class NeptuneAnalyticsNode:
    """Wraps a ``{"~id", "~labels", "~properties"}`` document as ``GraphNode``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    @property
    def element_id(self) -> str:
        return str(self._raw.get("~id", ""))

    @property
    def labels(self) -> list[str]:
        return [str(label) for label in self._raw.get("~labels") or []]

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw.get("~properties") or {})


class NeptuneAnalyticsEdge:
    """Wraps a ``{"~type", "~properties"}`` document as ``GraphEdge``."""

    __slots__ = ("_raw",)

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    @property
    def type(self) -> str:
        return str(self._raw.get("~type", ""))

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self._raw.get("~properties") or {})


class NeptuneAnalyticsResult:
    """Eagerly-collected Neptune Analytics result conforming to ``GraphResult``."""

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
# Dialect
# ---------------------------------------------------------------------------


class NeptuneAnalyticsDialect:
    """Strategy for Amazon Neptune Analytics-specific Cypher generation.

    Key differences from Neptune Database:

    - ``CALL … YIELD`` works for the built-in ``neptune.algo.*`` procedures.
    - Native vector KNN via ``neptune.algo.vectors.topK.byEmbedding`` — one
      vector index per graph, so the runic field name is ignored and the label
      is applied as a ``vertexFilter``.  The yielded ``score`` is a squared
      Euclidean distance (lower = more similar), matching runic's ASC
      ``__score`` ordering.
    - Still no Cypher-level fulltext search.
    - ``id()`` returns strings; no Cypher function wrappers.
    - ``Vector`` field writes are auto-synced into the vector index via
      :meth:`vector_sync_clause` (disable with ``sync_vectors=False``).
    """

    reserved_variable_names: frozenset[str] = UNIVERSAL_RESERVED_VARIABLES
    """The boolean literals only — the empirical set is not yet live-verified;
    ``tests/runic/ogm/integration/test_reserved_variable_names.py`` re-derives
    it once a graph is reachable."""

    unsupported_features: frozenset[str] = frozenset({CypherFeature.FULLTEXT_SEARCH})

    def __init__(self, *, sync_vectors: bool = True) -> None:
        self._sync_vectors = sync_vectors

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def vector_sync_clause(
        self,
        alias: str,
        fi: FieldInfo,  # noqa: ARG002 - one index per graph; field is irrelevant
        param_ref: str,
    ) -> str | None:
        """Cypher fragment syncing a written vector into the graph's index.

        Embeddings live in the per-graph vector index, not in node
        properties, so the mapper appends this to CREATE/SET statements for
        every ``Vector`` field it writes — one statement, no second round
        trip.  The graph must have been created with a
        ``vectorSearchConfiguration`` whose dimension matches; returns
        ``None`` (no sync) when the dialect was built with
        ``sync_vectors=False``.
        """
        if not self._sync_vectors:
            return None
        return (
            f"WITH {alias} "
            f"CALL neptune.algo.vectors.upsert({alias}, {param_ref}) "
            f"YIELD success WITH {alias}"
        )

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:  # noqa: ARG002
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "Neptune Analytics does not support Cypher-level fulltext search."
        )

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,  # noqa: ARG002
        type_name: str,
        field_name: str,  # noqa: ARG002
    ) -> str:
        return (
            f"CALL neptune.algo.vectors.topK.byEmbedding("
            f"{{embedding: $__knn_vec, topK: $__knn_k, "
            f"vertexFilter: {{equals: {{property: '~label', value: '{type_name}'}}}}}}) "
            f"YIELD {yield_as('node', alias)}, score"
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        return "score AS __score"

    def vector_knn_call(
        self,
        alias: str,
        label: str,
        field_name: str,  # noqa: ARG002
        k_ref: str,
        vec_ref: str,
    ) -> str:
        # One vector index per graph: field_name has no equivalent, the label
        # narrows results via vertexFilter.
        return (
            f"CALL neptune.algo.vectors.topK.byEmbedding("
            f"{{embedding: {vec_ref}, topK: {k_ref}, "
            f"vertexFilter: {{equals: {{property: '~label', value: '{label}'}}}}}}) "
            f"YIELD {yield_as('node', alias)}, score"
        )

    def vector_score_expr(self) -> str:
        return "score"

    def fulltext_yields_score(self) -> bool:
        return False

    def wrap_node(self, raw: Any) -> NeptuneAnalyticsNode:
        return NeptuneAnalyticsNode(raw)

    def wrap_edge(self, raw: Any) -> NeptuneAnalyticsEdge:
        return NeptuneAnalyticsEdge(raw)


_NEPTUNE_ANALYTICS_DIALECT = NeptuneAnalyticsDialect()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class NeptuneAnalyticsDriver:
    """Sync driver for Amazon Neptune Analytics via the ``neptune-graph`` API.

    Each :meth:`execute` call is one ``ExecuteQuery`` request — individually
    atomic at the service level.  There is no explicit transaction API, so
    this driver (like FalkorDB's) does not implement
    :class:`~runic.ogm.driver.TransactionalGraphDriver`.
    """

    def __init__(
        self,
        graph_id: str,
        *,
        region: str | None = None,
        client: Any | None = None,
        sync_vectors: bool = True,
    ) -> None:
        if client is None:
            import boto3

            client = (
                boto3.client("neptune-graph", region_name=region)
                if region
                else boto3.client("neptune-graph")
            )
        self._client = client
        self._graph_id = graph_id
        # Session writes auto-upsert Vector fields into the vector index;
        # sync_vectors=False opts out for graphs created without one.
        self._dialect = (
            _NEPTUNE_ANALYTICS_DIALECT
            if sync_vectors
            else NeptuneAnalyticsDialect(sync_vectors=False)
        )

    @property
    def graph_id(self) -> str:
        return self._graph_id

    @property
    def dialect(self) -> NeptuneAnalyticsDialect:
        return self._dialect

    def execute(self, cypher: str, params: dict[str, Any]) -> NeptuneAnalyticsResult:
        request: dict[str, Any] = {
            "graphIdentifier": self._graph_id,
            "queryString": cypher,
            "language": "OPEN_CYPHER",
        }
        if params:
            request["parameters"] = _jsonable_params(params)
        response = self._client.execute_query(**request)
        payload = json.loads(response["payload"].read())
        results = payload.get("results") or []
        if not results:
            return NeptuneAnalyticsResult([], [])
        columns = list(results[0].keys())
        rows = [[row.get(column) for column in columns] for row in results]
        log.debug("NeptuneAnalyticsDriver executed; %d row(s)", len(rows))
        return NeptuneAnalyticsResult(rows, columns)

    def upsert_vector(self, node_id: str, embedding: list[float]) -> bool:
        """Register *embedding* for the node in the graph's vector index.

        Session-managed ``Vector`` field writes sync the index automatically;
        this is the manual escape hatch for embeddings written outside the
        Session (raw Cypher, bulk loads) or when the driver was built with
        ``sync_vectors=False``.  Returns whether the upsert reported success.
        """
        result = self.execute(
            "MATCH (n) WHERE id(n) = $__vec_id "
            "CALL neptune.algo.vectors.upsert(n, $__vec_embedding) "
            "YIELD success RETURN success",
            {"__vec_id": node_id, "__vec_embedding": list(embedding)},
        )
        return bool(result.rows and result.rows[0][0])

    def close(self) -> None:
        self._client.close()


def create_neptune_analytics_driver(
    graph_id: str,
    *,
    region: str | None = None,
    client: Any | None = None,
    sync_vectors: bool = True,
) -> NeptuneAnalyticsDriver:
    """Create a :class:`NeptuneAnalyticsDriver` for the given graph.

    Parameters
    ----------
    graph_id:
        The Neptune Analytics graph identifier (e.g. ``"g-abc123xyz"``).
    region:
        AWS region of the graph; defaults to the standard AWS config chain.
    client:
        Optional pre-built ``neptune-graph`` boto3 client (useful for custom
        sessions, assumed roles, or testing); *region* is ignored when given.
    sync_vectors:
        When ``True`` (default), Session writes of ``Vector`` model fields
        append ``CALL neptune.algo.vectors.upsert`` to the same statement so
        the graph's vector index stays in sync automatically.  Set to
        ``False`` for graphs created without a ``vectorSearchConfiguration``.
    """
    return NeptuneAnalyticsDriver(
        graph_id, region=region, client=client, sync_vectors=sync_vectors
    )
