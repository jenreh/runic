"""Memgraph dialect and driver factory.

Memgraph is accessed via the Bolt protocol using the ``neo4j`` Python driver.
The dialect uses Memgraph's built-in ``text_search`` and ``vector_search``
modules for fulltext and vector KNN queries respectively.

Both fulltext and vector indexes must be **pre-created** with Cypher DDL before
use — pass a ``MemgraphAdapter`` to ``runic.migrate.IndexManager`` to create them.

Naming contract used by this dialect:

- **Fulltext**: index named ``{label}`` (e.g. ``CREATE TEXT INDEX Post ON :Post``).
- **Vector KNN**: index named ``{EntityClass}_{field}`` (e.g.
  ``CREATE VECTOR INDEX Article_embedding ON :Article(embedding)
  WITH CONFIG {"dimension": 1536, "capacity": 1000}``).

The vector score returned by ``vector_search.search`` is a ``distance`` (lower
value = more similar), which maps directly to ``__score`` and is ordered
``ASC`` by the QueryBuilder — the closest match appears first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runic.ogm.driver.bolt import BoltDriver, BoltEdge, BoltNode

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldInfo


class MemgraphDialect:
    """Strategy for Memgraph-specific Cypher generation.

    Key differences from Neo4j and FalkorDB:

    - Fulltext via ``CALL text_search.search_all(indexName, query)`` — uses
      Memgraph's built-in text search module (requires MAGE / built-in
      ``text_search``).  Index must be pre-created as
      ``CREATE TEXT INDEX {label} ON :{label}``.
    - Vector KNN via ``CALL vector_search.search(indexName, k, vec)`` —
      returns ``node``, ``distance``, and ``similarity`` columns.  Index must
      be pre-created as ``CREATE VECTOR INDEX {type}_{field} ON :{type}({field})
      WITH CONFIG {...}``.
    - Integer node IDs accessed via ``id()``, no ``toInteger()`` cast needed.
    - No Cypher function wrappers (``vecf32``, ``intern``) — raw values only.
    - TLS available via ``bolt+s://`` (pass ``encrypted=True`` to factory).
    """

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:
        from runic.ogm.core.types import GeoLocationConverter

        if isinstance(getattr(fi.field, "converter", None), GeoLocationConverter):
            return "point"
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:
        # Index must be pre-created as: CREATE TEXT INDEX {label} ON :{label}
        # text_search.search_all accepts plain text; no Lucene field prefix required.
        return (
            f"CALL text_search.search_all('{label}', ${query_param}) "
            f"YIELD node AS {alias}, score"
        )

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,  # noqa: ARG002
        type_name: str,
        field_name: str,
    ) -> str:
        # Index must be pre-created as:
        # CREATE VECTOR INDEX {type_name}_{field_name} ON :{type_name}({field_name}) WITH CONFIG {...}
        index_name = f"{type_name}_{field_name}"
        return (
            f"CALL vector_search.search('{index_name}', $__knn_k, $__knn_vec) "
            f"YIELD node AS {alias}, distance, similarity"
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        # Use distance as the score: lower = more similar, consistent with ASC ordering.
        return "distance AS __score"

    def wrap_node(self, raw: Any) -> BoltNode:
        return BoltNode(raw)

    def wrap_edge(self, raw: Any) -> BoltEdge:
        return BoltEdge(raw)


_MEMGRAPH_DIALECT = MemgraphDialect()


def create_memgraph_driver(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    *,
    encrypted: bool = False,
) -> BoltDriver:
    """Create a :class:`~runic.ogm.driver.bolt.BoltDriver` configured for Memgraph.

    Parameters
    ----------
    host:
        Memgraph host name or IP address.
    port:
        Bolt port (default ``7687``).
    database:
        Memgraph database name (typically ``"memgraph"``).
    username:
        Memgraph username.
    password:
        Memgraph password.
    encrypted:
        When ``True`` the driver connects over ``bolt+s://``.  Defaults to
        ``False`` since Memgraph is commonly run without TLS in development;
        set to ``True`` for production deployments.
    """
    return BoltDriver.from_params(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        dialect=_MEMGRAPH_DIALECT,
        encrypted=encrypted,
    )
