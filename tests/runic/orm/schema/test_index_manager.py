"""Tests for IndexManager and the spec extraction/parsing helpers."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field, Relation
from runic.orm.core.models import Edge, Node
from runic.orm.schema.index_manager import (
    IndexManager,
    IndexSpec,
    extract_declared_specs,
    parse_existing_specs,
)

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark_integration = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class SchemaPersonNode(Node, labels=["SchemaPerson"]):
    id: str
    email: str = Field(index=True, unique=True)
    name: str
    bio: str = Field(index_type="FULLTEXT")
    age: int = Field(index=True)


class SchemaLocationNode(
    Node, labels=["SchemaLocation"], primary_label="SchemaLocation"
):
    id: str
    title: str = Field(index_type="FULLTEXT")
    latitude: float = Field(index=True)


class SchemaNodeNoIndexes(Node, labels=["SchemaNoIdx"]):
    id: str
    value: str


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def graph() -> Any:
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)
    g = db.select_graph(f"test_idx_{secrets.token_hex(6)}")
    yield g
    with contextlib.suppress(Exception):
        g.delete()


# ---------------------------------------------------------------------------
# extract_declared_specs — unit tests (no graph)
# ---------------------------------------------------------------------------


def test_extract_range_index() -> None:
    class RangeNode(Node, labels=["RangeNode"]):
        id: str = Field()
        score: int = Field(index=True)

    specs = extract_declared_specs(RangeNode)
    assert IndexSpec(label="RangeNode", property="score", index_type="RANGE") in specs


def test_extract_unique_constraint() -> None:
    class UniqueNode(Node, labels=["UniqueNode"]):
        id: str = Field()
        code: str = Field(unique=True)

    specs = extract_declared_specs(UniqueNode)
    assert IndexSpec(label="UniqueNode", property="code", index_type="UNIQUE") in specs
    # Backing RANGE must NOT be emitted — it's auto-created by FalkorDB.
    assert (
        IndexSpec(label="UniqueNode", property="code", index_type="RANGE") not in specs
    )


def test_extract_fulltext_index() -> None:
    class FTNode(Node, labels=["FTNode"]):
        id: str = Field()
        bio: str = Field(index_type="FULLTEXT")

    specs = extract_declared_specs(FTNode)
    assert IndexSpec(label="FTNode", property="bio", index_type="FULLTEXT") in specs


def test_extract_unique_does_not_add_range() -> None:
    """unique=True + index=True: only UNIQUE is declared (RANGE is auto-backed)."""

    class BothNode(Node, labels=["BothNode"]):
        id: str = Field()
        code: str = Field(unique=True, index=True)

    specs = extract_declared_specs(BothNode)
    assert IndexSpec(label="BothNode", property="code", index_type="UNIQUE") in specs
    assert IndexSpec(label="BothNode", property="code", index_type="RANGE") not in specs


def test_extract_skips_relationship_fields() -> None:
    class RelEdge(Edge, type="REL_EDGE"):
        weight: float = Field()

    class RelNode(Node, labels=["RelNode"]):
        id: str = Field()
        friend: str = Relation(
            relationship="KNOWS", direction="OUTGOING", target="RelNode"
        )

    specs = extract_declared_specs(RelNode)
    prop_names = {s.property for s in specs}
    assert "friend" not in prop_names


def test_extract_no_indexes_returns_empty_set() -> None:
    specs = extract_declared_specs(SchemaNodeNoIndexes)
    assert specs == set()


def test_extract_uses_primary_label() -> None:
    specs = extract_declared_specs(SchemaLocationNode)
    labels = {s.label for s in specs}
    assert labels == {"SchemaLocation"}


def test_extract_combined_indexes() -> None:
    specs = extract_declared_specs(SchemaPersonNode)
    # email: unique=True, index=True → only UNIQUE
    assert IndexSpec("SchemaPerson", "email", "UNIQUE") in specs
    assert IndexSpec("SchemaPerson", "email", "RANGE") not in specs
    # age: index=True → RANGE
    assert IndexSpec("SchemaPerson", "age", "RANGE") in specs
    # bio: fulltext
    assert IndexSpec("SchemaPerson", "bio", "FULLTEXT") in specs
    # name: no index
    assert not any(s.property == "name" for s in specs)


def test_extract_inherits_parent_fields() -> None:
    class ParentNode(Node, labels=["ParentNode"]):
        id: str = Field()
        code: str = Field(unique=True)

    class ChildNode(
        ParentNode, labels=["ParentNode", "ChildNode"], primary_label="ParentNode"
    ):
        extra: str = Field(index=True)

    specs = extract_declared_specs(ChildNode)
    assert IndexSpec("ParentNode", "code", "UNIQUE") in specs
    assert IndexSpec("ParentNode", "extra", "RANGE") in specs


# ---------------------------------------------------------------------------
# parse_existing_specs + IndexManager — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_parse_empty_graph_returns_empty(graph: Any) -> None:
    specs = parse_existing_specs(graph)
    assert specs == set()


@pytest.mark.integration
def test_parse_range_index(graph: Any) -> None:
    graph.create_node_range_index("ParseLabel", "score")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "score", "RANGE") in specs


@pytest.mark.integration
def test_parse_fulltext_index(graph: Any) -> None:
    graph.create_node_fulltext_index("ParseLabel", "bio")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "bio", "FULLTEXT") in specs


@pytest.mark.integration
def test_parse_unique_constraint(graph: Any) -> None:
    graph.create_node_unique_constraint("ParseLabel", "code")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "code", "UNIQUE") in specs


@pytest.mark.integration
def test_unique_backing_range_not_reported_as_extra(graph: Any) -> None:
    """The RANGE index auto-created for a UNIQUE constraint must not appear in parsed specs."""
    graph.create_node_unique_constraint("ParseLabel", "code")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "code", "RANGE") not in specs
    assert IndexSpec("ParseLabel", "code", "UNIQUE") in specs


@pytest.mark.integration
def test_create_indexes_creates_all_declared(graph: Any) -> None:
    class CreateNode(Node, labels=["CreateNode"]):
        id: str = Field()
        email: str = Field(unique=True)
        score: int = Field(index=True)
        bio: str = Field(index_type="FULLTEXT")

    manager = IndexManager(graph)
    manager.create_indexes(CreateNode)

    specs = parse_existing_specs(graph)
    assert IndexSpec("CreateNode", "email", "UNIQUE") in specs
    assert IndexSpec("CreateNode", "score", "RANGE") in specs
    assert IndexSpec("CreateNode", "bio", "FULLTEXT") in specs


@pytest.mark.integration
def test_create_indexes_idempotent(graph: Any) -> None:
    class IdempNode(Node, labels=["IdempNode"]):
        id: str = Field()
        val: int = Field(index=True)

    manager = IndexManager(graph)
    manager.create_indexes(IdempNode)
    # Second call must not raise even though indexes already exist.
    manager.create_indexes(IdempNode)

    specs = parse_existing_specs(graph)
    assert IndexSpec("IdempNode", "val", "RANGE") in specs


@pytest.mark.integration
def test_ensure_indexes_is_idempotent(graph: Any) -> None:
    class EnsureNode(Node, labels=["EnsureNode"]):
        id: str = Field()
        tag: str = Field(index=True)

    manager = IndexManager(graph)
    manager.ensure_indexes(EnsureNode)
    manager.ensure_indexes(EnsureNode)

    specs = parse_existing_specs(graph)
    assert IndexSpec("EnsureNode", "tag", "RANGE") in specs


@pytest.mark.integration
def test_create_indexes_no_index_fields_is_noop(graph: Any) -> None:
    manager = IndexManager(graph)
    manager.create_indexes(SchemaNodeNoIndexes)
    assert parse_existing_specs(graph) == set()


# ---------------------------------------------------------------------------
# IndexManager with generic IndexAdapter (non-FalkorDB path)
# ---------------------------------------------------------------------------


class _MockAdapter:
    """Minimal IndexAdapter stub for unit testing IndexManager dispatch."""

    def __init__(self) -> None:
        from unittest.mock import MagicMock

        self.create_vertex_type = MagicMock()
        self.create_edge_type = MagicMock()
        self.create_range_index = MagicMock()
        self.drop_range_index = MagicMock()
        self.create_fulltext_index = MagicMock()
        self.drop_fulltext_index = MagicMock()
        self.create_vector_index = MagicMock()
        self.drop_vector_index = MagicMock()
        self.create_constraint = MagicMock()
        self.drop_constraint = MagicMock()
        self._existing: set[IndexSpec] = set()

    def get_existing_specs(self) -> set[IndexSpec]:
        return self._existing


class TestIndexManagerWithGenericAdapter:
    def _make_manager(self) -> tuple[IndexManager, _MockAdapter]:
        adapter = _MockAdapter()
        manager = IndexManager(adapter)
        return manager, adapter

    def test_auto_detection_wraps_falkordb_handle(self) -> None:
        from unittest.mock import MagicMock

        from runic.orm.schema.index_manager import FalkorDBIndexAdapter

        fake_graph = MagicMock()
        fake_graph.create_node_range_index = MagicMock()
        manager = IndexManager(fake_graph)
        assert isinstance(manager._adapter, FalkorDBIndexAdapter)  # noqa: SLF001

    def test_generic_adapter_not_wrapped(self) -> None:
        adapter = _MockAdapter()
        manager = IndexManager(adapter)
        assert manager._adapter is adapter  # noqa: SLF001

    def test_create_range_index_dispatched(self) -> None:
        class RangeEntity(Node, labels=["RangeEnt"]):
            id: str = Field()
            score: int = Field(index=True)

        manager, adapter = self._make_manager()
        manager.create_indexes(RangeEntity)
        adapter.create_range_index.assert_called_once_with("RangeEnt", "score")

    def test_create_unique_dispatched(self) -> None:
        class UniqueEntity(Node, labels=["UniqueEnt"]):
            id: str = Field()
            code: str = Field(unique=True)

        manager, adapter = self._make_manager()
        manager.create_indexes(UniqueEntity)
        adapter.create_constraint.assert_called_once_with(
            "UNIQUE", "NODE", "UniqueEnt", ["code"]
        )

    def test_fulltext_batched_by_label(self) -> None:
        class FTEntity(Node, labels=["FTEnt"]):
            id: str = Field()
            title: str = Field(index_type="FULLTEXT")
            body: str = Field(index_type="FULLTEXT")

        manager, adapter = self._make_manager()
        manager.create_indexes(FTEntity)
        # Must be called exactly once, with both props
        assert adapter.create_fulltext_index.call_count == 1
        call_args = adapter.create_fulltext_index.call_args
        assert call_args[0][0] == "FTEnt"
        props_passed = set(call_args[0][1:])
        assert props_passed == {"title", "body"}

    def test_fulltext_skipped_when_already_existing(self) -> None:
        class FTEntity2(Node, labels=["FTEnt2"]):
            id: str = Field()
            bio: str = Field(index_type="FULLTEXT")

        manager, adapter = self._make_manager()
        adapter._existing = {IndexSpec("FTEnt2", "bio", "FULLTEXT")}
        manager.create_indexes(FTEntity2)
        adapter.create_fulltext_index.assert_not_called()

    def test_range_skipped_when_already_existing(self) -> None:
        class RangeExist(Node, labels=["RangeExist"]):
            id: str = Field()
            val: int = Field(index=True)

        manager, adapter = self._make_manager()
        adapter._existing = {IndexSpec("RangeExist", "val", "RANGE")}
        manager.create_indexes(RangeExist)
        adapter.create_range_index.assert_not_called()

    def test_no_indexes_is_noop(self) -> None:
        class NoIdxEnt(Node, labels=["NoIdxEnt"]):
            id: str = Field()
            value: str = Field()

        manager, adapter = self._make_manager()
        manager.create_indexes(NoIdxEnt)
        adapter.create_range_index.assert_not_called()
        adapter.create_fulltext_index.assert_not_called()
        adapter.create_constraint.assert_not_called()

    def test_create_spec_range(self) -> None:
        manager, adapter = self._make_manager()
        manager.create_spec(IndexSpec("Foo", "bar", "RANGE"))
        adapter.create_range_index.assert_called_once_with("Foo", "bar")

    def test_create_spec_unique(self) -> None:
        manager, adapter = self._make_manager()
        manager.create_spec(IndexSpec("Foo", "bar", "UNIQUE"))
        adapter.create_constraint.assert_called_once_with(
            "UNIQUE", "NODE", "Foo", ["bar"]
        )

    def test_create_spec_vector(self) -> None:
        manager, adapter = self._make_manager()
        manager.create_spec(IndexSpec("Foo", "vec", "VECTOR"))
        adapter.create_vector_index.assert_called_once_with("Foo", "vec", 0, "cosine")

    def test_drop_spec_range(self) -> None:
        manager, adapter = self._make_manager()
        manager.drop_spec(IndexSpec("Foo", "bar", "RANGE"))
        adapter.drop_range_index.assert_called_once_with("Foo", "bar")

    def test_drop_spec_unique(self) -> None:
        manager, adapter = self._make_manager()
        manager.drop_spec(IndexSpec("Foo", "bar", "UNIQUE"))
        adapter.drop_constraint.assert_called_once_with(
            "UNIQUE", "NODE", "Foo", ["bar"]
        )

    def test_ensure_indexes_delegates_to_create_indexes(self) -> None:
        class EnsureEnt(Node, labels=["EnsureEnt"]):
            id: str = Field()
            tag: str = Field(index=True)

        manager, adapter = self._make_manager()
        manager.ensure_indexes(EnsureEnt)
        adapter.create_range_index.assert_called_once_with("EnsureEnt", "tag")

    def test_create_indexes_calls_create_vertex_type_for_node(self) -> None:
        class VertexNode(Node, labels=["VertexNode"]):
            id: str = Field()
            score: int = Field(index=True)

        manager, adapter = self._make_manager()
        manager.create_indexes(VertexNode)
        adapter.create_vertex_type.assert_called_once_with("VertexNode")

    def test_create_indexes_calls_create_edge_type_for_edge(self) -> None:
        class KnowsEdge(Edge, type="KNOWS"):
            weight: float = Field()

        manager, adapter = self._make_manager()
        manager.create_indexes(KnowsEdge)
        adapter.create_edge_type.assert_called_once_with("KNOWS")

    def test_vertex_type_called_before_index_ddl(self) -> None:
        """create_vertex_type must be called before any index DDL on the same adapter."""
        from unittest.mock import MagicMock

        class OrderedNode(Node, labels=["OrderedNode"]):
            id: str = Field()
            val: int = Field(index=True)

        parent = MagicMock()
        adapter = _MockAdapter()
        parent.attach_mock(adapter.create_vertex_type, "create_vertex_type")
        parent.attach_mock(adapter.create_range_index, "create_range_index")

        manager = IndexManager(adapter)
        manager.create_indexes(OrderedNode)

        calls = [c[0] for c in parent.mock_calls]
        assert calls.index("create_vertex_type") < calls.index("create_range_index")
