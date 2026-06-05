"""SchemaManager: validate and sync FalkorDB indexes against entity declarations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from runic.orm.core.metadata import MetaData, get_metadata
from runic.orm.schema.index_manager import (
    IndexManager,
    IndexSpec,
    extract_declared_specs,
    parse_existing_specs,
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
    """Validates and synchronizes FalkorDB indexes against entity Field declarations.

    Binds to a FalkorDB graph handle, not a Session.

    Example::

        schema = SchemaManager(graph)
        result = schema.validate_schema([Person, Trip, Stop])

        if not result.is_valid:
            print(schema.get_schema_diff([Person, Trip, Stop]))
            schema.sync_schema([Person, Trip, Stop], drop_extra=False)
    """

    def __init__(self, graph: Any, meta: MetaData | None = None) -> None:
        self._graph = graph
        self._meta: MetaData = meta if meta is not None else get_metadata()
        self._index_manager = IndexManager(graph, self._meta)

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
            existing = parse_existing_specs(self._graph)
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
        """Create missing indexes and, when *drop_extra* is ``True``, remove extra ones.

        Runs ``validate_schema`` internally; no duplicate graph introspection.
        Extra indexes are only dropped when explicitly requested to prevent data loss.
        """
        result = self.validate_schema(entity_classes)

        for spec in result.missing_indexes:
            log.info("Creating missing index: %r", spec)
            self._index_manager.create_spec(spec)

        if drop_extra:
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
            existing = parse_existing_specs(self._graph)
        except Exception as exc:
            log.debug("parse_existing_specs failed: %s", exc)
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
