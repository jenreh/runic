"""Tests for SchemaManager: validate_schema, sync_schema, get_schema_diff, get_schema_info."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Edge, Node
from runic.orm.schema.index_manager import IndexSpec, parse_existing_specs
from runic.orm.schema.schema_manager import SchemaManager, ValidationResult

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False


# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class SMPerson(Node, labels=["SMPerson"]):
    id: str = Field()
    email: str = Field(unique=True)
    score: int = Field(index=True)
    bio: str = Field(index_type="FULLTEXT")


class SMLocation(Node, labels=["SMLocation"], primary_label="SMLocation"):
    id: str = Field()
    title: str = Field(index_type="FULLTEXT")


class SMPlain(Node, labels=["SMPlain"]):
    id: str = Field()
    value: str = Field()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph(falkordb_server: Any) -> Any:
    db = falkordb_server
    g = db.select_graph(f"test_sm_{secrets.token_hex(6)}")
    yield g
    with contextlib.suppress(Exception):
        g.delete()


# ---------------------------------------------------------------------------
# ValidationResult — unit tests (no graph)
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
# validate_schema — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validate_empty_entity_no_indexes_is_valid(graph: Any) -> None:
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPlain])
    assert result.is_valid
    assert result.missing_indexes == []
    assert result.extra_indexes == []


@pytest.mark.integration
def test_validate_detects_missing_indexes(graph: Any) -> None:
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPerson])
    assert not result.is_valid
    missing_types = {(s.property, s.index_type) for s in result.missing_indexes}
    assert ("email", "UNIQUE") in missing_types
    assert ("score", "RANGE") in missing_types
    assert ("bio", "FULLTEXT") in missing_types


@pytest.mark.integration
def test_validate_valid_after_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    assert result.is_valid
    assert result.missing_indexes == []
    assert result.extra_indexes == []


@pytest.mark.integration
def test_validate_detects_extra_indexes(graph: Any) -> None:
    # Create an index not declared by any entity we pass to validate_schema.
    graph.create_node_range_index("SMPerson", "not_declared")
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPerson])
    extra_props = {s.property for s in result.extra_indexes}
    assert "not_declared" in extra_props


@pytest.mark.integration
def test_validate_unique_backing_range_not_extra(graph: Any) -> None:
    """A UNIQUE constraint's auto-backing RANGE must not be reported as extra."""
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    extra_props = {s.property for s in result.extra_indexes}
    # 'email' has unique=True; FalkorDB auto-creates RANGE — should not be "extra"
    assert "email" not in extra_props or not any(
        s.property == "email" and s.index_type == "RANGE" for s in result.extra_indexes
    )


@pytest.mark.integration
def test_validate_multiple_entity_classes(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson, SMLocation])
    result = schema.validate_schema([SMPerson, SMLocation])
    assert result.is_valid


# ---------------------------------------------------------------------------
# sync_schema — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sync_creates_missing_indexes(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    specs = parse_existing_specs(graph)
    assert IndexSpec("SMPerson", "email", "UNIQUE") in specs
    assert IndexSpec("SMPerson", "score", "RANGE") in specs
    assert IndexSpec("SMPerson", "bio", "FULLTEXT") in specs


@pytest.mark.integration
def test_sync_is_idempotent(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    # A second sync must not raise; should be a no-op.
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    assert result.is_valid


@pytest.mark.integration
def test_sync_drops_extra_when_requested(graph: Any) -> None:
    graph.create_node_range_index("SMPerson", "stray_field")
    schema = SchemaManager(graph)
    # Ensure base indexes are present first.
    schema.sync_schema([SMPerson])
    result_before = schema.validate_schema([SMPerson])
    assert any(s.property == "stray_field" for s in result_before.extra_indexes)

    schema.sync_schema([SMPerson], drop_extra=True)
    specs = parse_existing_specs(graph)
    assert IndexSpec("SMPerson", "stray_field", "RANGE") not in specs


@pytest.mark.integration
def test_sync_does_not_drop_extra_by_default(graph: Any) -> None:
    graph.create_node_range_index("SMPlain", "extra_prop")
    schema = SchemaManager(graph)
    schema.sync_schema([SMPlain])  # drop_extra=False by default
    specs = parse_existing_specs(graph)
    # Extra index must still be there.
    assert IndexSpec("SMPlain", "extra_prop", "RANGE") in specs


# ---------------------------------------------------------------------------
# get_schema_diff — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_schema_diff_in_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPlain])
    diff = schema.get_schema_diff([SMPlain])
    assert "in sync" in diff.lower()


@pytest.mark.integration
def test_get_schema_diff_shows_missing(graph: Any) -> None:
    schema = SchemaManager(graph)
    diff = schema.get_schema_diff([SMPerson])
    assert "MISSING" in diff
    assert "email" in diff


@pytest.mark.integration
def test_get_schema_diff_shows_extra(graph: Any) -> None:
    graph.create_node_range_index("SMPlain", "ghost")
    schema = SchemaManager(graph)
    diff = schema.get_schema_diff([SMPlain])
    assert "EXTRA" in diff
    assert "ghost" in diff


# ---------------------------------------------------------------------------
# get_schema_info — integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_schema_info_structure(graph: Any) -> None:
    schema = SchemaManager(graph)
    info = schema.get_schema_info([SMPerson])
    assert hasattr(info, "is_valid")
    assert hasattr(info, "declared_count")
    assert hasattr(info, "existing_count")
    assert hasattr(info, "missing_count")
    assert hasattr(info, "extra_count")
    assert hasattr(info, "missing")
    assert hasattr(info, "extra")
    assert hasattr(info, "errors")


@pytest.mark.integration
def test_get_schema_info_after_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    info = schema.get_schema_info([SMPerson])
    assert info.is_valid is True
    assert info.missing_count == 0
    assert info.extra_count == 0


@pytest.mark.integration
def test_get_schema_info_missing_count(graph: Any) -> None:
    schema = SchemaManager(graph)
    info = schema.get_schema_info([SMPerson])
    assert info.missing_count > 0
    assert info.declared_count > 0


# ---------------------------------------------------------------------------
# Unit tests with mock adapter (non-FalkorDB path)
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


class SMPersonMock(Node, labels=["SMPersonMock"]):
    id: str = Field()
    email: str = Field(unique=True)
    score: int = Field(index=True)


class SMKnowsEdge(Edge, type="SM_KNOWS"):
    weight: float = Field()


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
