"""IndexManager and SchemaManager: create and validate graph indexes via migrate adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from runic.orm.schema.index_manager import IndexSpec, extract_declared_specs

log = logging.getLogger(__name__)

_SPEC_SORT_KEY = lambda s: (s.label, s.property, s.index_type)  # noqa: E731


def _resolve_adapter(adapter_or_graph: Any) -> Any:
    """Wrap a raw FalkorDB graph handle; pass through real adapters unchanged."""
    if hasattr(adapter_or_graph, "create_node_range_index"):
        from runic.migrate.adapters.falkordb import FalkorDBIndexAdapter

        return FalkorDBIndexAdapter(adapter_or_graph)
    return adapter_or_graph


@dataclass
class _SpecsData:
    declared: set[IndexSpec]
    existing: set[IndexSpec]
    missing: list[IndexSpec]
    extra: list[IndexSpec]
    errors: list[str]


def _collect_specs(entity_classes: list[type], adapter: Any) -> _SpecsData:
    declared: set[IndexSpec] = set()
    errors: list[str] = []

    for cls in entity_classes:
        try:
            declared |= extract_declared_specs(cls)
        except Exception as exc:
            errors.append(f"Failed to extract specs for {cls.__name__!r}: {exc}")

    try:
        existing: set[IndexSpec] = adapter.get_existing_specs()
    except Exception as exc:
        errors.append(f"Failed to read live indexes: {exc}")
        existing = set()

    return _SpecsData(
        declared=declared,
        existing=existing,
        missing=sorted(declared - existing, key=_SPEC_SORT_KEY),
        extra=sorted(existing - declared, key=_SPEC_SORT_KEY),
        errors=errors,
    )


@dataclass
class ValidationResult:
    """Result of a :meth:`SchemaManager.validate_schema` call.

    Attributes:
        is_valid: ``True`` when declared and existing indexes match exactly.
        missing_indexes: Declared but not yet created in the live graph.
        extra_indexes: Present in the graph but not declared on any entity.
        errors: Non-fatal messages collected during validation.
    """

    is_valid: bool
    missing_indexes: list[IndexSpec] = field(default_factory=list)
    extra_indexes: list[IndexSpec] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SchemaInfo:
    """Diagnostic snapshot of the current schema state.

    Attributes:
        is_valid: ``True`` when declared and existing indexes match exactly.
        declared_count: Number of indexes declared across all entity classes.
        existing_count: Number of indexes found in the live graph.
        missing_count: Number of declared indexes not yet created.
        extra_count: Number of live indexes not declared on any entity.
        missing: Serialisable list of missing index specs.
        extra: Serialisable list of extra index specs.
        errors: Non-fatal messages collected during introspection.
    """

    is_valid: bool
    declared_count: int
    existing_count: int
    missing_count: int
    extra_count: int
    missing: list[dict[str, str]]
    extra: list[dict[str, str]]
    errors: list[str]


class IndexManager:
    """Creates and manages graph indexes and constraints from entity Field declarations.

    Accepts any object satisfying the :class:`~runic.migrate.adapters._base.IndexAdapter`
    protocol — a migrate adapter (Neo4j, Memgraph, FalkorDB, ArcadeDB, AGE) or a raw
    FalkorDB graph handle (auto-wrapped in ``FalkorDBIndexAdapter`` for backward compat).

    **Fulltext batching** — Neo4j and Memgraph use a single named fulltext index per
    label covering all search fields.  ``create_indexes()`` collapses all FULLTEXT specs
    for the same label into one ``create_fulltext_index(label, prop1, prop2, ...)`` call.

    Example::

        from runic.migrate import IndexManager, create_adapter

        adapter = create_adapter(
            "neo4j", host="localhost", database="neo4j", password="secret"
        )
        manager = IndexManager(adapter)
        manager.create_indexes(Person)
        manager.ensure_indexes(Trip)
    """

    def __init__(self, adapter_or_graph: Any) -> None:
        self._adapter: Any = _resolve_adapter(adapter_or_graph)

    def create_indexes(
        self,
        entity_class: type,
        *,
        if_not_exists: bool = True,
    ) -> None:
        """Create all indexes and constraints declared on *entity_class*.

        FULLTEXT specs sharing a label are batched into a single
        ``create_fulltext_index(label, *props)`` call.

        When *if_not_exists* is ``True`` (default), existing non-FULLTEXT specs are
        skipped.  FULLTEXT creation is always attempted — adapters must handle idempotency.
        """
        from runic.orm.core.models import Edge, Node

        if issubclass(entity_class, Node):
            label: str = getattr(entity_class, "_primary_label", entity_class.__name__)
            log.debug("Ensuring vertex type for %s", label)
            self._adapter.create_vertex_type(label)
        elif issubclass(entity_class, Edge):
            edge_type: str = getattr(entity_class, "_edge_type", entity_class.__name__)
            log.debug("Ensuring edge type for %s", edge_type)
            self._adapter.create_edge_type(edge_type)

        declared = extract_declared_specs(entity_class)
        existing = self._adapter.get_existing_specs() if if_not_exists else set()

        ft_by_label: dict[str, list[str]] = {}
        non_ft: list[IndexSpec] = []
        for spec in declared:
            if spec.index_type == "FULLTEXT":
                ft_by_label.setdefault(spec.label, []).append(spec.property)
            else:
                non_ft.append(spec)

        for lbl, props in sorted(ft_by_label.items()):
            existing_ft = {
                s.property
                for s in existing
                if s.label == lbl and s.index_type == "FULLTEXT"
            }
            new_props = [p for p in props if p not in existing_ft]
            if not new_props:
                log.debug("All fulltext props already exist for %s, skipping", lbl)
                continue
            log.debug("Creating fulltext index on %s covering %s", lbl, props)
            self._adapter.create_fulltext_index(lbl, *props)

        for spec in sorted(non_ft, key=lambda s: (s.label, s.property, s.index_type)):
            if spec in existing:
                log.debug("Index already exists, skipping: %r", spec)
                continue
            self.create_spec(spec)

    def ensure_indexes(self, entity_class: type) -> None:
        """Create missing indexes for *entity_class*; skip those that already exist."""
        self.create_indexes(entity_class, if_not_exists=True)

    def create_spec(self, spec: IndexSpec) -> None:
        """Issue the appropriate adapter call to create a single IndexSpec."""
        if spec.index_type == "UNIQUE":
            log.debug("Creating unique constraint: %r", spec)
            self._adapter.create_constraint(
                "UNIQUE", "NODE", spec.label, [spec.property]
            )
        elif spec.index_type == "RANGE":
            log.debug("Creating range index: %r", spec)
            self._adapter.create_range_index(spec.label, spec.property)
        elif spec.index_type == "FULLTEXT":
            log.debug("Creating fulltext index: %r", spec)
            self._adapter.create_fulltext_index(spec.label, spec.property)
        elif spec.index_type == "VECTOR":
            log.debug("Creating vector index: %r", spec)
            self._adapter.create_vector_index(spec.label, spec.property, 0, "cosine")
        else:
            log.warning(
                "Unknown index type %r for %r — skipping", spec.index_type, spec
            )

    def drop_spec(self, spec: IndexSpec) -> None:
        """Issue the appropriate adapter call to drop a single IndexSpec."""
        if spec.index_type == "UNIQUE":
            log.debug("Dropping unique constraint: %r", spec)
            self._adapter.drop_constraint("UNIQUE", "NODE", spec.label, [spec.property])
        elif spec.index_type == "RANGE":
            log.debug("Dropping range index: %r", spec)
            self._adapter.drop_range_index(spec.label, spec.property)
        elif spec.index_type == "FULLTEXT":
            log.debug("Dropping fulltext index: %r", spec)
            self._adapter.drop_fulltext_index(spec.label, spec.property)
        elif spec.index_type == "VECTOR":
            log.debug("Dropping vector index: %r", spec)
            self._adapter.drop_vector_index(spec.label, spec.property)
        else:
            log.warning(
                "Unknown index type %r for %r — cannot drop", spec.index_type, spec
            )


class SchemaManager:
    """Validates and synchronizes graph indexes against entity Field declarations.

    Accepts any object satisfying the :class:`~runic.migrate.adapters._base.IndexAdapter`
    protocol (a migrate adapter or a raw FalkorDB graph handle for backward compat).

    Example::

        from runic.migrate import SchemaManager, create_adapter

        adapter = create_adapter(
            "neo4j", host="localhost", database="neo4j", password="secret"
        )
        schema = SchemaManager(adapter)
        result = schema.validate_schema([Person, KnowsEdge])
        schema.sync_schema([Person, KnowsEdge])
    """

    def __init__(self, adapter_or_graph: Any) -> None:
        self._adapter: Any = _resolve_adapter(adapter_or_graph)
        self._index_manager = IndexManager(self._adapter)

    def ensure_entity_types(self, entity_classes: list[type]) -> None:
        """Create vertex/edge types for *entity_classes* on adapters that require them.

        No-op for schemaless backends.  Issues ``CREATE VERTEX TYPE`` / ``CREATE EDGE TYPE``
        DDL for ArcadeDB.
        """
        from runic.orm.core.models import Edge, Node

        for cls in entity_classes:
            if issubclass(cls, Node):
                label: str = getattr(cls, "_primary_label", cls.__name__)
                self._adapter.create_vertex_type(label)
            elif issubclass(cls, Edge):
                edge_type: str = getattr(cls, "_edge_type", cls.__name__)
                self._adapter.create_edge_type(edge_type)

    def validate_schema(self, entity_classes: list[type]) -> ValidationResult:
        """Compare declared indexes against the live graph state.

        Returns a :class:`ValidationResult` describing missing and extra indexes.
        ``is_valid`` is ``True`` only when both sets are empty and no errors occurred.
        """
        data = _collect_specs(entity_classes, self._adapter)
        return ValidationResult(
            is_valid=not data.missing and not data.extra and not data.errors,
            missing_indexes=data.missing,
            extra_indexes=data.extra,
            errors=data.errors,
        )

    def sync_schema(
        self,
        entity_classes: list[type],
        *,
        drop_extra: bool = False,
    ) -> None:
        """Create entity types and missing indexes; drop extras when *drop_extra* is ``True``.

        Calls ``ensure_entity_types`` first (required for ArcadeDB empty collections),
        then delegates to :meth:`IndexManager.create_indexes` per class.
        """
        self.ensure_entity_types(entity_classes)
        for cls in entity_classes:
            self._index_manager.create_indexes(cls)

        if drop_extra:
            result = self.validate_schema(entity_classes)
            for spec in result.extra_indexes:
                log.info("Dropping extra index: %r", spec)
                self._index_manager.drop_spec(spec)

    def get_schema_diff(self, entity_classes: list[type]) -> str:
        """Return a human-readable diff of declared vs existing indexes.

        Lines are prefixed with ``MISSING`` or ``EXTRA``; returns a single
        "in sync" message when no differences exist.
        """
        result = self.validate_schema(entity_classes)

        if not result.missing_indexes and not result.extra_indexes:
            return "Schema is in sync — no differences found."

        lines: list[str] = [
            f"  MISSING  {s.index_type:<10} {s.label}.{s.property}"
            for s in result.missing_indexes
        ]
        lines.extend(
            f"  EXTRA    {s.index_type:<10} {s.label}.{s.property}"
            for s in result.extra_indexes
        )
        return "\n".join(lines)

    def get_schema_info(self, entity_classes: list[type]) -> SchemaInfo:
        """Return a :class:`SchemaInfo` snapshot of the current schema state."""
        data = _collect_specs(entity_classes, self._adapter)
        return SchemaInfo(
            is_valid=not data.missing and not data.extra and not data.errors,
            declared_count=len(data.declared),
            existing_count=len(data.existing),
            missing_count=len(data.missing),
            extra_count=len(data.extra),
            missing=[
                {"label": s.label, "property": s.property, "type": s.index_type}
                for s in data.missing
            ],
            extra=[
                {"label": s.label, "property": s.property, "type": s.index_type}
                for s in data.extra
            ],
            errors=data.errors,
        )
