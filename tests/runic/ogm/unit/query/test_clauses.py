"""Unit tests for the ordered clause pipeline: WITH stages and traversals."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.ogm import select
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.driver import CypherFeature, dialect_supports, require_feature
from runic.ogm.driver.age import AGEDialect
from runic.ogm.driver.falkordb import FalkorDBDialect
from runic.ogm.driver.neo4j import Neo4jDialect
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.clauses import MatchClause, WithClause
from runic.ogm.query.expressions import collect, count
from runic.ogm.query.values import col, param
from tests.runic.ogm.catalog_models import Address, Message

_real_meta.finalize()

_ADDRESSED = ["SENT_TO", "COPIED_TO"]


def _mock_session(dialect: Any = None) -> Any:
    mapper = Mapper(_real_meta, dialect) if dialect else Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


def _build(stmt: Any, dialect: Any = None) -> tuple[str, dict[str, Any]]:
    with stmt._bound_to(_mock_session(dialect)) as bound:
        return bound.build()


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestPipelineOrder:
    def test_with_and_traversals_emit_in_call_order(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .with_("m", limit=10, order_by=Message.id)
            .traverse(Message.sent_from, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("s")
        )
        cypher, _ = _build(stmt)
        assert cypher.index("WITH m") < cypher.index("OPTIONAL MATCH (m)-[:SENT_FROM]")

    def test_a_with_after_a_traversal_stays_after_it(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_from, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("s")
            .with_("m", "s")
        )
        cypher, _ = _build(stmt)
        assert cypher.index("OPTIONAL MATCH (m)-[:SENT_FROM]") < cypher.index("WITH m")

    def test_several_with_stages_are_all_emitted(self) -> None:
        stmt = select(Message).alias("m").with_("m").with_("m", distinct=True)
        cypher, _ = _build(stmt)
        assert cypher.count("WITH ") == 2
        assert "WITH DISTINCT m" in cypher


# ---------------------------------------------------------------------------
# WITH
# ---------------------------------------------------------------------------


class TestWithStage:
    def test_order_limit_and_skip_render_inside_the_stage(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .with_("m", order_by=Message.id, limit=param("limit"), skip=5)
        )
        cypher, _ = _build(stmt)
        assert "WITH m\nORDER BY m.id ASC\nSKIP 5\nLIMIT $limit" in cypher

    def test_page_is_cut_before_the_expansions(self) -> None:
        """The reason a mid-query LIMIT exists at all."""
        stmt = (
            select(Message)
            .alias("m")
            .with_("m", order_by=Message.id, limit=param("limit"))
            .traverse(Message.sent_to, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("r")
        )
        cypher, _ = _build(stmt)
        assert cypher.index("LIMIT $limit") < cypher.index("OPTIONAL MATCH")

    def test_where_on_a_stage_filters_after_it(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .with_("m", where=Message.subject == param("wanted"))  # ty: ignore[invalid-argument-type]
        )
        cypher, _ = _build(stmt)
        assert "WITH m\nWHERE m.subject = $wanted" in cypher

    def test_an_expression_can_be_carried_forward(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_to, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("r")
            .with_("m", count("*").as_("fanout"))
        )
        cypher, _ = _build(stmt)
        assert "WITH m, count(*) AS fanout" in cypher

    def test_a_variable_must_be_an_identifier(self) -> None:
        stmt = select(Message).alias("m").with_("m) DETACH DELETE m //")
        with pytest.raises(ValueError, match="WITH variable"):
            _build(stmt)


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------


class TestFanOut:
    def test_from_anchors_each_traversal_to_the_same_source(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_from, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("s")
            .traverse(Message.sent_to, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("r")
        )
        cypher, _ = _build(stmt)
        assert "OPTIONAL MATCH (m)-[:SENT_FROM]->(s:Address)" in cypher
        assert "OPTIONAL MATCH (m)-[:SENT_TO]->(r:Address)" in cypher

    def test_without_from_a_traversal_continues_the_chain(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_from)  # ty: ignore[invalid-argument-type]
            .alias("s")
            .traverse(Address.co_addressed)  # ty: ignore[invalid-argument-type]
            .alias("x")
        )
        cypher, _ = _build(stmt)
        assert "(s)-[:CO_ADDRESSED]-(x:Address)" in cypher


class TestAlternation:
    def test_emits_a_single_pattern_over_both_types(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_to, from_="m", types=_ADDRESSED)  # ty: ignore[invalid-argument-type]
            .alias("r")
        )
        cypher, _ = _build(stmt)
        assert "(m)-[:SENT_TO|COPIED_TO]->(r:Address)" in cypher

    def test_each_type_is_validated(self) -> None:
        """Rejected as the step is registered, before any Cypher is compiled."""
        with pytest.raises(ValueError, match="relationship type"):
            (
                select(Message)
                .alias("m")
                .traverse(
                    Message.sent_to,  # ty: ignore[invalid-argument-type]
                    from_="m",
                    types=["SENT_TO", "X] DELETE m //"],
                )
                .alias("r")
            )

    def test_refused_on_a_backend_that_cannot_parse_it(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_to, from_="m", types=_ADDRESSED)  # ty: ignore[invalid-argument-type]
            .alias("r")
        )
        with pytest.raises(NotImplementedError, match="alternation"):
            _build(stmt, AGEDialect())

    def test_allowed_where_supported(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_to, from_="m", types=_ADDRESSED)  # ty: ignore[invalid-argument-type]
            .alias("r")
        )
        cypher, _ = _build(stmt, Neo4jDialect())
        assert "[:SENT_TO|COPIED_TO]" in cypher


class TestDirectionOverride:
    def test_a_both_relation_can_be_matched_directed(self) -> None:
        """Both ends carry the same label, so an arrow matches each edge once."""
        stmt = (
            select(Address)
            .alias("a")
            .traverse(
                Address.co_addressed,  # ty: ignore[invalid-argument-type]
                edge_alias="r",
                optional=False,
                direction="OUTGOING",
            )
            .alias("b")
        )
        cypher, _ = _build(stmt)
        assert "(a)-[r:CO_ADDRESSED]->(b:Address)" in cypher

    def test_the_declared_direction_is_the_default(self) -> None:
        stmt = (
            select(Address)
            .alias("a")
            .traverse(Address.co_addressed, edge_alias="r", optional=False)  # ty: ignore[invalid-argument-type]
            .alias("b")
        )
        cypher, _ = _build(stmt)
        assert "(a)-[r:CO_ADDRESSED]-(b:Address)" in cypher


# ---------------------------------------------------------------------------
# Capability probe
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_a_backend_that_states_nothing_supports_everything(self) -> None:
        assert dialect_supports(Neo4jDialect(), CypherFeature.RELATIONSHIP_ALTERNATION)
        assert dialect_supports(None, CypherFeature.PROCEDURE_CALL)

    def test_declared_gaps_are_reported(self) -> None:
        assert not dialect_supports(
            AGEDialect(), CypherFeature.RELATIONSHIP_ALTERNATION
        )
        assert not dialect_supports(FalkorDBDialect(), CypherFeature.UNDIRECTED_MERGE)

    def test_require_feature_names_the_backend_and_the_construct(self) -> None:
        with pytest.raises(NotImplementedError) as excinfo:
            require_feature(AGEDialect(), CypherFeature.PROCEDURE_CALL, "CALL … YIELD")
        message = str(excinfo.value)
        assert "AGE" in message
        assert "CALL … YIELD" in message

    def test_require_feature_is_silent_when_supported(self) -> None:
        require_feature(Neo4jDialect(), CypherFeature.PROCEDURE_CALL, "CALL … YIELD")


# ---------------------------------------------------------------------------
# Clause objects
# ---------------------------------------------------------------------------


class TestClauseObjects:
    def test_match_clause_optionality(self) -> None:
        assert MatchClause("(a)-[:T]->(b)").to_cypher(None).startswith("OPTIONAL MATCH")
        assert (
            MatchClause("(a)-[:T]->(b)", optional=False).to_cypher(None)
            == "MATCH (a)-[:T]->(b)"
        )

    def test_with_clause_renders_bare_variables(self) -> None:
        assert WithClause(variables=("m", "s")).to_cypher(MagicMock()) == "WITH m, s"


class TestCollectOverTraversal:
    def test_collect_distinct_on_a_traversal_alias(self) -> None:
        stmt = (
            select(Message)
            .alias("m")
            .traverse(Message.sent_to, from_="m")  # ty: ignore[invalid-argument-type]
            .alias("r")
            .aggregate(
                collect(col("r", Address.id), distinct=True).as_("addressed"),  # ty: ignore[no-matching-overload]
                group_by=col("m", Message.id).as_("id"),  # ty: ignore[no-matching-overload]
            )
        )
        cypher, _ = _build(stmt)
        assert "RETURN m.id AS id, collect(DISTINCT r.id) AS addressed" in cypher
