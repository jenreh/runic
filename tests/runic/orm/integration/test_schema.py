"""Integration tests for IndexManager and SchemaManager against a live FalkorDB graph."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.schema.index_manager import (
    IndexManager,
    IndexSpec,
    parse_existing_specs,
)
from runic.orm.schema.schema_manager import SchemaManager

_integration = pytest.mark.integration

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


class _IntNoIdx(Node, labels=["IntNoIdx"]):
    """Node with no indexed fields — used to assert create_indexes is a no-op."""

    id: str
    value: str


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def graph(falkordb_server: Any) -> Any:
    db = falkordb_server
    g = db.select_graph(f"test_schema_{secrets.token_hex(6)}")
    yield g
    with contextlib.suppress(Exception):
        g.delete()


# ---------------------------------------------------------------------------
# parse_existing_specs — integration tests
# ---------------------------------------------------------------------------


@_integration
def test_parse_empty_graph_returns_empty(graph: Any) -> None:
    specs = parse_existing_specs(graph)
    assert specs == set()


@_integration
def test_parse_range_index(graph: Any) -> None:
    graph.create_node_range_index("ParseLabel", "score")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "score", "RANGE") in specs


@_integration
def test_parse_fulltext_index(graph: Any) -> None:
    graph.create_node_fulltext_index("ParseLabel", "bio")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "bio", "FULLTEXT") in specs


@_integration
def test_parse_unique_constraint(graph: Any) -> None:
    graph.create_node_unique_constraint("ParseLabel", "code")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "code", "UNIQUE") in specs


@_integration
def test_unique_backing_range_not_reported_as_extra(graph: Any) -> None:
    """The RANGE index auto-created for a UNIQUE constraint must not appear in parsed specs."""
    graph.create_node_unique_constraint("ParseLabel", "code")
    specs = parse_existing_specs(graph)
    assert IndexSpec("ParseLabel", "code", "RANGE") not in specs
    assert IndexSpec("ParseLabel", "code", "UNIQUE") in specs


# ---------------------------------------------------------------------------
# IndexManager.create_indexes — integration tests
# ---------------------------------------------------------------------------


@_integration
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


@_integration
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


@_integration
def test_ensure_indexes_is_idempotent(graph: Any) -> None:
    class EnsureNode(Node, labels=["EnsureNode"]):
        id: str = Field()
        tag: str = Field(index=True)

    manager = IndexManager(graph)
    manager.ensure_indexes(EnsureNode)
    manager.ensure_indexes(EnsureNode)

    specs = parse_existing_specs(graph)
    assert IndexSpec("EnsureNode", "tag", "RANGE") in specs


@_integration
def test_create_indexes_no_index_fields_is_noop(graph: Any) -> None:
    manager = IndexManager(graph)
    manager.create_indexes(_IntNoIdx)
    assert parse_existing_specs(graph) == set()


# ---------------------------------------------------------------------------
# SchemaManager.validate_schema — integration tests
# ---------------------------------------------------------------------------


@_integration
def test_validate_empty_entity_no_indexes_is_valid(graph: Any) -> None:
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPlain])
    assert result.is_valid
    assert result.missing_indexes == []
    assert result.extra_indexes == []


@_integration
def test_validate_detects_missing_indexes(graph: Any) -> None:
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPerson])
    assert not result.is_valid
    missing_types = {(s.property, s.index_type) for s in result.missing_indexes}
    assert ("email", "UNIQUE") in missing_types
    assert ("score", "RANGE") in missing_types
    assert ("bio", "FULLTEXT") in missing_types


@_integration
def test_validate_valid_after_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    assert result.is_valid
    assert result.missing_indexes == []
    assert result.extra_indexes == []


@_integration
def test_validate_detects_extra_indexes(graph: Any) -> None:
    # Create an index not declared by any entity we pass to validate_schema.
    graph.create_node_range_index("SMPerson", "not_declared")
    schema = SchemaManager(graph)
    result = schema.validate_schema([SMPerson])
    extra_props = {s.property for s in result.extra_indexes}
    assert "not_declared" in extra_props


@_integration
def test_validate_unique_backing_range_not_extra(graph: Any) -> None:
    """A UNIQUE constraint's auto-backing RANGE must not be reported as extra."""
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    extra_props = {s.property for s in result.extra_indexes}
    assert "email" not in extra_props or not any(
        s.property == "email" and s.index_type == "RANGE" for s in result.extra_indexes
    )


@_integration
def test_validate_multiple_entity_classes(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson, SMLocation])
    result = schema.validate_schema([SMPerson, SMLocation])
    assert result.is_valid


# ---------------------------------------------------------------------------
# SchemaManager.sync_schema — integration tests
# ---------------------------------------------------------------------------


@_integration
def test_sync_creates_missing_indexes(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    specs = parse_existing_specs(graph)
    assert IndexSpec("SMPerson", "email", "UNIQUE") in specs
    assert IndexSpec("SMPerson", "score", "RANGE") in specs
    assert IndexSpec("SMPerson", "bio", "FULLTEXT") in specs


@_integration
def test_sync_is_idempotent(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    # A second sync must not raise; should be a no-op.
    schema.sync_schema([SMPerson])
    result = schema.validate_schema([SMPerson])
    assert result.is_valid


@_integration
def test_sync_drops_extra_when_requested(graph: Any) -> None:
    graph.create_node_range_index("SMPerson", "stray_field")
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    result_before = schema.validate_schema([SMPerson])
    assert any(s.property == "stray_field" for s in result_before.extra_indexes)

    schema.sync_schema([SMPerson], drop_extra=True)
    specs = parse_existing_specs(graph)
    assert IndexSpec("SMPerson", "stray_field", "RANGE") not in specs


@_integration
def test_sync_does_not_drop_extra_by_default(graph: Any) -> None:
    graph.create_node_range_index("SMPlain", "extra_prop")
    schema = SchemaManager(graph)
    schema.sync_schema([SMPlain])  # drop_extra=False by default
    specs = parse_existing_specs(graph)
    assert IndexSpec("SMPlain", "extra_prop", "RANGE") in specs


# ---------------------------------------------------------------------------
# SchemaManager.get_schema_diff — integration tests
# ---------------------------------------------------------------------------


@_integration
def test_get_schema_diff_in_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPlain])
    diff = schema.get_schema_diff([SMPlain])
    assert "in sync" in diff.lower()


@_integration
def test_get_schema_diff_shows_missing(graph: Any) -> None:
    schema = SchemaManager(graph)
    diff = schema.get_schema_diff([SMPerson])
    assert "MISSING" in diff
    assert "email" in diff


@_integration
def test_get_schema_diff_shows_extra(graph: Any) -> None:
    graph.create_node_range_index("SMPlain", "ghost")
    schema = SchemaManager(graph)
    diff = schema.get_schema_diff([SMPlain])
    assert "EXTRA" in diff
    assert "ghost" in diff


# ---------------------------------------------------------------------------
# SchemaManager.get_schema_info — integration tests
# ---------------------------------------------------------------------------


@_integration
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


@_integration
def test_get_schema_info_after_sync(graph: Any) -> None:
    schema = SchemaManager(graph)
    schema.sync_schema([SMPerson])
    info = schema.get_schema_info([SMPerson])
    assert info.is_valid is True
    assert info.missing_count == 0
    assert info.extra_count == 0


@_integration
def test_get_schema_info_missing_count(graph: Any) -> None:
    schema = SchemaManager(graph)
    info = schema.get_schema_info([SMPerson])
    assert info.missing_count > 0
    assert info.declared_count > 0
