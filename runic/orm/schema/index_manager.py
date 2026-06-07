"""IndexManager: create and manage graph indexes from entity Field declarations.

Supports FalkorDB (via raw graph handle, auto-wrapped) and any migrate adapter
that satisfies the ``IndexAdapter`` protocol (Neo4j, Memgraph, ArcadeDB, AGE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from runic.orm.core.metadata import MetaData, get_metadata

if TYPE_CHECKING:
    pass

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
    """Parse live FalkorDB graph state and return all existing NODE index/constraint specs.

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


# ---------------------------------------------------------------------------
# IndexAdapter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IndexAdapter(Protocol):
    """Structural protocol satisfied by all runic migrate GraphAdapter subclasses.

    Defined locally in ``orm.schema`` to avoid a circular import between
    ``orm`` and ``migrate``.  Migrate adapters satisfy this protocol
    structurally — no explicit ``implements`` declaration is needed.
    """

    def create_range_index(
        self, label: str, prop: str, *, rel: bool = False
    ) -> None: ...

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None: ...

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,
        stopwords: list[str] | None = None,
    ) -> None: ...

    def drop_fulltext_index(self, label: str, *props: str) -> None: ...

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,
        similarity: str,
        *,
        m: int = 16,
        ef_construction: int = 200,
        ef_runtime: int = 10,
    ) -> None: ...

    def drop_vector_index(self, label: str, prop: str) -> None: ...

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None: ...

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None: ...

    def create_vertex_type(self, label: str) -> None: ...

    def create_edge_type(self, type_name: str) -> None: ...

    def get_existing_specs(self) -> set[IndexSpec]: ...


# ---------------------------------------------------------------------------
# FalkorDBIndexAdapter
# ---------------------------------------------------------------------------


class FalkorDBIndexAdapter:
    """Adapts a raw FalkorDB graph handle to the IndexAdapter protocol.

    Auto-created by IndexManager when a raw graph handle (identified by
    the presence of ``create_node_range_index``) is passed.  This preserves
    backward compat: existing ``IndexManager(graph)`` call sites are unchanged.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        self._graph.create_node_range_index(label, prop)

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:  # noqa: ARG002
        self._graph.drop_node_range_index(label, prop)

    def create_fulltext_index(
        self,
        label: str,
        *props: str,
        language: str | None = None,  # noqa: ARG002
        stopwords: list[str] | None = None,  # noqa: ARG002
    ) -> None:
        self._graph.create_node_fulltext_index(label, *props)

    def drop_fulltext_index(self, label: str, *props: str) -> None:
        self._graph.drop_node_fulltext_index(label, *props)

    def create_vector_index(
        self,
        label: str,
        prop: str,
        dimension: int,  # noqa: ARG002
        similarity: str,  # noqa: ARG002
        *,
        m: int = 16,  # noqa: ARG002
        ef_construction: int = 200,  # noqa: ARG002
        ef_runtime: int = 10,  # noqa: ARG002
    ) -> None:
        self._graph.create_node_vector_index(label, prop)

    def drop_vector_index(self, label: str, prop: str) -> None:
        self._graph.drop_node_vector_index(label, prop)

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            self._graph.create_node_unique_constraint(label, props[0])
        else:
            log.warning(
                "FalkorDB create_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if kind == "UNIQUE" and entity == "NODE" and len(props) == 1:
            self._graph.drop_node_unique_constraint(label, props[0])
        else:
            log.warning(
                "FalkorDB drop_constraint: unsupported kind=%s entity=%s label=%s props=%s",
                kind,
                entity,
                label,
                props,
            )

    def create_vertex_type(self, label: str) -> None:  # noqa: ARG002
        pass

    def create_edge_type(self, type_name: str) -> None:  # noqa: ARG002
        pass

    def get_existing_specs(self) -> set[IndexSpec]:
        return parse_existing_specs(self._graph)


# ---------------------------------------------------------------------------
# IndexManager
# ---------------------------------------------------------------------------


class IndexManager:
    """Creates and manages graph indexes and constraints from entity Field declarations.

    Accepts either a raw FalkorDB graph handle (auto-wrapped in
    :class:`FalkorDBIndexAdapter` for backward compat) or any object satisfying
    the :class:`IndexAdapter` protocol (e.g. a migrate adapter for Neo4j or
    Memgraph).

    **Fulltext batching** — Neo4j and Memgraph use a single named fulltext index
    per label covering all search fields.  ``create_indexes()`` automatically
    collapses all FULLTEXT specs for the same label into one
    ``create_fulltext_index(label, prop1, prop2, ...)`` call.  FalkorDB's
    ``create_node_fulltext_index`` accepts the same variadic signature.

    Example::

        # FalkorDB (backward compat — raw graph handle)
        manager = IndexManager(graph)
        manager.create_indexes(Person, if_not_exists=True)

        # Neo4j / Memgraph via migrate adapter
        adapter = create_adapter("neo4j", host="...", ...)
        manager = IndexManager(adapter)
        manager.create_indexes(Article)
    """

    def __init__(self, adapter_or_graph: Any, meta: MetaData | None = None) -> None:
        if hasattr(adapter_or_graph, "create_node_range_index"):
            self._adapter: Any = FalkorDBIndexAdapter(adapter_or_graph)
        else:
            self._adapter = adapter_or_graph
        self._meta: MetaData = meta if meta is not None else get_metadata()

    def create_indexes(
        self,
        entity_class: type,
        *,
        if_not_exists: bool = True,
    ) -> None:
        """Create all indexes and constraints declared on *entity_class*.

        FULLTEXT specs sharing a label are batched into a single
        ``create_fulltext_index(label, *props)`` call.

        When *if_not_exists* is ``True`` (default), existing non-FULLTEXT specs
        are skipped.  FULLTEXT creation is always attempted — adapters must
        handle idempotency (FalkorDB and Neo4j/Memgraph ``IF NOT EXISTS`` do).
        """
        from runic.orm.core.models import Edge, Node  # local to avoid circular import

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

        # Separate FULLTEXT specs for per-label batching
        ft_by_label: dict[str, list[str]] = {}
        non_ft: list[IndexSpec] = []
        for spec in declared:
            if spec.index_type == "FULLTEXT":
                ft_by_label.setdefault(spec.label, []).append(spec.property)
            else:
                non_ft.append(spec)

        # Batch-create FULLTEXT indexes per label
        for label, props in sorted(ft_by_label.items()):
            existing_ft = {
                s.property
                for s in existing
                if s.label == label and s.index_type == "FULLTEXT"
            }
            new_props = [p for p in props if p not in existing_ft]
            if not new_props:
                log.debug("All fulltext props already exist for %s, skipping", label)
                continue
            log.debug("Creating fulltext index on %s covering %s", label, props)
            self._adapter.create_fulltext_index(label, *props)

        # Create remaining specs one by one
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
            # dimension=0 is a placeholder; FalkorDB ignores it; other backends
            # should pre-create vector indexes with correct dimension via DDL.
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
