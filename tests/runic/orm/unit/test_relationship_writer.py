"""Unit tests for RelationshipWriter Cypher generation and Session mutation methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, FieldInfo, Relation
from runic.orm.core.models import Edge, Node
from runic.orm.mapper.mapper import Mapper
from runic.orm.mapper.relationship_writer import (
    RelationshipWriter,
    _node_match_clause,
    _rel_clause,
)
from runic.orm.session.session import Session

# ---------------------------------------------------------------------------
# Model definitions (unique labels to avoid collision with other test files)
# ---------------------------------------------------------------------------


class WrCompany(Node, labels=["WrCompany"]):
    id: str = Field()
    name: str = Field()


class WrMemberEdge(Edge, type="MEMBER_OF"):
    role: str
    since: str | None = None


class WrPerson(Node, labels=["WrPerson"]):
    id: str = Field()
    name: str = Field()
    company: WrCompany | None = Relation(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="WrCompany",
    )
    colleagues: list[WrPerson] = Relation(
        relationship="KNOWS",
        direction="OUTGOING",
        target="WrPerson",
    )
    managed_by: WrPerson | None = Relation(
        relationship="MANAGED_BY",
        direction="INCOMING",
        target="WrPerson",
    )
    linked: WrCompany | None = Relation(
        relationship="LINKED",
        direction="BOTH",
        target="WrCompany",
    )
    member_of: WrCompany | None = Relation(
        relationship="MEMBER_OF",
        direction="OUTGOING",
        target="WrCompany",
        edge_model=WrMemberEdge,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mapper() -> Mapper:
    from runic.orm.core.metadata import metadata

    return Mapper(metadata)


def _make_writer() -> tuple[RelationshipWriter, Mapper]:
    mapper = _make_mapper()
    writer = RelationshipWriter(mapper.meta, mapper)
    return writer, mapper


def _fi(person_cls: type, field_name: str) -> FieldInfo:
    return next(f for f in person_cls._fields if f.name == field_name)


# ---------------------------------------------------------------------------
# _node_match_clause
# ---------------------------------------------------------------------------


def test_node_match_clause_explicit_pk() -> None:
    from runic.orm.core.metadata import metadata

    node_meta = metadata.get_node_meta(WrCompany)
    assert node_meta is not None
    clause = _node_match_clause("a", node_meta, "__pk", generated=False)
    assert clause == "MATCH (a:WrCompany {id: $__pk})"


def test_node_match_clause_generated_pk() -> None:
    from runic.orm.core.metadata import metadata

    node_meta = metadata.get_node_meta(WrCompany)
    assert node_meta is not None
    clause = _node_match_clause("a", node_meta, "__pk", generated=True)
    assert clause == "MATCH (a:WrCompany) WHERE id(a) = toInteger($__pk)"


# ---------------------------------------------------------------------------
# _rel_clause
# ---------------------------------------------------------------------------


def test_rel_clause_merge_outgoing() -> None:
    clause = _rel_clause("MERGE", "a", "b", "WORKS_FOR", "OUTGOING", "r")
    assert clause == "MERGE (a)-[r:WORKS_FOR]->(b)"


def test_rel_clause_match_incoming() -> None:
    clause = _rel_clause("MATCH", "a", "b", "MANAGED_BY", "INCOMING", "r")
    assert clause == "MATCH (a)<-[r:MANAGED_BY]-(b)"


def test_rel_clause_both() -> None:
    clause = _rel_clause("MATCH", "a", "b", "LINKED", "BOTH", "r")
    assert clause == "MATCH (a)-[r:LINKED]-(b)"


# ---------------------------------------------------------------------------
# RelationshipWriter.build_relate_query — no edge
# ---------------------------------------------------------------------------


def test_build_relate_no_edge_outgoing() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "company")

    cypher, params = writer.build_relate_query(source, fi, target, edge=None)

    assert "MATCH (a:WrPerson {id: $__src_pk})" in cypher
    assert "MATCH (b:WrCompany {id: $__tgt_pk})" in cypher
    assert "MERGE (a)-[r:WORKS_FOR]->(b)" in cypher
    assert "SET" not in cypher
    assert params == {"__src_pk": "p1", "__tgt_pk": "c1"}


def test_build_relate_no_edge_incoming() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrPerson(id="p2", name="Bob")
    fi = _fi(WrPerson, "managed_by")

    cypher, params = writer.build_relate_query(source, fi, target, edge=None)

    assert "MERGE (a)<-[r:MANAGED_BY]-(b)" in cypher
    assert params == {"__src_pk": "p1", "__tgt_pk": "p2"}


def test_build_relate_no_edge_both() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "linked")

    cypher, params = writer.build_relate_query(source, fi, target, edge=None)

    assert "MERGE (a)-[r:LINKED]-(b)" in cypher


# ---------------------------------------------------------------------------
# RelationshipWriter.build_relate_query — with edge
# ---------------------------------------------------------------------------


def test_build_relate_with_edge_props() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "member_of")
    edge = WrMemberEdge(role="admin", since="2024-01-01")

    cypher, params = writer.build_relate_query(source, fi, target, edge=edge)

    assert "MERGE (a)-[r:MEMBER_OF]->(b)" in cypher
    assert "r.role = $__e_role" in cypher
    assert "r.since = $__e_since" in cypher
    assert params["__e_role"] == "admin"
    assert params["__e_since"] == "2024-01-01"
    assert params["__src_pk"] == "p1"
    assert params["__tgt_pk"] == "c1"


def test_build_relate_with_edge_skips_none_props() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "member_of")
    edge = WrMemberEdge(role="viewer")  # since=None (optional)

    cypher, params = writer.build_relate_query(source, fi, target, edge=edge)

    assert "r.role = $__e_role" in cypher
    assert "__e_since" not in params


def test_build_relate_with_empty_edge_no_set_clause() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    # Edge with all-None props produces no SET clause
    class EmptyEdge(Edge, type="EMPTY_E"):
        val: str | None = None

    fi = _fi(WrPerson, "company")  # reuse WORKS_FOR fi for structure
    edge = EmptyEdge()
    cypher, _ = writer.build_relate_query(source, fi, target, edge=edge)
    assert "SET" not in cypher


# ---------------------------------------------------------------------------
# RelationshipWriter.build_unrelate_query
# ---------------------------------------------------------------------------


def test_build_unrelate_outgoing() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "company")

    cypher, params = writer.build_unrelate_query(source, fi, target)

    assert "MATCH (a:WrPerson {id: $__src_pk})" in cypher
    assert "MATCH (b:WrCompany {id: $__tgt_pk})" in cypher
    assert "MATCH (a)-[r:WORKS_FOR]->(b)" in cypher
    assert "DELETE r" in cypher
    assert params == {"__src_pk": "p1", "__tgt_pk": "c1"}


def test_build_unrelate_incoming() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrPerson(id="p2", name="Bob")
    fi = _fi(WrPerson, "managed_by")

    cypher, params = writer.build_unrelate_query(source, fi, target)

    assert "MATCH (a)<-[r:MANAGED_BY]-(b)" in cypher
    assert "DELETE r" in cypher


def test_build_unrelate_both_direction() -> None:
    writer, _ = _make_writer()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    fi = _fi(WrPerson, "linked")

    cypher, _ = writer.build_unrelate_query(source, fi, target)

    assert "MATCH (a)-[r:LINKED]-(b)" in cypher
    assert "DELETE r" in cypher


# ---------------------------------------------------------------------------
# RelationshipWriter._encode_edge_props
# ---------------------------------------------------------------------------


def test_encode_edge_props_all_set() -> None:
    writer, _ = _make_writer()
    edge = WrMemberEdge(role="admin", since="2024-01-01")
    props = writer._encode_edge_props(edge)
    assert props == {"role": "admin", "since": "2024-01-01"}


def test_encode_edge_props_skips_none() -> None:
    writer, _ = _make_writer()
    edge = WrMemberEdge(role="viewer")
    props = writer._encode_edge_props(edge)
    assert "since" not in props
    assert props["role"] == "viewer"


def test_encode_edge_props_no_fields() -> None:
    writer, _ = _make_writer()
    props = writer._encode_edge_props(object())
    assert props == {}


# ---------------------------------------------------------------------------
# Session.relate / Session.unrelate — with mocked graph
# ---------------------------------------------------------------------------


def _make_session() -> tuple[Session, MagicMock]:
    mock_graph = MagicMock()
    mock_graph.query.return_value = MagicMock(result_set=[])
    session = Session(mock_graph)
    return session, mock_graph


def test_session_relate_executes_query() -> None:
    session, mock_graph = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    session.relate(source, "company", target)

    mock_graph.query.assert_called_once()
    cypher, params = mock_graph.query.call_args[0]
    assert "MERGE" in cypher
    assert "WORKS_FOR" in cypher
    assert params["__src_pk"] == "p1"
    assert params["__tgt_pk"] == "c1"


def test_session_relate_invalidates_cache() -> None:
    session, _ = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    source.__dict__["company"] = target  # simulate previously cached

    session.relate(source, "company", target)

    assert source.__dict__["company"] is _NOT_LOADED


def test_session_relate_with_edge() -> None:
    session, mock_graph = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    edge = WrMemberEdge(role="admin")

    session.relate(source, "member_of", target, edge=edge)

    cypher, params = mock_graph.query.call_args[0]
    assert "SET" in cypher
    assert params["__e_role"] == "admin"


def test_session_unrelate_executes_query() -> None:
    session, mock_graph = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    session.unrelate(source, "company", target)

    cypher, params = mock_graph.query.call_args[0]
    assert "DELETE r" in cypher
    assert "WORKS_FOR" in cypher
    assert params["__src_pk"] == "p1"


def test_session_unrelate_invalidates_cache() -> None:
    session, _ = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")
    source.__dict__["company"] = target

    session.unrelate(source, "company", target)

    assert source.__dict__["company"] is _NOT_LOADED


def test_session_relate_raises_for_non_relation_field() -> None:
    session, _ = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    with pytest.raises(TypeError, match="no Relation field named 'name'"):
        session.relate(source, "name", target)


def test_session_relate_raises_for_unknown_field() -> None:
    session, _ = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    with pytest.raises(TypeError, match="no Relation field named 'nonexistent'"):
        session.relate(source, "nonexistent", target)


def test_session_unrelate_raises_for_non_relation_field() -> None:
    session, _ = _make_session()
    source = WrPerson(id="p1", name="Alice")
    target = WrCompany(id="c1", name="Acme")

    with pytest.raises(TypeError, match="no Relation field named 'id'"):
        session.unrelate(source, "id", target)
