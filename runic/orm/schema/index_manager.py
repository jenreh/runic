"""IndexManager: create and manage FalkorDB indexes from entity Field declarations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from runic.orm.core.metadata import MetaData, get_metadata

log = logging.getLogger(__name__)

# Valid index type strings as tracked by runic.orm.
_INDEX_TYPES = frozenset({"RANGE", "FULLTEXT", "VECTOR", "UNIQUE"})


@dataclass(frozen=True)
class IndexSpec:
    """Normalized description of a single declared or existing index/constraint.

    Used for comparing declared entity schemas against the live graph state.
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
            continue  # relationship fields have no property indexes
        if f.unique:
            specs.add(IndexSpec(label=label, property=fi.name, index_type="UNIQUE"))
            # Do NOT emit RANGE — FalkorDB auto-creates the backing range index.
        elif f.index:
            specs.add(IndexSpec(label=label, property=fi.name, index_type="RANGE"))
        if f.index_type == "FULLTEXT":
            specs.add(IndexSpec(label=label, property=fi.name, index_type="FULLTEXT"))
        elif f.index_type == "VECTOR":
            specs.add(IndexSpec(label=label, property=fi.name, index_type="VECTOR"))

    return specs


def parse_existing_specs(graph: Any) -> set[IndexSpec]:
    """Parse live graph state and return all existing NODE index/constraint specs.

    Unique constraints are sourced from ``list_constraints()``.  Regular indexes
    (RANGE / FULLTEXT / VECTOR) are sourced from ``list_indices()``.  The RANGE
    index that FalkorDB auto-creates as backing storage for a UNIQUE constraint is
    excluded so it is not reported as an extra index during schema diffing.
    """
    specs: set[IndexSpec] = set()
    unique_pairs: set[tuple[str, str]] = set()

    # Unique constraints — already parsed by falkordb client into dicts.
    try:
        for constraint in graph.list_constraints():
            if constraint.get("type") != "UNIQUE":
                continue
            if constraint.get("entitytype") != "NODE":
                continue
            lbl: str = constraint["label"]
            for prop in constraint.get("properties", []):
                specs.add(IndexSpec(label=lbl, property=prop, index_type="UNIQUE"))
                unique_pairs.add((lbl, prop))
    except Exception:
        log.debug("list_constraints() unavailable or failed")

    # Regular indexes — raw QueryResult, map columns by name from header.
    try:
        result = graph.list_indices()
        col_map: dict[str, int] = {col[1]: idx for idx, col in enumerate(result.header)}
        label_col = col_map.get("label", 0)
        types_col = col_map.get("types", 2)
        entitytype_col = col_map.get("entitytype", 6)

        for row in result.result_set:
            if row[entitytype_col] != "NODE":
                continue
            lbl = row[label_col]
            types_dict = row[types_col]  # OrderedDict{prop: [type_list]}
            for prop, type_list in types_dict.items():
                for idx_type in type_list:
                    if idx_type == "RANGE" and (lbl, prop) in unique_pairs:
                        # Auto-backing range index for a unique constraint; not extra.
                        continue
                    if idx_type in _INDEX_TYPES:
                        specs.add(
                            IndexSpec(label=lbl, property=prop, index_type=idx_type)
                        )
    except Exception:
        log.debug("list_indices() unavailable or failed")

    return specs


class IndexManager:
    """Creates and manages FalkorDB indexes and constraints from Field declarations.

    Binds to a FalkorDB graph handle, not a Session.

    Example::

        manager = IndexManager(graph)
        manager.create_indexes(Person, if_not_exists=True)
        manager.ensure_indexes(Trip)
    """

    def __init__(self, graph: Any, meta: MetaData | None = None) -> None:
        self._graph = graph
        self._meta: MetaData = meta if meta is not None else get_metadata()

    def create_indexes(
        self,
        entity_class: type,
        *,
        if_not_exists: bool = True,
    ) -> None:
        """Create all indexes and constraints declared on *entity_class*.

        When *if_not_exists* is ``True`` (default), specs already present in the
        live graph are skipped silently.  Pass ``if_not_exists=False`` to attempt
        creation unconditionally (the graph will raise on duplicates).
        """
        declared = extract_declared_specs(entity_class)
        existing = parse_existing_specs(self._graph) if if_not_exists else set()

        for spec in sorted(declared, key=lambda s: (s.label, s.property, s.index_type)):
            if spec in existing:
                log.debug("Index already exists, skipping: %r", spec)
                continue
            self.create_spec(spec)

    def ensure_indexes(self, entity_class: type) -> None:
        """Create missing indexes for *entity_class*; skip those that already exist."""
        self.create_indexes(entity_class, if_not_exists=True)

    def create_spec(self, spec: IndexSpec) -> None:
        """Issue the appropriate FalkorDB API call to create a single IndexSpec."""
        if spec.index_type == "UNIQUE":
            log.debug("Creating unique constraint: %r", spec)
            self._graph.create_node_unique_constraint(spec.label, spec.property)
        elif spec.index_type == "RANGE":
            log.debug("Creating range index: %r", spec)
            self._graph.create_node_range_index(spec.label, spec.property)
        elif spec.index_type == "FULLTEXT":
            log.debug("Creating fulltext index: %r", spec)
            self._graph.create_node_fulltext_index(spec.label, spec.property)
        elif spec.index_type == "VECTOR":
            log.debug("Creating vector index: %r", spec)
            self._graph.create_node_vector_index(spec.label, spec.property)
        else:
            log.warning(
                "Unknown index type %r for %r — skipping", spec.index_type, spec
            )

    def drop_spec(self, spec: IndexSpec) -> None:
        """Issue the appropriate FalkorDB API call to drop a single IndexSpec."""
        if spec.index_type == "UNIQUE":
            log.debug("Dropping unique constraint: %r", spec)
            self._graph.drop_node_unique_constraint(spec.label, spec.property)
        elif spec.index_type == "RANGE":
            log.debug("Dropping range index: %r", spec)
            self._graph.drop_node_range_index(spec.label, spec.property)
        elif spec.index_type == "FULLTEXT":
            log.debug("Dropping fulltext index: %r", spec)
            self._graph.drop_node_fulltext_index(spec.label, spec.property)
        elif spec.index_type == "VECTOR":
            log.debug("Dropping vector index: %r", spec)
            self._graph.drop_node_vector_index(spec.label, spec.property)
        else:
            log.warning(
                "Unknown index type %r for %r — cannot drop", spec.index_type, spec
            )
