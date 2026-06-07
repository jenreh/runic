"""Neo4j dialect and driver factory.

Neo4j is accessed via the Bolt protocol using the ``neo4j`` Python driver.
The dialect targets Neo4j 5.x where ``db.index.fulltext.queryNodes`` and
``db.index.vector.queryNodes`` are the canonical fulltext/vector procedures.

Both fulltext and vector indexes must be **pre-created** with Cypher DDL before
use — the runic ``IndexManager`` is FalkorDB-specific and will not create them.

Naming contract used by this dialect:

- **Fulltext**: index named ``{label}`` (e.g. ``CREATE FULLTEXT INDEX Post FOR
  (n:Post) ON EACH [n.title, n.body]``).
- **Vector KNN**: index named ``{EntityClass}_{field}`` (e.g.
  ``CREATE VECTOR INDEX Article_embedding FOR (n:Article) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'}}``).

The vector score returned by Neo4j is cosine *similarity* (1.0 = identical).
The dialect maps it to ``(1.0 - score) AS __score`` so that the QueryBuilder's
``ORDER BY __score ASC`` still places the *most similar* nodes first, consistent
with FalkorDB and ArcadeDB drivers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runic.orm.driver.bolt import BoltDriver, BoltEdge, BoltNode

if TYPE_CHECKING:
    from runic.orm.core.descriptors import FieldInfo


class Neo4jDialect:
    """Strategy for Neo4j-specific Cypher generation.

    Key differences from FalkorDB and ArcadeDB:

    - Fulltext via ``CALL db.index.fulltext.queryNodes(indexName, query)``
      (requires a pre-created fulltext index named after the label).
    - Vector KNN via ``CALL db.index.vector.queryNodes(indexName, k, vec)``
      (requires a pre-created vector index named ``{type}_{field}``).
    - Integer node IDs accessed via ``id()``, no ``toInteger()`` cast needed.
    - No Cypher function wrappers (``vecf32``, ``intern``) — raw values only.
    - TLS available via ``bolt+s://`` (pass ``encrypted=True`` to factory).
    """

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:
        from runic.orm.core.types import GeoLocationConverter

        if isinstance(getattr(fi.field, "converter", None), GeoLocationConverter):
            return "point"
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:
        # Index must be pre-created as: CREATE FULLTEXT INDEX {label} FOR (n:{label}) ON EACH [...]
        return (
            f"CALL db.index.fulltext.queryNodes('{label}', ${query_param}) "
            f"YIELD node AS {alias}, score"
        )

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,  # noqa: ARG002
        type_name: str,
        field_name: str,
    ) -> str:
        # Index must be pre-created as: CREATE VECTOR INDEX {type_name}_{field_name} FOR (n:{type_name}) ON (n.{field_name})
        index_name = f"{type_name}_{field_name}"
        return (
            f"CALL db.index.vector.queryNodes('{index_name}', $__knn_k, $__knn_vec) "
            f"YIELD node AS {alias}, score"
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        # Neo4j returns cosine similarity (1.0=identical); invert to distance so
        # ORDER BY __score ASC still places the closest match first.
        return "(1.0 - score) AS __score"

    def wrap_node(self, raw: Any) -> BoltNode:
        return BoltNode(raw)

    def wrap_edge(self, raw: Any) -> BoltEdge:
        return BoltEdge(raw)


_NEO4J_DIALECT = Neo4jDialect()


def create_neo4j_driver(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    *,
    encrypted: bool = True,
) -> BoltDriver:
    """Create a :class:`~runic.orm.driver.bolt.BoltDriver` configured for Neo4j.

    Parameters
    ----------
    host:
        Neo4j host name or IP address.
    port:
        Bolt port (default ``7687``).
    database:
        Neo4j database name (default database is ``"neo4j"``).
    username:
        Neo4j username (default ``"neo4j"``).
    password:
        Neo4j password.
    encrypted:
        When ``True`` (default) the driver connects over ``bolt+s://``.
        Pass ``False`` for plaintext ``bolt://`` (e.g. local dev with no TLS).
    """
    return BoltDriver.from_params(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        dialect=_NEO4J_DIALECT,
        encrypted=encrypted,
    )
