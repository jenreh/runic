"""Every property key and result alias runic emits is backtick-quoted.

Apache AGE resolves an unquoted property key against its keyword and function
tokens before treating it as a key, so a model that declares ``count`` — or
``end``, ``order``, ``where``, and 34 more of the 65 words probed — produces
Cypher its parser rejects::

    MATCH (n:Reserved) WHERE n.count > 0 RETURN n
    -> psycopg.errors.SyntaxError: syntax error at or near ">"

Quoting is unconditional rather than restricted to a deny-list: the failing set
is AGE's whole grammar, a word missing from such a list would be a syntax error
in production, and backticks were verified accepted in every emission position
by all five supported backends.  These tests pin that at each position; the
live counterpart in
:mod:`tests.runic.ogm.integration.test_reserved_word_properties` proves the
backends accept the result.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from runic.cypher import unquote_identifier, unquote_reference
from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.core.models import Edge, Node
from runic.ogm.driver.age import _parse_return_columns, _quote_sql_identifier
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.mapper.relationship_loader import RelationshipLoader
from runic.ogm.mapper.relationship_writer import RelationshipWriter
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.expressions import count
from runic.ogm.query.values import col, param, row, when

# ---------------------------------------------------------------------------
# Models whose property names collide with Cypher keywords and functions
# ---------------------------------------------------------------------------


class EscTally(Edge, type="ESC_TALLY"):
    count: int | None = Field(default=None)
    end: str | None = Field(default=None)


class EscReserved(Node, labels=["EscReserved"]):
    """Every field name here is a word AGE rejects unquoted after a dot."""

    id: str = Field(primary_key=True)
    count: int | None = Field(default=None)
    end: str | None = Field(default=None)
    order: int | None = Field(default=None)
    match: str | None = Field(default=None)
    tallied: list[EscReserved] = Relation(
        relationship="ESC_TALLY",
        direction="OUTGOING",
        target="EscReserved",
        edge_model="EscTally",
    )


class EscKeyed(Node, labels=["EscKeyed"]):
    """A natural primary key whose name is itself a reserved word."""

    end: str = Field(primary_key=True)
    label: str | None = Field(default=None)


def _mock_session() -> Any:
    """A MagicMock session wired to the real MetaData and Mapper."""
    mapper = Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


def _build(query: QueryBuilder[Any]) -> str:
    cypher, _ = query.build()
    return cypher


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


class TestWherePredicates:
    def test_comparison_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).where(EscReserved.count > 0)  # ty: ignore[unsupported-operator]
        )
        assert "WHERE n.`count` > $p0" in cypher
        assert "n.count" not in cypher

    def test_null_checks_quote_the_key(self) -> None:
        q = QueryBuilder(_mock_session(), EscReserved)
        assert "n.`end` IS NULL" in _build(q.where(EscReserved.end.is_null()))  # ty: ignore[unresolved-attribute]
        q2 = QueryBuilder(_mock_session(), EscReserved)
        assert "n.`end` IS NOT NULL" in _build(q2.where(EscReserved.end.is_not_null()))  # ty: ignore[unresolved-attribute]

    def test_membership_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).where(
                EscReserved.match.in_(["a", "b"])  # ty: ignore[unresolved-attribute]
            )
        )
        assert "n.`match` IN $p0" in cypher

    def test_edge_predicate_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved, "a")
            .traverse(EscReserved.tallied, edge="r", to="b")
            .where(EscTally.count.is_not_null(), on="r")  # ty: ignore[unresolved-attribute]
        )
        assert "r.`count` IS NOT NULL" in cypher


# ---------------------------------------------------------------------------
# Projection, ordering, aggregation
# ---------------------------------------------------------------------------


class TestProjection:
    def test_descriptor_projection_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(EscReserved.count)
        )
        assert "RETURN n.`count`" in cypher

    def test_raw_string_projection_quotes_the_key(self) -> None:
        """The escape hatch takes the catalogue's spelling and quotes it too."""
        cypher = _build(QueryBuilder(_mock_session(), EscReserved).project("n.count"))
        assert "RETURN n.`count`" in cypher

    def test_bare_alias_projection_is_left_alone(self) -> None:
        """A bare reference names a Cypher variable, not a property key."""
        cypher = _build(QueryBuilder(_mock_session(), EscReserved).project("n"))
        assert "RETURN n" in cypher
        assert "`n`" not in cypher

    def test_result_alias_is_quoted(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                EscReserved.count.as_("end")  # ty: ignore[unresolved-attribute]
            )
        )
        assert "RETURN n.`count` AS `end`" in cypher


