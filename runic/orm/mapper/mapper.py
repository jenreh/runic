"""Mapper: encodes ORM entities to Cypher parameters and decodes QueryResult rows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.orm.core.descriptors import _NOT_LOADED, FieldInfo
from runic.orm.core.metadata import MetaData, NodeMeta
from runic.orm.exceptions import MetadataError

if TYPE_CHECKING:
    from runic.orm.driver import GraphDialect

log = logging.getLogger(__name__)


class Mapper:
    """Translates between ORM entity instances and FalkorDB Cypher queries/results.

    Reads ``_new`` and ``_dirty`` flags to decide which Cypher operation to emit.
    Decodes ``falkordb.Node`` objects back to ORM instances.  Private: composed
    by Session and Repository, never used directly by application code.
    """

    def __init__(self, meta: MetaData, dialect: GraphDialect | None = None) -> None:
        self._meta = meta
        if dialect is None:
            from runic.orm.driver.falkordb import FalkorDBDialect

            dialect = FalkorDBDialect()
        self._dialect = dialect

    # ------------------------------------------------------------------
    # Dialect helpers (optional dialect methods with safe defaults)
    # ------------------------------------------------------------------

    def labels_clause(self, labels: list[str]) -> str:
        """Return the Cypher label clause string for a MATCH/CREATE pattern."""
        fn = getattr(self._dialect, "labels_clause", None)
        return fn(labels) if fn else ":".join(labels)

    def subtype_where(self, alias: str, labels: list[str]) -> str | None:
        """Return an extra WHERE condition for subtype filtering, or None."""
        fn = getattr(self._dialect, "subtype_where", None)
        return fn(alias, labels) if fn else None

    # ------------------------------------------------------------------
    # Query builders
    # ------------------------------------------------------------------

    def build_create_query(self, entity: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a CREATE statement."""
        cls = type(entity)
        node_meta = self._require_node_meta(cls)
        labels_str = self.labels_clause(node_meta.labels)
        generated = self._is_generated_pk(node_meta)
        props = self._encode_props(entity, node_meta, include_pk=not generated)

        needs_labels_prop = getattr(
            self._dialect, "needs_labels_property", lambda: False
        )()
        if needs_labels_prop and len(node_meta.labels) > 1:
            props["_labels"] = node_meta.labels

        if props:
            param_str = ", ".join(
                f"{k}: {self._prop_ref(k, self._find_field(node_meta.fields, k))}"
                for k in props
            )
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

        set_str = ", ".join(
            f"n.{k} = {self._prop_ref(k, self._find_field(node_meta.fields, k))}"
            for k in props
        )
        params: dict[str, Any] = {"__pk": pk_val, **props}

        if generated:
            id_where = self._dialect.generated_id_where("n", "__pk")
            cypher = (
                f"MATCH (n:{node_meta.primary_label}) {id_where} SET {set_str} RETURN n"
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
            id_where = self._dialect.generated_id_where("n", "__pk")
            cypher = f"MATCH (n:{node_meta.primary_label}) {id_where} DETACH DELETE n"
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
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)

        if generated:
            id_where = self._dialect.generated_id_where("n", "__pk")
            if subtype_filter:
                id_where = f"WHERE {subtype_filter} AND {id_where[6:]}"
            cypher = f"MATCH (n:{labels_str}) {id_where} RETURN n"
        else:
            pk_name = node_meta.pk_field_name
            if subtype_filter:
                cypher = (
                    f"MATCH (n:{labels_str} {{{pk_name}: $__pk}}) "
                    f"WHERE {subtype_filter} RETURN n"
                )
            else:
                cypher = f"MATCH (n:{labels_str} {{{pk_name}: $__pk}}) RETURN n"

        return cypher, {"__pk": pk}

    def build_find_all_query(self, cls: type) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to MATCH all entities of *cls*."""
        node_meta = self._require_node_meta(cls)
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)
        where = f"WHERE {subtype_filter} " if subtype_filter else ""
        return f"MATCH (n:{labels_str}) {where}RETURN n", {}

    def build_find_all_by_ids_query(
        self, cls: type, pks: list[Any]
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to MATCH a batch of entities by primary key."""
        node_meta = self._require_node_meta(cls)
        generated = self._is_generated_pk(node_meta)
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)

        if generated:
            where = f"WHERE {subtype_filter} AND " if subtype_filter else "WHERE "
            cypher = f"MATCH (n:{labels_str}) {where}id(n) IN $__pks RETURN n"
        else:
            pk_name = node_meta.pk_field_name
            where = f"WHERE {subtype_filter} AND " if subtype_filter else "WHERE "
            cypher = f"MATCH (n:{labels_str}) {where}n.{pk_name} IN $__pks RETURN n"

        return cypher, {"__pks": pks}

    def build_count_query(self, cls: type) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to count all entities of *cls*."""
        node_meta = self._require_node_meta(cls)
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)
        where = f"WHERE {subtype_filter} " if subtype_filter else ""
        return f"MATCH (n:{labels_str}) {where}RETURN count(n)", {}

    def build_exists_query(self, cls: type, pk: Any) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to test whether an entity with *pk* exists."""
        node_meta = self._require_node_meta(cls)
        generated = self._is_generated_pk(node_meta)
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)

        if generated:
            id_where = self._dialect.generated_id_where("n", "__pk")
            if subtype_filter:
                id_where = f"WHERE {subtype_filter} AND {id_where[6:]}"
            cypher = f"MATCH (n:{labels_str}) {id_where} RETURN count(n)"
        else:
            pk_name = node_meta.pk_field_name
            if subtype_filter:
                cypher = (
                    f"MATCH (n:{labels_str} {{{pk_name}: $__pk}}) "
                    f"WHERE {subtype_filter} RETURN count(n)"
                )
            else:
                cypher = f"MATCH (n:{labels_str} {{{pk_name}: $__pk}}) RETURN count(n)"

        return cypher, {"__pk": pk}

    def build_paginated_query(
        self, cls: type, pageable: Any
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` for a paginated MATCH with optional ORDER BY."""
        node_meta = self._require_node_meta(cls)
        labels_str = self.labels_clause(node_meta.labels)
        subtype_filter = self.subtype_where("n", node_meta.labels)
        where = f" WHERE {subtype_filter}" if subtype_filter else ""

        order_clause = ""
        if pageable.sort_by:
            direction = "ASC" if str(pageable.direction).upper() == "ASC" else "DESC"
            order_clause = f" ORDER BY n.{pageable.sort_by} {direction}"

        cypher = (
            f"MATCH (n:{labels_str}){where}"
            f" RETURN n{order_clause} SKIP $__skip LIMIT $__limit"
        )
        return cypher, {
            "__skip": pageable.page * pageable.size,
            "__limit": pageable.size,
        }

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def decode_node(self, raw_node: Any, hint_cls: type | None = None) -> Any:
        """Decode a raw driver node to an ORM entity instance."""
        node = self._dialect.wrap_node(raw_node)
        target_cls = self._resolve_cls(node, hint_cls)
        node_meta = self._require_node_meta(target_cls)

        instance: Any = object.__new__(target_cls)
        instance.__dict__["_new"] = False
        instance.__dict__["_dirty"] = False
        instance.__dict__["_expired"] = False

        for fi in node_meta.fields:
            if fi.field.relationship is not None:
                instance.__dict__[fi.name] = _NOT_LOADED
                continue
            self._decode_field(instance, fi, node.properties)

        if node_meta.pk_field_name:
            pk_fi = self._find_field(node_meta.fields, node_meta.pk_field_name)
            if pk_fi is not None and pk_fi.field.generated:
                instance.__dict__[node_meta.pk_field_name] = node.element_id

        log.debug("Decoded node as %s", target_cls.__name__)
        return instance

    def decode_edge(self, falkor_edge: Any, hint_cls: type | None = None) -> Any:
        """Decode a ``falkordb.Edge`` to an ORM Edge instance.

        This is the relationship counterpart of :meth:`decode_node`.  It
        extracts ``falkor_edge.properties`` into an Edge subclass instance and
        applies any registered :class:`~runic.orm.core.types.TypeConverter`.

        When an edge alias is present in a query (``(u)-[r:RATED]->(m)``),
        the ``r`` column is a ``falkordb.Edge`` object; pass it here to get a
        typed :class:`~runic.orm.core.models.Edge` instance back.

        Parameters
        ----------
        falkor_edge:
            A ``falkordb.Edge`` as returned in a ``QueryResult`` row.
        hint_cls:
            The Edge subclass to decode into.  When ``None``, the edge type
            string from ``falkor_edge.type`` is used to look up the registered
            class from :attr:`~runic.orm.core.metadata.MetaData`.  Falls back
            to a plain ``Edge`` instance if no match is found.

        Returns
        -------
        Any
            A decoded instance of *hint_cls* (or the resolved Edge subclass),
            with ``_new=False`` and ``_dirty=False``.

        Example
        -------
        .. code-block:: python

            rows = (
                session.query(User)
                .alias("u")
                .traverse(User.rated, edge_alias="r")
                .alias("m")
                .return_nodes("u", "m")
                .return_edge("r")
                .all_with_edges()
            )
            user, edge, movie = rows[0]
            # edge is a decoded Rated instance with .score populated
        """
        # Resolve the target class
        target_cls: type | None = hint_cls
        edge = self._dialect.wrap_edge(falkor_edge)
        if target_cls is None:
            edge_type = edge.type
            if edge_type is not None:
                edge_meta = self._meta.resolve_edge_by_type(str(edge_type))
                if edge_meta is not None:
                    target_cls = edge_meta.cls

        if target_cls is None:
            log.debug("No Edge class resolved for raw edge; returning raw props")
            return falkor_edge

        edge_meta_entry = self._meta.get_edge_meta(target_cls)
        if edge_meta_entry is None:
            raise MetadataError(
                f"Class {target_cls.__name__!r} is not a registered Edge subclass"
            )

        instance: Any = object.__new__(target_cls)
        instance.__dict__["_new"] = False
        instance.__dict__["_dirty"] = False

        props: dict[str, Any] = edge.properties or {}
        for fi in edge_meta_entry.fields:
            self._decode_field(instance, fi, props)

        log.debug("Decoded edge as %s", target_cls.__name__)
        return instance

    def update_entity_from_node(self, entity: Any, raw_node: Any) -> None:
        """Update an existing entity in-place from a raw driver node."""
        node = self._dialect.wrap_node(raw_node)
        cls = type(entity)
        node_meta = self._require_node_meta(cls)

        for fi in node_meta.fields:
            if fi.field.relationship is not None:
                entity.__dict__[fi.name] = _NOT_LOADED
                continue
            self._decode_field(entity, fi, node.properties)

        if node_meta.pk_field_name:
            pk_fi = self._find_field(node_meta.fields, node_meta.pk_field_name)
            if pk_fi is not None and pk_fi.field.generated:
                entity.__dict__[node_meta.pk_field_name] = node.element_id

        entity.__dict__["_dirty"] = False
        entity.__dict__["_expired"] = False

    @property
    def meta(self) -> MetaData:
        """Return the MetaData registry used by this Mapper."""
        return self._meta

    @property
    def dialect(self) -> GraphDialect:
        """Return the GraphDialect used by this Mapper."""
        return self._dialect

    def require_node_meta(self, cls: type) -> NodeMeta:
        """Public alias for ``_require_node_meta``; used by RelationshipLoader/Session."""
        return self._require_node_meta(cls)

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
        """Find the most specific registered ORM class matching a graph node."""
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

    def _field_cypher_fn(self, fi: FieldInfo) -> str | None:
        """Return the Cypher function name to wrap a param reference, or None."""
        return self._dialect.cypher_fn_for_field(fi)

    def _prop_ref(self, k: str, fi: FieldInfo | None) -> str:
        """Return the Cypher param expression for field *k*, wrapping with a function if needed."""
        if fi is not None:
            fn = self._field_cypher_fn(fi)
            if fn:
                return f"{fn}(${k})"
        return f"${k}"

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
