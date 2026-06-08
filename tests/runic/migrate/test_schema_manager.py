"""Unit tests for SchemaManager: ValidationResult and mock-adapter dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

from runic.migrate.schema import SchemaManager, ValidationResult
from runic.ogm.core.descriptors import Field
from runic.ogm.core.models import Edge, Node
from runic.ogm.schema.index_manager import IndexSpec

# ---------------------------------------------------------------------------
# _MockSchemaAdapter
# ---------------------------------------------------------------------------


class _MockSchemaAdapter:
    """Minimal adapter stub for SchemaManager unit tests."""

    def __init__(self) -> None:
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

    def get_existing_specs(self) -> set[IndexSpec]:
        return set()


# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class SMPersonMock(Node, labels=["SMPersonMock"]):
    id: str = Field()
    email: str = Field(unique=True)
    score: int = Field(index=True)


class SMKnowsEdge(Edge, type="SM_KNOWS"):
    weight: float = Field()


# ---------------------------------------------------------------------------
# ValidationResult — unit tests
# ---------------------------------------------------------------------------


def test_validation_result_valid() -> None:
    r = ValidationResult(is_valid=True)
    assert r.is_valid
    assert r.missing_indexes == []
    assert r.extra_indexes == []
    assert r.errors == []


def test_validation_result_invalid() -> None:
    missing = [IndexSpec("L", "p", "RANGE")]
    r = ValidationResult(is_valid=False, missing_indexes=missing)
    assert not r.is_valid
    assert r.missing_indexes == missing


# ---------------------------------------------------------------------------
# SchemaManager with mock adapter
# ---------------------------------------------------------------------------


class TestSchemaManagerWithMockAdapter:
    def _make_schema(self) -> tuple[SchemaManager, _MockSchemaAdapter]:
        adapter = _MockSchemaAdapter()
        schema = SchemaManager(adapter)
        return schema, adapter

    def test_generic_adapter_stored_directly(self) -> None:
        schema, adapter = self._make_schema()
        assert schema._adapter is adapter  # noqa: SLF001

    def test_sync_schema_calls_ensure_entity_types_for_node(self) -> None:
        schema, adapter = self._make_schema()
        schema.sync_schema([SMPersonMock])
        adapter.create_vertex_type.assert_called_with("SMPersonMock")

    def test_sync_schema_calls_create_vertex_type_before_index_ddl(self) -> None:
        parent = MagicMock()
        adapter = _MockSchemaAdapter()
        parent.attach_mock(adapter.create_vertex_type, "create_vertex_type")
        parent.attach_mock(adapter.create_range_index, "create_range_index")

        schema = SchemaManager(adapter)
        schema.sync_schema([SMPersonMock])

        calls = [c[0] for c in parent.mock_calls]
        assert calls.index("create_vertex_type") < calls.index("create_range_index")

    def test_ensure_entity_types_node_dispatches_create_vertex_type(self) -> None:
        schema, adapter = self._make_schema()
        schema.ensure_entity_types([SMPersonMock])
        adapter.create_vertex_type.assert_called_once_with("SMPersonMock")
        adapter.create_edge_type.assert_not_called()

    def test_ensure_entity_types_edge_dispatches_create_edge_type(self) -> None:
        schema, adapter = self._make_schema()
        schema.ensure_entity_types([SMKnowsEdge])
        adapter.create_edge_type.assert_called_once_with("SM_KNOWS")
        adapter.create_vertex_type.assert_not_called()

    def test_ensure_entity_types_mixed(self) -> None:
        schema, adapter = self._make_schema()
        schema.ensure_entity_types([SMPersonMock, SMKnowsEdge])
        adapter.create_vertex_type.assert_called_once_with("SMPersonMock")
        adapter.create_edge_type.assert_called_once_with("SM_KNOWS")

    def test_validate_schema_returns_all_declared_as_missing(self) -> None:
        schema, _ = self._make_schema()
        result = schema.validate_schema([SMPersonMock])
        assert not result.is_valid
        missing_types = {(s.property, s.index_type) for s in result.missing_indexes}
        assert ("email", "UNIQUE") in missing_types
        assert ("score", "RANGE") in missing_types
