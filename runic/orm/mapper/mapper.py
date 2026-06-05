"""Mapper: encodes ORM entities to Cypher parameters and decodes QueryResult rows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.orm.core.descriptors import FieldInfo
from runic.orm.core.metadata import MetaData, NodeMeta
from runic.orm.exceptions import MetadataError

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class Mapper:
    """Translates between ORM entity instances and FalkorDB Cypher queries/results.

    Reads ``_new`` and ``_dirty`` flags to decide which Cypher operation to emit.
    Decodes ``falkordb.Node`` objects back to ORM instances.  Private: composed
    by Session and Repository, never used directly by application code.
    """

    def __init__(self, meta: MetaData) -> None:
        self._meta = meta

    # ------------------------------------------------------------------
    # Query builders
    # ------------------------------------------------------------------

    def build_create_query(self, entity: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a CREATE statement."""
        cls = type(entity)
        node_meta = self._require_node_meta(cls)
        labels_str = ":".join(node_meta.labels)
        generated = self._is_generated_pk(node_meta)
        props = self._encode_props(entity, node_meta, include_pk=not generated)

        if props:
            param_str = ", ".join(f"{k}: ${k}" for k in props)
            cypher = f"CREATE (n:{labels_str} {{{param_str}}}) RETURN n"
        else:
            cypher = f"CREATE (n:{labels_str}) RETURN n"

        return cypher, props

    def build_update_query(self, entity: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a MATCH … SET statement."""
        cls = type(entity)
        node_meta = self._require_node_meta(cls)
        generated = self._is_generated_pk(node_meta)
        pk_val = self._get_pk_value(entity, node_meta)
        props = self._encode_props(entity, node_meta, include_pk=False)

        if not props:
            return "", {}

        set_str = ", ".join(f"n.{k} = ${k}" for k in props)
        params: dict[str, Any] = {"__pk": pk_val, **props}

        if generated:
            cypher = (
                f"MATCH (n:{node_meta.primary_label}) "
                f"WHERE id(n) = toInteger($__pk) "
                f"SET {set_str} RETURN n"
            )
        else:
            pk_name = node_meta.pk_field_name
            cypher = (
                f"MATCH (n:{node_meta.primary_label} {{{pk_name}: $__pk}}) "
                f"SET {set_str} RETURN n"
            )

        return cypher, params

    def build_delete_query(self, entity: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a DETACH DELETE statement."""
        cls = type(entity)
        node_meta = self._require_node_meta(cls)
        generated = self._is_generated_pk(node_meta)
        pk_val = self._get_pk_value(entity, node_meta)

        if generated:
            cypher = (
                f"MATCH (n:{node_meta.primary_label}) "
                f"WHERE id(n) = toInteger($__pk) DETACH DELETE n"
            )
        else:
            pk_name = node_meta.pk_field_name
            cypher = (
                f"MATCH (n:{node_meta.primary_label} {{{pk_name}: $__pk}}) "
                f"DETACH DELETE n"
            )

        return cypher, {"__pk": pk_val}

    def build_get_query(self, cls: type, pk: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a single-entity MATCH by primary key."""
        node_meta = self._require_node_meta(cls)
        generated = self._is_generated_pk(node_meta)
        labels_str = ":".join(node_meta.labels)

        if generated:
            cypher = f"MATCH (n:{labels_str}) WHERE id(n) = toInteger($__pk) RETURN n"
        else:
            pk_name = node_meta.pk_field_name
            cypher = f"MATCH (n:{labels_str} {{{pk_name}: $__pk}}) RETURN n"

        return cypher, {"__pk": pk}

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def decode_node(self, falkor_node: Any, hint_cls: type | None = None) -> Any:
        """Decode a ``falkordb.Node`` to an ORM entity instance."""
        target_cls = self._resolve_cls(falkor_node, hint_cls)
        node_meta = self._require_node_meta(target_cls)

        instance = object.__new__(target_cls)
        instance.__dict__["_new"] = False
        instance.__dict__["_dirty"] = False
        instance.__dict__["_expired"] = False

        for fi in node_meta.fields:
            if fi.field.relationship is not None:
                continue
            self._decode_field(instance, fi, falkor_node.properties)

        if node_meta.pk_field_name:
            pk_fi = self._find_field(node_meta.fields, node_meta.pk_field_name)
            if pk_fi is not None and pk_fi.field.generated:
                instance.__dict__[node_meta.pk_field_name] = falkor_node.id

        log.debug("Decoded node as %s", target_cls.__name__)
        return instance

    def update_entity_from_node(self, entity: Any, falkor_node: Any) -> None:
        """Update an existing entity in-place from a FalkorDB node."""
        cls = type(entity)
        node_meta = self._require_node_meta(cls)

        for fi in node_meta.fields:
            if fi.field.relationship is not None:
                continue
            self._decode_field(entity, fi, falkor_node.properties)

        if node_meta.pk_field_name:
            pk_fi = self._find_field(node_meta.fields, node_meta.pk_field_name)
            if pk_fi is not None and pk_fi.field.generated:
                entity.__dict__[node_meta.pk_field_name] = falkor_node.id

        entity.__dict__["_dirty"] = False
        entity.__dict__["_expired"] = False

    def get_pk_value(self, entity: Any) -> Any:
        """Return the primary key value of an entity."""
        node_meta = self._require_node_meta(type(entity))
        return self._get_pk_value(entity, node_meta)

    def get_pk_field_name(self, cls: type) -> str | None:
        """Return the primary key field name for the given Node class."""
        node_meta = self._require_node_meta(cls)
        return node_meta.pk_field_name

    def is_generated_pk(self, cls: type) -> bool:
        """True if the Node class uses a FalkorDB-generated primary key."""
        node_meta = self._require_node_meta(cls)
        return self._is_generated_pk(node_meta)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_node_meta(self, cls: type) -> NodeMeta:
        meta = self._meta.get_node_meta(cls)
        if meta is None:
            raise MetadataError(
                f"Class {cls.__name__!r} is not a registered Node subclass"
            )
        return meta

    def _is_generated_pk(self, node_meta: NodeMeta) -> bool:
        if node_meta.pk_field_name is None:
            return False
        pk_fi = self._find_field(node_meta.fields, node_meta.pk_field_name)
        return pk_fi is not None and pk_fi.field.generated

    def _get_pk_value(self, entity: Any, node_meta: NodeMeta) -> Any:
        if node_meta.pk_field_name is None:
            return None
        return entity.__dict__.get(node_meta.pk_field_name)

    def _encode_props(
        self,
        entity: Any,
        node_meta: NodeMeta,
        include_pk: bool = True,
    ) -> dict[str, Any]:
        """Encode entity field values to a Cypher-parameter dict."""
        props: dict[str, Any] = {}
        pk_name = node_meta.pk_field_name

        for fi in node_meta.fields:
            if fi.field.relationship is not None:
                continue
            if not include_pk and fi.name == pk_name:
                continue

            val = entity.__dict__.get(fi.name)
            if val is None and fi.field.has_default:
                val = fi.field.get_default()
            if val is None:
                continue

            if fi.field.converter is not None:
                val = fi.field.converter.to_graph(val)
            props[fi.name] = val

        return props

    def _resolve_cls(self, falkor_node: Any, hint_cls: type | None) -> type:
        """Find the most specific registered ORM class matching a FalkorDB node."""
        node_labels = set(falkor_node.labels or [])

        # Exact label-set match takes priority
        for meta in self._meta.all_nodes():
            if set(meta.labels) == node_labels:
                return meta.cls

        # Fall back to the caller's hint
        if hint_cls is not None:
            return hint_cls

        # Best subset match (most specific)
        best_cls: type | None = None
        best_size = 0
        for meta in self._meta.all_nodes():
            meta_labels = set(meta.labels)
            if meta_labels.issubset(node_labels) and len(meta_labels) > best_size:
                best_cls = meta.cls
                best_size = len(meta_labels)

        if best_cls is not None:
            return best_cls

        raise MetadataError(f"No ORM class registered for labels {list(node_labels)!r}")

    def _decode_field(
        self, instance: Any, fi: FieldInfo, props: dict[str, Any]
    ) -> None:
        if fi.name in props:
            val = props[fi.name]
            if fi.field.converter is not None:
                val = fi.field.converter.from_graph(val)
            instance.__dict__[fi.name] = val
        elif fi.field.has_default:
            instance.__dict__[fi.name] = fi.field.get_default()

    @staticmethod
    def _find_field(fields: list[FieldInfo], name: str) -> FieldInfo | None:
        return next((fi for fi in fields if fi.name == name), None)