class TestOrdering:
    def test_descriptor_order_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).order_by(
                EscReserved.order,
                desc=True,
            )
        )
        assert "ORDER BY n.`order` DESC" in cypher

    def test_raw_order_term_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).order_by("n.count DESC")
        )
        assert "ORDER BY n.`count` DESC" in cypher

    def test_raw_order_term_on_a_result_alias_is_left_alone(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved)
            .project(count("*").as_("total"))
            .order_by("total DESC")
        )
        assert "ORDER BY total DESC" in cypher


class TestAggregation:
    def test_descriptor_operand_and_alias_are_quoted(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                count(EscReserved.count, distinct=True).as_("end")
            )
        )
        assert "count(DISTINCT n.`count`) AS `end`" in cypher

    def test_raw_operand_is_quoted(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                count("n.count").as_("total")
            )
        )
        assert "count(n.`count`) AS `total`" in cypher

    def test_count_star_is_not_quoted(self) -> None:
        cypher = _build(QueryBuilder(_mock_session(), EscReserved).project(count("*")))
        assert "count(*)" in cypher

    def test_group_by_key_is_quoted(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                "n.count", count("*").as_("total")
            )
        )
        assert "RETURN n.`count`, count(*) AS `total`" in cypher

    def test_result_alias_cannot_smuggle_a_second_clause(self) -> None:
        """Quoting the alias closes it as an interpolation point as well."""
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                count("*").as_("c DETACH DELETE n")
            )
        )
        assert "AS `c DETACH DELETE n`" in cypher
        assert "AS c DETACH DELETE n" not in cypher


# ---------------------------------------------------------------------------
# Value expressions
# ---------------------------------------------------------------------------


class TestValueExpressions:
    def test_col_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved, "a").where(
                col("a", EscReserved.count) > param("floor")  # ty: ignore[no-matching-overload]
            )
        )
        assert "a.`count` > $floor" in cypher

    def test_property_to_property_comparison_quotes_both(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved, "a")
            .traverse(EscReserved.tallied, edge="r", to="b")
            .where(col("a", EscReserved.count) < col("b", EscReserved.count))  # ty: ignore[no-matching-overload]
        )
        assert "a.`count` < b.`count`" in cypher

    def test_case_expression_quotes_the_key(self) -> None:
        cypher = _build(
            QueryBuilder(_mock_session(), EscReserved).project(
                count(when(EscReserved.end == param("marker"), 1)).as_("ended")  # ty: ignore[invalid-argument-type]
            )
        )
        assert "CASE WHEN n.`end` = $marker" in cypher

    def test_row_reference_quotes_the_key(self) -> None:
        assert row("count").to_cypher(None) == "row.`count`"
        assert row("count", var="entry").to_cypher(None) == "entry.`count`"


# ---------------------------------------------------------------------------
# Mapper: CREATE / SET / MATCH
# ---------------------------------------------------------------------------


