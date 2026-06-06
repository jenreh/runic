"""Relationship mutation operations — MERGE and DELETE for ORM entity edges."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.orm.core.descriptors import FieldInfo
from runic.orm.core.metadata import MetaData, NodeMeta

if TYPE_CHECKING:
    from runic.orm.driver import GraphDialect
    from runic.orm.mapper.mapper import Mapper

log = logging.getLogger(__name__)


class RelationshipWriter:
    """Builds MERGE and DELETE Cypher queries for relationship mutations.

    Composed by Session and AsyncSession; never used directly by application code.
    """

    def __init__(self, meta: MetaData, mapper: Mapper) -> None:
        self._meta = meta
        self._mapper = mapper

    def build_relate_query(
        self,
        source: Any,
        fi: FieldInfo,
        target: Any,
        edge: Any | None,
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a MERGE relationship (create or update).

        Uses ``MERGE`` so calling ``relate()`` multiple times is idempotent.
        When *edge* is provided, its field values are written via ``SET`` after
        the merge, effectively upserting edge properties on every call.
        """
        src_meta = self._mapper.require_node_meta(type(source))
        tgt_meta = self._mapper.require_node_meta(type(target))

        src_pk = self._mapper.get_pk_value(source)
        tgt_pk = self._mapper.get_pk_value(target)
        src_gen = self._mapper.is_generated_pk(type(source))
        tgt_gen = self._mapper.is_generated_pk(type(target))

        rel_type = fi.field.relationship
        direction = fi.field.direction or "OUTGOING"

        dialect = self._mapper.dialect
        match_a = _node_match_clause("a", src_meta, "__src_pk", src_gen, dialect)
        match_b = _node_match_clause("b", tgt_meta, "__tgt_pk", tgt_gen, dialect)
        merge_rel = _rel_clause("MERGE", "a", "b", rel_type, direction, "r")

        params: dict[str, Any] = {"__src_pk": src_pk, "__tgt_pk": tgt_pk}
        clauses = [match_a, match_b, merge_rel]

        if edge is not None:
            edge_props = self._encode_edge_props(edge)
            if edge_props:
                set_parts = ", ".join(f"r.{k} = $__e_{k}" for k in edge_props)
                clauses.append(f"SET {set_parts}")
                params.update({f"__e_{k}": v for k, v in edge_props.items()})

        return "\n".join(clauses), params

    def build_unrelate_query(
        self,
        source: Any,
        fi: FieldInfo,
        target: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to DELETE a specific relationship."""
        src_meta = self._mapper.require_node_meta(type(source))
        tgt_meta = self._mapper.require_node_meta(type(target))

        src_pk = self._mapper.get_pk_value(source)
        tgt_pk = self._mapper.get_pk_value(target)
        src_gen = self._mapper.is_generated_pk(type(source))
        tgt_gen = self._mapper.is_generated_pk(type(target))

        rel_type = fi.field.relationship
        direction = fi.field.direction or "OUTGOING"

        dialect = self._mapper.dialect
        match_a = _node_match_clause("a", src_meta, "__src_pk", src_gen, dialect)
        match_b = _node_match_clause("b", tgt_meta, "__tgt_pk", tgt_gen, dialect)
        match_rel = _rel_clause("MATCH", "a", "b", rel_type, direction, "r")

        params: dict[str, Any] = {"__src_pk": src_pk, "__tgt_pk": tgt_pk}
        cypher = f"{match_a}\n{match_b}\n{match_rel}\nDELETE r"
        return cypher, params

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _encode_edge_props(self, edge: Any) -> dict[str, Any]:
        """Encode Edge model field values to a Cypher-parameter dict."""
        fields = getattr(type(edge), "_fields", None)
        if not fields:
            return {}

        props: dict[str, Any] = {}
        for fi in fields:
            val = edge.__dict__.get(fi.name)
            if val is None:
                continue
            if fi.field.converter is not None:
                val = fi.field.converter.to_graph(val)
            props[fi.name] = val
        return props


# ---------------------------------------------------------------------------
# Module-level Cypher helpers (stateless, reused in tests)
# ---------------------------------------------------------------------------


def _node_match_clause(
    alias: str,
    node_meta: NodeMeta,
    pk_param: str,
    generated: bool,
    dialect: GraphDialect | None = None,
) -> str:
    """Return a single ``MATCH`` clause for one node."""
    if generated:
        if dialect is not None:
            id_where = dialect.generated_id_where(alias, pk_param)
        else:
            id_where = f"WHERE id({alias}) = toInteger(${pk_param})"
        return f"MATCH ({alias}:{node_meta.primary_label}) {id_where}"
    pk_name = node_meta.pk_field_name or "id"
    return f"MATCH ({alias}:{node_meta.primary_label} {{{pk_name}: ${pk_param}}})"


def _rel_clause(
    verb: str,
    src: str,
    tgt: str,
    rel_type: str | None,
    direction: str,
    alias: str,
) -> str:
    """Return a ``MERGE`` or ``MATCH`` clause for a directed relationship."""
    if direction == "OUTGOING":
        return f"{verb} ({src})-[{alias}:{rel_type}]->({tgt})"
    if direction == "INCOMING":
        return f"{verb} ({src})<-[{alias}:{rel_type}]-({tgt})"
    return f"{verb} ({src})-[{alias}:{rel_type}]-({tgt})"
