"""SchemaManager: validate and sync graph indexes against entity declarations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from runic.orm.core.metadata import MetaData, get_metadata
from runic.orm.schema.index_manager import (
    FalkorDBIndexAdapter,
    IndexManager,
    IndexSpec,
    extract_declared_specs,
)

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a :meth:`SchemaManager.validate_schema` call.

    Attributes:
        is_valid: ``True`` when declared and existing indexes match exactly.
        missing_indexes: Declared but not yet created in the live graph.
        extra_indexes: Present in the graph but not declared on any entity.
        errors: Non-fatal messages collected during validation (e.g., introspection failures).
    """

    is_valid: bool
    missing_indexes: list[IndexSpec] = field(default_factory=list)
    extra_indexes: list[IndexSpec] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SchemaManager:
    """Validates and synchronizes graph indexes against entity Field declarations.

    Accepts either a raw FalkorDB graph handle (auto-wrapped in
    :class:`~runic.orm.schema.index_manager.FalkorDBIndexAdapter`) or any object
    satisfying the :class:`~runic.orm.schema.index_manager.IndexAdapter` protocol
    (e.g. a migrate adapter for Neo4j, Memgraph, ArcadeDB, or AGE).

    Example::

        # FalkorDB (backward compat — raw graph handle)
        schema = SchemaManager(graph)
        result = schema.validate_schema([Person, Trip, Stop])

        # Neo4j / any other adapter
        adapter = create_adapter("neo4j", ...)
        schema = SchemaManager(adapter)
        schema.sync_schema([Person, KnowsEdge])
    """

    def __init__(self, adapter_or_graph: Any, meta: MetaData | None = None) -> None:
        if hasattr(adapter_or_graph, "create_node_range_index"):
            self._adapter: Any = FalkorDBIndexAdapter(adapter_or_graph)
        else:
            self._adapter = adapter_or_graph
        self._meta: MetaData = meta if meta is not None else get_metadata()
        self._index_manager = IndexManager(self._adapter, self._meta)

    def ensure_entity_types(self, entity_classes: list[type]) -> None:
        """Create vertex/edge types for *entity_classes* on adapters that require them.

        No-op for schemaless backends (FalkorDB, Neo4j, Memgraph, AGE).
        Issues ``CREATE VERTEX TYPE`` / ``CREATE EDGE TYPE`` DDL for ArcadeDB.
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
        declared: set[IndexSpec] = set()
        errors: list[str] = []

        for cls in entity_classes:
            try:
                declared |= extract_declared_specs(cls)
            except Exception as exc:
                errors.append(f"Failed to extract specs for {cls.__name__!r}: {exc}")

        try:
            existing = self._adapter.get_existing_specs()
        except Exception as exc:
            errors.append(f"Failed to read live indexes: {exc}")
            existing = set()

        missing = sorted(
            declared - existing,
            key=lambda s: (s.label, s.property, s.index_type),
        )
        extra = sorted(
            existing - declared,
            key=lambda s: (s.label, s.property, s.index_type),
        )

        return ValidationResult(
            is_valid=not missing and not extra and not errors,
            missing_indexes=missing,
            extra_indexes=extra,
            errors=errors,
        )

    def sync_schema(
        self,
        entity_classes: list[type],
        *,
        drop_extra: bool = False,
    ) -> None:
        """Create entity types and missing indexes; drop extras when *drop_extra* is ``True``.

        Calls ``ensure_entity_types`` first (required for ArcadeDB empty collections),
        then delegates to :meth:`~runic.orm.schema.index_manager.IndexManager.create_indexes`
        per class for fulltext batching and idempotent creation.
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

    def get_schema_info(self, entity_classes: list[type]) -> dict[str, Any]:
        """Return diagnostic information about the current schema state.

        The returned dict contains counts of declared/existing indexes plus the
        full missing and extra lists for programmatic inspection.
        """
        declared: set[IndexSpec] = set()
        for cls in entity_classes:
            try:
                declared |= extract_declared_specs(cls)
            except Exception as exc:
                log.debug("extract_declared_specs failed for %r: %s", cls, exc)

        try:
            existing = self._adapter.get_existing_specs()
        except Exception as exc:
            log.debug("get_existing_specs failed: %s", exc)
            existing = set()

        result = self.validate_schema(entity_classes)

        return {
            "is_valid": result.is_valid,
            "declared_count": len(declared),
            "existing_count": len(existing),
            "missing_count": len(result.missing_indexes),
            "extra_count": len(result.extra_indexes),
            "missing": [
                {"label": s.label, "property": s.property, "type": s.index_type}
                for s in result.missing_indexes
            ],
            "extra": [
                {"label": s.label, "property": s.property, "type": s.index_type}
                for s in result.extra_indexes
            ],
            "errors": result.errors,
        }
