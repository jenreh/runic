"""Unit tests for the MetaData registry."""

from runic.orm.core.descriptors import Field, Relation
from runic.orm.core.metadata import MetaData, metadata
from runic.orm.core.models import Edge, Node

# ---------------------------------------------------------------------------
# Module-level entities used across tests
# ---------------------------------------------------------------------------


class MetaTestPerson(Node, labels=["MetaTestPerson"]):
    id: str = Field(primary_key=True)
    name: str = Field()


class MetaTestKnowsEdge(Edge, type="META_KNOWS"):
    weight: float = Field(default=1.0)


# ---------------------------------------------------------------------------
# Node registration
# ---------------------------------------------------------------------------


def test_node_registered_in_global_metadata() -> None:
    meta = metadata.get_node_meta(MetaTestPerson)
    assert meta is not None
    assert meta.cls is MetaTestPerson


def test_node_labels_in_metadata() -> None:
    meta = metadata.get_node_meta(MetaTestPerson)
    assert meta is not None
    assert meta.labels == ["MetaTestPerson"]


def test_node_primary_label_in_metadata() -> None:
    meta = metadata.get_node_meta(MetaTestPerson)
    assert meta is not None
    assert meta.primary_label == "MetaTestPerson"


def test_node_pk_field_detected() -> None:
    meta = metadata.get_node_meta(MetaTestPerson)
    assert meta is not None
    assert meta.pk_field_name == "id"


def test_node_fields_in_metadata() -> None:
    meta = metadata.get_node_meta(MetaTestPerson)
    assert meta is not None
    names = {fi.name for fi in meta.fields}
    assert "id" in names
    assert "name" in names


# ---------------------------------------------------------------------------
# Edge registration
# ---------------------------------------------------------------------------


def test_edge_registered_in_global_metadata() -> None:
    meta = metadata.get_edge_meta(MetaTestKnowsEdge)
    assert meta is not None
    assert meta.cls is MetaTestKnowsEdge


def test_edge_type_in_metadata() -> None:
    meta = metadata.get_edge_meta(MetaTestKnowsEdge)
    assert meta is not None
    assert meta.edge_type == "META_KNOWS"


# ---------------------------------------------------------------------------
# Label / type index lookups
# ---------------------------------------------------------------------------


def test_resolve_node_by_primary_label() -> None:
    meta = metadata.resolve_node_by_label("MetaTestPerson")
    assert meta is not None
    assert meta.cls is MetaTestPerson


def test_resolve_node_by_unknown_label_returns_none() -> None:
    assert metadata.resolve_node_by_label("DoesNotExist") is None


def test_resolve_edge_by_type() -> None:
    meta = metadata.resolve_edge_by_type("META_KNOWS")
    assert meta is not None
    assert meta.cls is MetaTestKnowsEdge


# ---------------------------------------------------------------------------
# Forward-reference resolution
# ---------------------------------------------------------------------------


def test_resolve_target_by_class() -> None:
    result = metadata.resolve_target(MetaTestPerson)
    assert result is MetaTestPerson


def test_resolve_target_by_string_name() -> None:
    result = metadata.resolve_target("MetaTestPerson")
    assert result is MetaTestPerson


def test_resolve_target_unknown_returns_none() -> None:
    assert metadata.resolve_target("Nonexistent") is None


def test_resolve_target_none_returns_none() -> None:
    assert metadata.resolve_target(None) is None


# ---------------------------------------------------------------------------
# Finalize: resolves string targets in relationship fields
# ---------------------------------------------------------------------------


def test_finalize_resolves_string_target() -> None:
    local_meta = MetaData()

    class Source(Node, labels=["Source"]):
        id: str = Field()
        friend: str = Relation(
            relationship="KNOWS", direction="OUTGOING", target="Target"
        )

    class Target(Node, labels=["Target"]):
        id: str = Field()

    # Re-register with a fresh registry to control the environment.
    local_meta.register_node(Source)
    local_meta.register_node(Target)

    # The target on Source's field is still a string at this point.
    friend_field = next(fi.field for fi in Source._fields if fi.name == "friend")
    assert friend_field.target == "Target"

    local_meta.finalize()
    assert friend_field.target is Target


# ---------------------------------------------------------------------------
# Snapshot / restore isolation
# ---------------------------------------------------------------------------


def test_snapshot_and_restore_isolation() -> None:
    snap = metadata.snapshot()

    class TempNode(Node, labels=["TempNode"]):
        id: str = Field()

    assert metadata.get_node_meta(TempNode) is not None

    metadata.restore(snap)
    assert metadata.get_node_meta(TempNode) is None


def test_all_nodes_returns_list() -> None:
    nodes = metadata.all_nodes()
    classes = [m.cls for m in nodes]
    assert MetaTestPerson in classes


def test_all_edges_returns_list() -> None:
    edges = metadata.all_edges()
    types = [m.edge_type for m in edges]
    assert "META_KNOWS" in types


# ---------------------------------------------------------------------------
# PK convention: field named 'id' without primary_key=True
# ---------------------------------------------------------------------------


def test_pk_detected_by_name_convention() -> None:
    class ConventionNode(Node, labels=["ConventionNode"]):
        id: str = Field()
        title: str = Field()

    meta = metadata.get_node_meta(ConventionNode)
    assert meta is not None
    assert meta.pk_field_name == "id"
