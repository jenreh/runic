"""IndexSpec and entity-declaration extraction for graph index management."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

_INDEX_TYPES = frozenset({"RANGE", "FULLTEXT", "VECTOR", "UNIQUE"})


@dataclass(frozen=True)
class IndexSpec:
    """Normalized description of a single declared or existing index/constraint.

    ``index_type`` is one of ``"RANGE"``, ``"FULLTEXT"``, ``"VECTOR"``, or ``"UNIQUE"``.
    """

    label: str
    property: str
    index_type: str

    def __repr__(self) -> str:
        return f"IndexSpec({self.index_type} {self.label}.{self.property})"


def extract_declared_specs(entity_class: type) -> set[IndexSpec]:
    """Return IndexSpecs declared via Field descriptors on *entity_class*.

    Rules:
    - ``unique=True``  → UNIQUE constraint (backing RANGE is auto-created by FalkorDB).
    - ``index=True`` (without ``unique``) → RANGE index.
    - ``index_type="FULLTEXT"`` → FULLTEXT index.
    - ``index_type="VECTOR"`` → VECTOR index.
    - Relationship fields are skipped.
    - A field with both ``unique=True`` and ``index=True`` emits only UNIQUE.
    """
    fields = getattr(entity_class, "_fields", [])
    label: str = getattr(entity_class, "_primary_label", entity_class.__name__)
    specs: set[IndexSpec] = set()

    for fi in fields:
        f = fi.field
        if f.relationship is not None:
            continue
        if f.unique:
            specs.add(IndexSpec(label=label, property=fi.name, index_type="UNIQUE"))
        elif f.index:
            specs.add(IndexSpec(label=label, property=fi.name, index_type="RANGE"))
        if f.index_type == "FULLTEXT":
            specs.add(IndexSpec(label=label, property=fi.name, index_type="FULLTEXT"))
        elif f.index_type == "VECTOR":
            specs.add(IndexSpec(label=label, property=fi.name, index_type="VECTOR"))

    return specs