class TestMapperWrites:
    def test_create_quotes_property_map_keys(self) -> None:
        mapper = Mapper(_real_meta)
        cypher, params = mapper.build_create_query(
            EscReserved(id="r1", count=3, end="x")
        )
        assert "`count`: $count" in cypher
        assert "`end`: $end" in cypher
        assert params["count"] == 3

    def test_update_quotes_set_targets(self) -> None:
        mapper = Mapper(_real_meta)
        entity = EscReserved(id="r1", count=4)
        cypher, _ = mapper.build_update_query(entity)
        assert "SET n.`count` = $count" in cypher

    def test_pk_match_quotes_a_reserved_primary_key(self) -> None:
        mapper = Mapper(_real_meta)
        cypher, _ = mapper.build_get_query(EscKeyed, "e1")
        assert "MATCH (n:EscKeyed {`end`: $__pk})" in cypher

    def test_delete_quotes_a_reserved_primary_key(self) -> None:
        mapper = Mapper(_real_meta)
        cypher, _ = mapper.build_delete_query(EscKeyed(end="e1"))
        assert "{`end`: $__pk}" in cypher

    def test_find_all_by_ids_quotes_the_primary_key(self) -> None:
        mapper = Mapper(_real_meta)
        cypher, _ = mapper.build_find_all_by_ids_query(EscKeyed, ["e1", "e2"])
        assert "n.`end` IN $__pks" in cypher


class TestRelationshipCypher:
    def test_edge_property_set_quotes_the_key(self) -> None:
        mapper = Mapper(_real_meta)
        writer = RelationshipWriter(_real_meta, mapper)
        source = EscReserved(id="r1")
        target = EscReserved(id="r2")
        fi = next(
            f
            for f in mapper.require_node_meta(EscReserved).fields
            if f.name == "tallied"
        )
        cypher, _ = writer.build_relate_query(
            source, fi, target, edge=EscTally(count=7)
        )
        assert "r.`count` = $__e_count" in cypher

    def test_eager_fetch_quotes_the_collect_alias(self) -> None:
        mapper = Mapper(_real_meta)
        loader = RelationshipLoader(_real_meta, mapper)
        cypher, _, _ = loader.build_get_with_fetch_query(EscReserved, "r1", ["tallied"])
        assert "AS `tallied`" in cypher


# ---------------------------------------------------------------------------
# AGE: reading the quoted form back out
# ---------------------------------------------------------------------------


class TestAGEColumnNames:
    def test_quoted_property_yields_the_declared_name(self) -> None:
        """Falling through to the positional fallback would rename the column."""
        assert _parse_return_columns("MATCH (n:X) RETURN n.`count`") == ["count"]

    def test_quoted_alias_yields_the_declared_name(self) -> None:
        assert _parse_return_columns("MATCH (n:X) RETURN count(*) AS `end`") == ["end"]

    def test_mixed_items_keep_their_order(self) -> None:
        assert _parse_return_columns(
            "MATCH (n:X) RETURN n.`count` AS `total`, n.id, m"
        ) == ["total", "id", "m"]

    def test_unquoted_forms_still_parse(self) -> None:
        assert _parse_return_columns("MATCH (n:X) RETURN n.id AS ident") == ["ident"]
        assert _parse_return_columns("MATCH (n:X) RETURN n") == ["n"]

    def test_unquote_collapses_doubled_backticks(self) -> None:
        assert unquote_identifier("`odd``name`") == "odd`name"
        assert unquote_identifier("plain") == "plain"

    def test_sql_column_names_are_double_quoted(self) -> None:
        """``AS (end agtype)`` is a PostgreSQL syntax error; the quoted form is not."""
        assert _quote_sql_identifier("end") == '"end"'
        assert _quote_sql_identifier('od"d') == '"od""d"'


class TestReportedColumnNames:
    """Quoting must not reach the caller's ``all_rows()`` keys."""

    def test_reference_is_unquoted(self) -> None:
        assert unquote_reference("n.`count`") == "n.count"

    def test_bare_alias_is_unquoted(self) -> None:
        assert unquote_reference("`end`") == "end"

    def test_unquoted_input_is_unchanged(self) -> None:
        assert unquote_reference("n.count") == "n.count"
        assert unquote_reference("total") == "total"
