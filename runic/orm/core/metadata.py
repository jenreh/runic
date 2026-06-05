"""Global metadata registry tracking all Node and Edge subclasses."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from runic.orm.core.descriptors import FieldInfo

log = logging.getLogger(__name__)


@dataclass
class NodeMeta:
    """Metadata snapshot for a registered Node subclass."""

    cls: type
    labels: list[str]
    primary_label: str
    fields: list[FieldInfo]
    pk_field_name: str | None = None


@dataclass
class EdgeMeta:
    """Metadata snapshot for a registered Edge subclass."""

    cls: type
    edge_type: str
    fields: list[FieldInfo]


@dataclass
class _MetaSnapshot:
    """Point-in-time snapshot of the registry used for test isolation."""

    nodes: dict[type, NodeMeta] = field(default_factory=dict)
    edges: dict[type, EdgeMeta] = field(default_factory=dict)


class MetaData:
    """Registry for all Node and Edge subclasses.

    Populated automatically when Node/Edge subclasses are defined via
    ``__init_subclass__``. Also provides forward-reference resolution
    (string targets on relationship Fields) after all models are imported.
    """

    def __init__(self) -> None:
        self._nodes: dict[type, NodeMeta] = {}
        self._edges: dict[type, EdgeMeta] = {}
        # label → NodeMeta lookup (primary_label as key)
        self._label_index: dict[str, NodeMeta] = {}
        # edge type → EdgeMeta lookup
        self._type_index: dict[str, EdgeMeta] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(self, cls: type) -> None:
        """Register a Node subclass; called by Node.__init_subclass__."""
        labels: list[str] = getattr(cls, "_labels", [cls.__name__])
        primary_label: str = getattr(cls, "_primary_label", labels[0])
        fields: list[FieldInfo] = getattr(cls, "_fields", [])
        pk_name = _find_pk_field(fields)

        meta = NodeMeta(
            cls=cls,
            labels=labels,
            primary_label=primary_label,
            fields=fields,
            pk_field_name=pk_name,
        )
        self._nodes[cls] = meta
        self._label_index[primary_label] = meta
        log.debug("Registered node: %s (labels=%s)", cls.__name__, labels)

    def register_edge(self, cls: type) -> None:
        """Register an Edge subclass; called by Edge.__init_subclass__."""
        edge_type: str = getattr(cls, "_edge_type", cls.__name__)
        fields: list[FieldInfo] = getattr(cls, "_fields", [])

        meta = EdgeMeta(cls=cls, edge_type=edge_type, fields=fields)
        self._edges[cls] = meta
        self._type_index[edge_type] = meta
        log.debug("Registered edge: %s (type=%s)", cls.__name__, edge_type)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_node_meta(self, cls: type) -> NodeMeta | None:
        """Return metadata for a Node class, or None if not registered."""
        return self._nodes.get(cls)

    def get_edge_meta(self, cls: type) -> EdgeMeta | None:
        """Return metadata for an Edge class, or None if not registered."""
        return self._edges.get(cls)

    def resolve_node_by_label(self, label: str) -> NodeMeta | None:
        """Look up a Node by its primary label string."""
        return self._label_index.get(label)

    def resolve_edge_by_type(self, edge_type: str) -> EdgeMeta | None:
        """Look up an Edge by its type string."""
        return self._type_index.get(edge_type)

    def resolve_target(self, target: str | type | None) -> type | None:
        """Resolve a string forward reference to its registered Node/Edge class."""
        if target is None:
            return None
        if isinstance(target, type):
            return target
        # String forward ref: search nodes then edges
        for node_meta in self._nodes.values():
            if node_meta.cls.__name__ == target:
                return node_meta.cls
        for edge_meta in self._edges.values():
            if edge_meta.cls.__name__ == target:
                return edge_meta.cls
        log.debug("Could not resolve target reference: %r", target)
        return None

    def finalize(self) -> None:
        """Resolve all string forward references in relationship Fields.

        Call once after all model modules have been imported. String targets
        on relationship Fields are replaced with the actual class objects.
        """
        for node_meta in self._nodes.values():
            _resolve_fields(node_meta.fields, self)
        for edge_meta in self._edges.values():
            _resolve_fields(edge_meta.fields, self)
        log.debug(
            "Metadata finalized: %d nodes, %d edges", len(self._nodes), len(self._edges)
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_nodes(self) -> list[NodeMeta]:
        """Return metadata for all registered Node subclasses."""
        return list(self._nodes.values())

    def all_edges(self) -> list[EdgeMeta]:
        """Return metadata for all registered Edge subclasses."""
        return list(self._edges.values())

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def snapshot(self) -> _MetaSnapshot:
        """Capture the current registry state for later restore."""
        return _MetaSnapshot(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
        )

    def restore(self, snap: _MetaSnapshot) -> None:
        """Restore the registry to a prior snapshot (used in test fixtures)."""
        self._nodes = dict(snap.nodes)
        self._edges = dict(snap.edges)
        self._label_index = {m.primary_label: m for m in self._nodes.values()}
        self._type_index = {m.edge_type: m for m in self._edges.values()}

    def clear(self) -> None:
        """Remove all registrations (use in tests only)."""
        self._nodes.clear()
        self._edges.clear()
        self._label_index.clear()
        self._type_index.clear()

    def __repr__(self) -> str:
        return f"MetaData(nodes={len(self._nodes)}, edges={len(self._edges)})"


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _find_pk_field(fields: list[FieldInfo]) -> str | None:
    """Return the name of the primary-key field, or None if none declared."""
    for fi in fields:
        if fi.field.primary_key:
            return fi.name
    # Convention: a field named 'id' is the implicit primary key.
    for fi in fields:
        if fi.name == "id":
            return fi.name
    return None


def _resolve_fields(fields: list[FieldInfo], registry: MetaData) -> None:
    for fi in fields:
        f = fi.field
        if isinstance(f.target, str):
            resolved = registry.resolve_target(f.target)
            if resolved is not None:
                f.target = resolved
        if isinstance(f.edge_model, str):
            resolved = registry.resolve_target(f.edge_model)
            if resolved is not None:
                f.edge_model = resolved


# Global singleton shared by the entire application.
metadata: MetaData = MetaData()


def get_metadata() -> MetaData:
    """Return the global MetaData singleton."""
    return metadata
