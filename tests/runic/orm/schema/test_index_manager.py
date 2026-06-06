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
