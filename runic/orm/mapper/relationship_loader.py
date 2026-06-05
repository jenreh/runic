"""Lazy and eager relationship loading for ORM entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.orm.core.descriptors import FieldInfo
from runic.orm.core.metadata import MetaData, NodeMeta

if TYPE_CHECKING:
    from runic.orm.mapper.mapper import Mapper

log = logging.getLogger(__name__)


class RelationshipLoader:
    """Builds and decodes lazy/eager relationship queries.

    Composed by Session and AsyncSession; never used directly by application code.
    """

    def __init__(self, meta: MetaData, mapper: Mapper) -> None:
        self._meta = meta
        self._mapper = mapper

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def build_lazy_load_query(
        self, entity: Any, fi: FieldInfo
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(cypher, params)`` to load a single lazy relationship field."""
        cls = type(entity)
        node_meta = self._mapper.require_node_meta(cls)
        pk_val = self._mapper.get_pk_value(entity)
        generated = self._mapper.is_generated_pk(cls)

        _, target_label = self._resolve_target(fi)
        rel_pattern = self._rel_pattern("n", fi, "related", target_label)

        if generated:
            match_src = (
                f"MATCH (n:{node_meta.primary_label}) WHERE id(n) = toInteger($__pk)"
            )
        else:
            pk_name = node_meta.pk_field_name
            match_src = f"MATCH (n:{node_meta.primary_label} {{{pk_name}: $__pk}})"

        cypher = f"{match_src}\nMATCH {rel_pattern}\nRETURN related"
        return cypher, {"__pk": pk_val}

    def decode_lazy_result(
        self,
        result: Any,
        fi: FieldInfo,
    ) -> Any:
        """Decode a lazy-load ``QueryResult`` into an entity or list of entities."""
        if not result.result_set:
            return [] if fi.is_collection else None

        target_cls, _ = self._resolve_target(fi)

        if fi.is_collection:
            return [
                self._mapper.decode_node(row[0], target_cls)
                for row in result.result_set
                if row[0] is not None
            ]
        row = result.result_set[0]
        return (
            self._mapper.decode_node(row[0], target_cls) if row[0] is not None else None
        )

    # ------------------------------------------------------------------
    # Eager loading
    # ------------------------------------------------------------------

    def build_get_with_fetch_query(
        self,
        cls: type,
        pk: Any,
        fetch: list[str],
    ) -> tuple[str, dict[str, Any], list[tuple[str, FieldInfo]]]:
        """Build a MATCH + OPTIONAL MATCHes query for eager relationship loading.

        Returns ``(cypher, params, fetch_meta)`` where *fetch_meta* is a list of
        ``(field_name, field_info)`` for each valid relationship in *fetch*.
        The result columns are ``[n, collect(distinct r0) AS name0, ...]``.
        """
        node_meta = self._mapper.require_node_meta(cls)
        generated = self._mapper.is_generated_pk(cls)
        labels_str = ":".join(node_meta.labels)

        if generated:
            main_match = f"MATCH (n:{labels_str}) WHERE id(n) = toInteger($__pk)"
        else:
            pk_name = node_meta.pk_field_name
            main_match = f"MATCH (n:{labels_str} {{{pk_name}: $__pk}})"

        optional_clauses, return_cols, fetch_meta = self._build_fetch_clauses(
            node_meta, fetch
        )
        parts = [main_match, *optional_clauses, f"RETURN {', '.join(return_cols)}"]
        return "\n".join(parts), {"__pk": pk}, fetch_meta

    def build_find_all_with_fetch_query(
        self,
        cls: type,
        fetch: list[str],
    ) -> tuple[str, dict[str, Any], list[tuple[str, FieldInfo]]]:
        """Build MATCH + OPTIONAL MATCHes to find all entities with eager loading."""
        node_meta = self._mapper.require_node_meta(cls)
        labels_str = ":".join(node_meta.labels)
        main_match = f"MATCH (n:{labels_str})"

        optional_clauses, return_cols, fetch_meta = self._build_fetch_clauses(
            node_meta, fetch
        )
        parts = [main_match, *optional_clauses, f"RETURN {', '.join(return_cols)}"]
        return "\n".join(parts), {}, fetch_meta

    def build_find_all_by_ids_with_fetch_query(
        self,
        cls: type,
        pks: list[Any],
        fetch: list[str],
    ) -> tuple[str, dict[str, Any], list[tuple[str, FieldInfo]]]:
        """Build MATCH + OPTIONAL MATCHes to fetch a batch of entities by PK."""
        node_meta = self._mapper.require_node_meta(cls)
        generated = self._mapper.is_generated_pk(cls)
        labels_str = ":".join(node_meta.labels)

        if generated:
            main_match = f"MATCH (n:{labels_str}) WHERE id(n) IN $__pks"
        else:
            pk_name = node_meta.pk_field_name
            main_match = f"MATCH (n:{labels_str}) WHERE n.{pk_name} IN $__pks"

        optional_clauses, return_cols, fetch_meta = self._build_fetch_clauses(
            node_meta, fetch
        )
        parts = [main_match, *optional_clauses, f"RETURN {', '.join(return_cols)}"]
        return "\n".join(parts), {"__pks": pks}, fetch_meta

    def decode_eager_columns(
        self,
        row: list[Any],
        entity: Any,
        fetch_meta: list[tuple[str, FieldInfo]],
    ) -> list[Any]:
        """Decode eager-loaded columns (index 1+) directly into ``entity.__dict__``.

        Returns a flat list of all decoded related entity instances so the caller
        can inject ``_session`` into each one.
        """
        decoded_entities: list[Any] = []

        for i, (field_name, fi) in enumerate(fetch_meta):
            collected: list[Any] = row[i + 1] or []
            target_cls, _ = self._resolve_target(fi)

            if fi.is_collection:
                decoded_list = [
                    self._mapper.decode_node(node, target_cls)
                    for node in collected
                    if node is not None
                ]
                entity.__dict__[field_name] = decoded_list
                decoded_entities.extend(decoded_list)
            else:
                first = next((n for n in collected if n is not None), None)
                decoded = (
                    self._mapper.decode_node(first, target_cls)
                    if first is not None
                    else None
                )
                entity.__dict__[field_name] = decoded
                if decoded is not None:
                    decoded_entities.append(decoded)

        return decoded_entities

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_fetch_clauses(
        self,
        node_meta: NodeMeta,
        fetch: list[str],
    ) -> tuple[list[str], list[str], list[tuple[str, FieldInfo]]]:
        """Build OPTIONAL MATCH clauses and RETURN columns for *fetch* field names.

        Returns ``(optional_clauses, return_cols, fetch_meta)``.
        ``return_cols`` always starts with ``["n"]``.
        """
        optional_clauses: list[str] = []
        return_cols: list[str] = ["n"]
        fetch_meta: list[tuple[str, FieldInfo]] = []

        for i, field_name in enumerate(fetch):
            fi = next((f for f in node_meta.fields if f.name == field_name), None)
            if fi is None or fi.field.relationship is None:
                log.debug(
                    "Skipping unknown or non-relationship fetch name: %r", field_name
                )
                continue

            alias = f"_r{i}_{field_name}"
            _, target_label = self._resolve_target(fi)
            rel_pattern = self._rel_pattern("n", fi, alias, target_label)

            optional_clauses.append(f"OPTIONAL MATCH {rel_pattern}")
            return_cols.append(f"collect(distinct {alias}) AS {field_name}")
            fetch_meta.append((field_name, fi))

        return optional_clauses, return_cols, fetch_meta

    def _resolve_target(self, fi: FieldInfo) -> tuple[type | None, str]:
        """Return ``(target_cls, primary_label)`` for a relationship FieldInfo."""
        raw = fi.field.target
        target_cls: type | None = (
            self._meta.resolve_target(raw) if isinstance(raw, str) else raw
        )

        if target_cls is not None:
            node_meta = self._meta.get_node_meta(target_cls)
            label = node_meta.primary_label if node_meta else target_cls.__name__
        else:
            label = str(raw) if raw is not None else "Node"

        return target_cls, label

    def _rel_pattern(
        self,
        src: str,
        fi: FieldInfo,
        alias: str,
        target_label: str,
    ) -> str:
        """Return the Cypher relationship pattern, e.g. ``(n)-[:REL]->(alias:Label)``."""
        rel_type = fi.field.relationship
        direction = fi.field.direction or "OUTGOING"

        if direction == "OUTGOING":
            return f"({src})-[:{rel_type}]->({alias}:{target_label})"
        if direction == "INCOMING":
            return f"({src})<-[:{rel_type}]-({alias}:{target_label})"
        return f"({src})-[:{rel_type}]-({alias}:{target_label})"
