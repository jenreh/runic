"""ArcadeDB dialect and driver factory.

ArcadeDB is accessed via the Bolt protocol using the ``neo4j`` Python driver
with ``encrypted=False``.  The only difference from a generic Bolt connection
is the ``ArcadeDBDialect`` strategy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runic.cypher import UNIVERSAL_RESERVED_VARIABLES
from runic.ogm.driver import CypherFeature, yield_as
from runic.ogm.driver.bolt import BoltDriver, BoltEdge, BoltNode

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldInfo


class ArcadeDBDialect:
    """Strategy for ArcadeDB-specific Cypher generation.

    Key differences from FalkorDB:
    - Engine-assigned ids are matched with ``elementId()``, never ``id()``
    - No ``vecf32()`` or ``intern()`` wrappers (raw values stored as-is)
    - Vector KNN via ``CALL vector.neighbors(...)``
    - Fulltext search not yet supported (raises ``NotImplementedError``)
    - ``SET n.prop = point()`` is not supported via Bolt; GeoLocation is stored as a ``{"latitude": x, "longitude": y}`` map instead.
    """

    reserved_variable_names: frozenset[str] = UNIVERSAL_RESERVED_VARIABLES
    """Only the boolean literals; every other keyword works as a variable here."""

    unsupported_features: frozenset[str] = frozenset(
        {CypherFeature.PROCEDURE_CALL, CypherFeature.FULLTEXT_SEARCH}
    )

    supports_geo_update: bool = False

    def generated_id_where(self, alias: str, param: str) -> str:
        """Match on the RID, which is what the Bolt layer hands back.

        ArcadeDB reports two different identifiers for the same vertex: Bolt
        sends the RID (``"#1:0"``) as ``element_id``, while Cypher ``id()``
        packs bucket and position into a long. The two use different shift
        widths (``BoltStructureMapper.ridToId`` vs ``IdFunction``), and the
        Cypher one is governed by a server setting, so a client that
        reconstructs it is guessing. ``elementId()`` compares the RID runic
        actually holds.
        """
        return f"WHERE elementId({alias}) = ${param}"

    def generated_ids_where(
        self, alias: str, pks: list[Any]
    ) -> tuple[str, dict[str, Any]]:
        """Return the batch counterpart of :meth:`generated_id_where`."""
        return f"elementId({alias}) IN $__pks", {"__pks": pks}

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
            f"YIELD {yield_as('node', alias)}, distance"
        )

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        return "distance AS __score"

    def vector_knn_call(
        self, alias: str, label: str, field_name: str, k_ref: str, vec_ref: str
    ) -> str:
        return (
            f"CALL vector.neighbors('{label}[{field_name}]', {vec_ref}, {k_ref}) "
            f"YIELD {yield_as('node', alias)}, distance"
        )

    def vector_score_expr(self) -> str:
        return "distance"

    def fulltext_yields_score(self) -> bool:
        return False

    def wrap_node(self, raw: Any) -> BoltNode:
        return BoltNode(raw)

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
    """Create a :class:`~runic.ogm.driver.bolt.BoltDriver` configured for ArcadeDB."""
    return BoltDriver.from_params(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        dialect=_ARCADE_DIALECT,
        encrypted=False,
    )
