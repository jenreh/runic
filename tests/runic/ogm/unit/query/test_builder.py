"""Unit tests for runic.ogm.query.builder — Cypher generation and decoding.

Tests use a MagicMock session with real MetaData so generated Cypher can be
verified without a live FalkorDB connection.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.core.models import Edge, Node
from runic.ogm.core.types import (
    GeoLocation,
    Vector,
)
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.expressions import count
from runic.ogm.query.specialised import FulltextQueryBuilder, VectorQueryBuilder

# ---------------------------------------------------------------------------
# Test models (unique labels to avoid collisions)
# ---------------------------------------------------------------------------


class BPerson(Node, labels=["BPerson"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    age: int | None = Field(default=None)
    active: bool = Field(default=True)
    deleted_at: str | None = Field(default=None)


class BPost(Node, labels=["BPost"]):
    id: str = Field(primary_key=True)
    title: str = Field()
    published: bool = Field(default=False)


class BCompany(Node, labels=["BCompany"]):
    id: str = Field(primary_key=True)
    name: str = Field()


class WorksFor(Edge, type="BWORKS_FOR"):
    since: int | None = Field(default=None)


class BPersonWithRel(Node, labels=["BPersonWithRel"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    works_for: BCompany | None = Relation(
        relationship="BWORKS_FOR",
        direction="OUTGOING",
        target="BCompany",
        edge_model="WorksFor",
    )
    friends: list[BPersonWithRel] = Relation(
        relationship="BKNOWS",
        direction="OUTGOING",
        target="BPersonWithRel",
    )
    reports_to: BPersonWithRel | None = Relation(
        relationship="BREPORTS_TO",
        direction="OUTGOING",
        target="BPersonWithRel",
    )


class BDocument(Node, labels=["BDocument"]):
    id: str = Field(primary_key=True)
    text: str = Field()
    embedding: Vector = Field(index_type="VECTOR")
    location: GeoLocation | None = Field(default=None)


class BArticle(Node, labels=["BArticle"]):
    id: str = Field(primary_key=True)
    title: str = Field(index_type="FULLTEXT")


_real_meta.finalize()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _mock_session() -> Any:
    """Return a MagicMock session wired to the real MetaData and a real Mapper."""
    mapper = Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


# ---------------------------------------------------------------------------
# Basic Cypher generation
# ---------------------------------------------------------------------------


class TestBasicQueries:
    def test_match_all(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        cypher, params = q.build()
        assert "MATCH (n:BPerson)" in cypher
        assert "RETURN n" in cypher
        assert params == {}

    def test_where_equality(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        cypher, params = q.build()
        assert "WHERE n.name = $p0" in cypher
        assert params["p0"] == "Alice"

    def test_where_comparison(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.age > 18)  # ty: ignore[unsupported-operator]
        cypher, params = q.build()
        assert "WHERE n.age > $p0" in cypher
        assert params["p0"] == 18

    def test_where_multiple_conditions_use_and(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        q.where(BPerson.age > 18)  # ty: ignore[unsupported-operator]
        cypher, params = q.build()
        assert "WHERE" in cypher
        assert "AND" in cypher
        assert "p0" in params
        assert "p1" in params

    def test_where_contains(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name.contains("lic"))  # ty: ignore[unresolved-attribute]
        cypher, params = q.build()
        assert "n.name CONTAINS $p0" in cypher

    def test_where_starts_with(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name.startswith("A"))  # ty: ignore[invalid-argument-type]
        cypher, params = q.build()
        assert "STARTS WITH" in cypher

    def test_where_is_null(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.deleted_at.is_null())  # ty: ignore[unresolved-attribute]
        cypher, params = q.build()
        assert "n.deleted_at IS NULL" in cypher
        assert params == {}

    def test_where_is_not_null(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.deleted_at.is_not_null())  # ty: ignore[unresolved-attribute]
        cypher, params = q.build()
        assert "n.deleted_at IS NOT NULL" in cypher

    def test_where_in_list(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name.in_(["Alice", "Bob"]))  # ty: ignore[unresolved-attribute]
        cypher, params = q.build()
        assert "n.name IN $p0" in cypher
        assert params["p0"] == ["Alice", "Bob"]

    def test_where_not_in(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name.not_in_(["spam"]))  # ty: ignore[unresolved-attribute]
        cypher, params = q.build()
        assert "NOT n.name IN $p0" in cypher

    def test_where_compound_and(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where((BPerson.age > 18) & (BPerson.active == True))  # noqa: E712  # ty: ignore[unsupported-operator]
        cypher, _ = q.build()
        assert "AND" in cypher

    def test_where_compound_or(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where((BPerson.name == "Alice") | (BPerson.name == "Bob"))  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "OR" in cypher

    def test_where_not(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(~(BPerson.active == True))  # noqa: E712  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "NOT" in cypher

    def test_order_by_asc(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.order_by(BPerson.name)
        cypher, _ = q.build()
        assert "ORDER BY n.name ASC" in cypher

    def test_order_by_desc(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.order_by(BPerson.age, desc=True)  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "ORDER BY n.age DESC" in cypher

    def test_limit(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.limit(10)
        cypher, _ = q.build()
        assert "LIMIT 10" in cypher

    def test_skip(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.skip(5).limit(10)
        cypher, _ = q.build()
        assert "SKIP 5" in cypher
        assert "LIMIT 10" in cypher

    def test_distinct(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.distinct()
        cypher, _ = q.build()
        assert "RETURN DISTINCT n" in cypher

    def test_params_are_fresh_on_rebuild(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.where(BPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        _, p1 = q.build()
        _, p2 = q.build()
        assert p1 == p2


# ---------------------------------------------------------------------------
# Alias
# ---------------------------------------------------------------------------


class TestAlias:
    def test_alias_changes_root_variable(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.alias("u")
        cypher, _ = q.build()
        assert "MATCH (u:BPerson)" in cypher
        assert "RETURN u" in cypher

    def test_where_on_explicit_alias(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.alias("u")
        q.where(BPerson.name == "Alice", on="u")  # ty: ignore[invalid-argument-type]
        cypher, params = q.build()
        assert "u.name = $p0" in cypher

    def test_where_without_on_uses_cls_alias(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.alias("u")
        q.where(BPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "u.name = $p0" in cypher


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_single_hop_optional_match(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.friends).alias("f")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "OPTIONAL MATCH (u)-[:BKNOWS]->(f:BPersonWithRel)" in cypher
        assert "RETURN f" in cypher

    def test_required_match(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.friends, optional=False).alias("f")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert cypher.count("OPTIONAL MATCH") == 0
        assert "MATCH (u)-[:BKNOWS]->(f:BPersonWithRel)" in cypher

    def test_traversal_with_edge_alias(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.works_for, edge_alias="r").alias("c")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "OPTIONAL MATCH (u)-[r:BWORKS_FOR]->(c:BCompany)" in cypher

    def test_traversal_where_on_edge(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.works_for, edge_alias="r").alias("c")  # ty: ignore[invalid-argument-type]
        q.where(WorksFor.since > 2020, on="r")  # ty: ignore[unsupported-operator]
        cypher, params = q.build()
        assert "r.since > $p0" in cypher
        assert params["p0"] == 2020

    def test_multi_hop_traversal(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.friends).alias("f")  # ty: ignore[invalid-argument-type]
        q.traverse(BPersonWithRel.friends).alias("ff")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert cypher.count("OPTIONAL MATCH") == 2
        assert "(u)-[:BKNOWS]->(f:" in cypher
        assert "(f)-[:BKNOWS]->(ff:" in cypher

    def test_variable_length_path(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("p").repeat(BPersonWithRel.reports_to, min_hops=1, max_hops=5).alias(  # ty: ignore[invalid-argument-type]
            "anc"
        )
        cypher, _ = q.build()
        assert "*1..5" in cypher
        assert "MATCH (p)-[:BREPORTS_TO*1..5]->(anc:" in cypher

    def test_variable_length_unbounded(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("p").repeat(BPersonWithRel.reports_to, min_hops=1).alias("anc")  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "*1.." in cypher

    def test_return_target_explicit(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.friends).alias("f")  # ty: ignore[invalid-argument-type]
        q.return_target("u")
        cypher, _ = q.build()
        assert "RETURN u" in cypher

    def test_return_nodes(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.works_for, edge_alias="r").alias("c")  # ty: ignore[invalid-argument-type]
        q.return_nodes("u", "c").return_edge("r")
        cypher, _ = q.build()
        assert "u" in cypher
        assert "r" in cypher
        assert "c" in cypher


# ---------------------------------------------------------------------------
# WITH clause
# ---------------------------------------------------------------------------


class TestWithClause:
    def test_with_inserts_between_match_and_where(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.alias("u").where(BPerson.active == True).with_("u")  # noqa: E712  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "WITH u" in cypher
        lines = cypher.splitlines()
        with_line = next(i for i, l in enumerate(lines) if "WITH u" in l)
        where_line = next(i for i, l in enumerate(lines) if "WHERE" in l)
        assert with_line < where_line


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_count_star_return(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.aggregate(count().as_("total"))
        cypher, _ = q.build()
        assert "RETURN count(*) AS total" in cypher

    def test_group_by_alias(self) -> None:
        q = QueryBuilder(_mock_session(), BPersonWithRel)
        q.alias("u").traverse(BPersonWithRel.friends)  # ty: ignore[invalid-argument-type]
        q.aggregate(count("*").as_("friend_count"), group_by="u")
        cypher, _ = q.build()
        assert "RETURN u, count(*) AS friend_count" in cypher

    def test_count_via_terminal(self) -> None:
        mock_result = MagicMock()
        mock_result.rows = [[5]]
        sess = _mock_session()
        sess.execute.return_value = mock_result
        q = QueryBuilder(sess, BPerson)
        result = q.count()
        assert result == 5
        called_cypher = sess.execute.call_args[0][0]
        assert "count(*)" in called_cypher


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class TestProjection:
    def test_project_single_field(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.project(BPerson.name)
        cypher, _ = q.build()
        assert "RETURN n.name" in cypher

    def test_project_multiple_fields(self) -> None:
        q = QueryBuilder(_mock_session(), BPerson)
        q.project(BPerson.name, BPerson.age)  # ty: ignore[invalid-argument-type]
        cypher, _ = q.build()
        assert "n.name" in cypher
        assert "n.age" in cypher


# ---------------------------------------------------------------------------
# TypeConverter in WHERE
# ---------------------------------------------------------------------------


class TestTypeConverterInWhere:
    def test_geolocation_wraps_param_ref(self) -> None:
        q = QueryBuilder(_mock_session(), BDocument)
        loc = GeoLocation(latitude=52.5, longitude=13.4)
        q.where(BDocument.location == loc)  # ty: ignore[invalid-argument-type]
        cypher, params = q.build()
        # GeoLocationConverter.cypher_fn = "point" → point($p0)
        assert "point($p0)" in cypher
        assert isinstance(params["p0"], dict)
        assert params["p0"]["latitude"] == 52.5

    def test_vector_no_wrapper_in_plain_eq(self) -> None:
        q = QueryBuilder(_mock_session(), BDocument)
        q.where(BDocument.embedding == [0.1, 0.2])  # ty: ignore[invalid-argument-type]
        cypher, params = q.build()
        # VectorConverter.cypher_fn = "vecf32" → vecf32($p0)
        assert "vecf32($p0)" in cypher


# ---------------------------------------------------------------------------
# Fulltext search builder
# ---------------------------------------------------------------------------


class TestFulltextQueryBuilder:
    def test_emits_call_procedure(self) -> None:
        sess = _mock_session()
        q = FulltextQueryBuilder(sess, BArticle, query="graph databases")
        cypher, params = q.build()
        assert "CALL db.idx.fulltext.queryNodes" in cypher
        assert "'BArticle'" in cypher
        assert "$__fts_query" in cypher
        assert params["__fts_query"] == "graph databases"

    def test_where_appended_after_call(self) -> None:
        sess = _mock_session()
        q = FulltextQueryBuilder(sess, BArticle, query="graph")
        q.where(BArticle.title.contains("db"))  # ty: ignore[unresolved-attribute]
        cypher, _ = q.build()
        assert "WHERE" in cypher
        lines = cypher.splitlines()
        call_idx = next(i for i, l in enumerate(lines) if "CALL" in l)
        where_idx = next(i for i, l in enumerate(lines) if "WHERE" in l)
        assert call_idx < where_idx


# ---------------------------------------------------------------------------
# Vector search builder
# ---------------------------------------------------------------------------


class TestVectorQueryBuilder:
    def test_emits_knn_order_by(self) -> None:
        sess = _mock_session()
        vec = [0.1, 0.2, 0.3]
        q = VectorQueryBuilder(
            sess,
            BDocument,
            field=BDocument.embedding,  # ty: ignore[invalid-argument-type]
            vector=vec,
            k=5,
        )
        cypher, params = q.build()
        assert "vecf32(n.embedding) <-> vecf32($__knn_vec)" in cypher
        assert "ORDER BY __score ASC" in cypher
        assert "LIMIT 5" in cypher
        assert params["__knn_vec"] == vec

    def test_where_respected(self) -> None:
        sess = _mock_session()
        q = VectorQueryBuilder(
            sess,
            BDocument,
            field=BDocument.embedding,  # ty: ignore[invalid-argument-type]
            vector=[0.1],
            k=3,
        )
        q.where(BDocument.text.is_not_null())  # ty: ignore[unresolved-attribute]
        cypher, _ = q.build()
        assert "WHERE" in cypher


# ---------------------------------------------------------------------------
# decode_edge integration (Mapper)
# ---------------------------------------------------------------------------


class TestDecodeEdge:
    def test_decode_edge_extracts_properties(self) -> None:
        mapper = Mapper(_real_meta)
        mock_edge = MagicMock()
        mock_edge.type = "BWORKS_FOR"
        mock_edge.properties = {"since": 2020}

        decoded = mapper.decode_edge(mock_edge)
        assert isinstance(decoded, WorksFor)
        assert decoded.since == 2020
        assert decoded._new is False
        assert decoded._dirty is False

    def test_decode_edge_with_hint_cls(self) -> None:
        mapper = Mapper(_real_meta)
        mock_edge = MagicMock()
        mock_edge.properties = {"since": 2019}

        decoded = mapper.decode_edge(mock_edge, hint_cls=WorksFor)
        assert isinstance(decoded, WorksFor)
        assert decoded.since == 2019

    def test_decode_edge_unknown_type_returns_raw(self) -> None:
        mapper = Mapper(_real_meta)
        mock_edge = MagicMock()
        mock_edge.type = "NONEXISTENT_TYPE"
        mock_edge.properties = {}

        result = mapper.decode_edge(mock_edge)
        assert result is mock_edge
