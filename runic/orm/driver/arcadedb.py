"""ArcadeDB dialect and driver factory.

ArcadeDB is accessed via the Bolt protocol using the ``neo4j`` Python driver
with ``encrypted=False``.  The only difference from a generic Bolt connection
is the ``ArcadeDBDialect`` strategy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runic.orm.driver.bolt import BoltDriver, BoltEdge, BoltNode

if TYPE_CHECKING:
    from runic.orm.core.descriptors import FieldInfo


class ArcadeDBNode(BoltNode):
    """BoltNode variant that corrects ArcadeDB's Bolt element_id offset.

    ArcadeDB's Bolt implementation sends ``element_id`` as 2× the value that
    the Cypher ``id()`` function returns.  Dividing by 2 realigns the stored
    primary-key with what ``WHERE id(n) = $pk`` expects.
    """

    @property
    def element_id(self) -> int:
        return int(self._raw.element_id) // 2


class ArcadeDBDialect:
    """Strategy for ArcadeDB-specific Cypher generation.

    Key differences from FalkorDB:
    - No ``toInteger()`` cast needed for ``id()``-based lookups
    - No ``vecf32()`` or ``intern()`` wrappers (raw values stored as-is)
    - Vector KNN via ``CALL vector.neighbors(...)``
    - Fulltext search not yet supported (raises ``NotImplementedError``)
    - ``SET n.prop = point()`` is not supported via Bolt; GeoLocation is stored as a ``{"latitude": x, "longitude": y}`` map instead.
    """

    supports_geo_update: bool = True

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def cypher_fn_for_field(self, fi: FieldInfo) -> str | None:  # noqa: ARG002
        # GeoLocation serialised as a plain map dict — no point() wrapper needed.
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:  # noqa: ARG002
        raise NotImplementedError(
            "ArcadeDB fulltext search via Cypher is not yet supported. "
            "Use ArcadeDB HTTP API or contribute a CALL procedure mapping."
        )

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,  # noqa: ARG002
        type_name: str,
        field_name: str,  # noqa: ARG002
    ) -> str:
        return (
            f"CALL vector.neighbors('{type_name}[{field_name}]', $__knn_vec, $__knn_k) "
            f"YIELD node AS {alias}, distance"
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        return "distance AS __score"

    def wrap_node(self, raw: Any) -> ArcadeDBNode:
        return ArcadeDBNode(raw)

    def wrap_edge(self, raw: Any) -> BoltEdge:
        return BoltEdge(raw)


_ARCADE_DIALECT = ArcadeDBDialect()


def create_arcadedb_driver(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
) -> BoltDriver:
    """Create a :class:`~runic.orm.driver.bolt.BoltDriver` configured for ArcadeDB."""
    return BoltDriver.from_params(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        dialect=_ARCADE_DIALECT,
        encrypted=False,
    )
