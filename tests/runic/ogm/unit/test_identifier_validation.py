"""Identifier-validation chokepoints guarding against Cypher injection (S6/S7).

Labels, edge types, and relationship types come from model definitions and are
interpolated directly into Cypher patterns, so they are validated once at
definition time.  DataOperations validates its runtime label/property args.
"""

from unittest.mock import MagicMock

import pytest

from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.models import Edge, Node
from runic.ogm.operations import DataOperations


def test_node_with_injection_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid Cypher node label"):

        class _Evil(Node, labels=["Person) DETACH DELETE n //"]):
            id: str = Field(primary_key=True)


def test_edge_with_injection_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid Cypher edge type"):

        class _EvilEdge(Edge, type="KNOWS]->() DELETE n //"):
            since: int = Field(default=0)


def test_relation_with_injection_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid Cypher relationship type"):
        Relation(
            relationship="KNOWS]-() DELETE n //",
            direction="OUTGOING",
            target="Person",
        )


def test_rename_property_rejects_injection_identifiers() -> None:
    ops = DataOperations(MagicMock())
    with pytest.raises(ValueError, match="invalid Cypher"):
        ops.rename_property("Person", "old`) DETACH DELETE n //", "new")


def test_relabel_nodes_rejects_injection_identifiers() -> None:
    ops = DataOperations(MagicMock())
    with pytest.raises(ValueError, match="invalid Cypher node label"):
        ops.relabel_nodes("Old", "New) DETACH DELETE n //")
