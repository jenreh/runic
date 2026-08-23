"""Unit tests for the write pipeline: UNWIND, MERGE, SET, DELETE."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.ogm import alias, select, unwind
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.driver.falkordb import FalkorDBDialect
from runic.ogm.driver.neo4j import Neo4jDialect
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.expressions import count
from runic.ogm.query.values import encode_rows, param, row
from tests.runic.ogm.catalog_models import (
    About,
    Address,
    CoAddressed,
    Group,
    Message,
    Topic,
)

_real_meta.finalize()


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
# UNWIND + MERGE
# ---------------------------------------------------------------------------


class TestBulkUpsert:
    def test_merge_puts_only_the_key_in_the_pattern(self) -> None:
        """Everything else belongs in SET, or a changed value misses the node."""
        stmt = (
            unwind(param("rows"))
            .merge(Group, key={Group.id: row("id")}, alias="g")
            .set({Group.size: row("size")}, on="g")
        )
        cypher, _ = _build(stmt)
        assert "UNWIND $rows AS row" in cypher
        assert "MERGE (g:Group {id: row.id})" in cypher
        assert "SET g.size = row.size" in cypher

    def test_an_alias_is_generated_when_not_given(self) -> None:
        stmt = unwind(param("rows")).merge(Group, key={Group.id: row("id")})
        cypher, _ = _build(stmt)
        assert "MERGE (n1:Group {id: row.id})" in cypher

    def test_loop_variable_is_configurable(self) -> None:
        stmt = unwind(param("rows"), as_="entry").merge(
            Group, key={Group.id: row("id", var="entry")}, alias="g"
        )
        cypher, _ = _build(stmt)
        assert "UNWIND $rows AS entry" in cypher
        assert "{id: entry.id}" in cypher

    def test_a_bare_merge_returns_nothing(self) -> None:
        """Inventing a RETURN would change what the statement does."""
        cypher, _ = _build(
            unwind(param("rows")).merge(Group, key={Group.id: row("id")})
        )
        assert "RETURN" not in cypher

    def test_returning_reports_what_a_write_did(self) -> None:
        stmt = (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("id")}, alias="m")
            .set({Message.subject: row("subject")}, on="m")
            .returning(count("m").as_("written"))
        )
        cypher, _ = _build(stmt)
        assert cypher.endswith("RETURN count(m) AS written")


class TestEdgeUpsert:
    def test_endpoints_are_matched_not_merged(self) -> None:
        """A missing endpoint is a caller bug, not something to invent."""
        stmt = (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("message_id")}, alias="m")
            .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
            .merge_edge("m", "ABOUT", "t", alias="r", edge_model=About)
            .set({About.score: row("score")}, on="r")
        )
        cypher, _ = _build(stmt)
        assert "MATCH (m:Message {id: row.message_id})" in cypher
        assert "MATCH (t:Topic {id: row.topic_id})" in cypher
        assert "MERGE (m)-[r:ABOUT]->(t)" in cypher
        assert "SET r.score = row.score" in cypher

    def test_an_anonymous_edge_needs_no_alias(self) -> None:
        stmt = (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("message_id")}, alias="m")
            .match(Group, key={Group.id: row("group_id")}, alias="g")
            .merge_edge("m", "ADDRESSED_GROUP", "g")
        )
        cypher, _ = _build(stmt)
        assert "MERGE (m)-[:ADDRESSED_GROUP]->(g)" in cypher

    def test_undirected_merge_omits_the_arrow(self) -> None:
        """So the same pair in either order finds the same edge."""
        stmt = (
            unwind(param("rows"))
            .match(Address, key={Address.id: row("left")}, alias="a")
            .match(Address, key={Address.id: row("right")}, alias="b")
            .merge_edge("a", "CO_ADDRESSED", "b", alias="r", directed=False)
        )
        cypher, _ = _build(stmt, Neo4jDialect())
        assert "MERGE (a)-[r:CO_ADDRESSED]-(b)" in cypher

    def test_undirected_merge_is_refused_on_falkordb(self) -> None:
        stmt = (
            unwind(param("rows"))
            .match(Address, key={Address.id: row("left")}, alias="a")
            .match(Address, key={Address.id: row("right")}, alias="b")
            .merge_edge("a", "CO_ADDRESSED", "b", alias="r", directed=False)
        )
        with pytest.raises(NotImplementedError, match="undirected MERGE"):
            _build(stmt, FalkorDBDialect())

    def test_variables_are_validated(self) -> None:
        with pytest.raises(ValueError, match="relationship type"):
            unwind(param("rows")).merge_edge("a", "T] DELETE a //", "b")


# ---------------------------------------------------------------------------
# SET
# ---------------------------------------------------------------------------


class TestSet:
    def test_dialect_wrapping_is_applied(self) -> None:
        """A vector stored unwrapped is accepted and then never indexed."""
        stmt = (
            unwind(param("rows"))
            .match(Message, key={Message.id: row("id")}, alias="m")
            .set({Message.embedding: row("vector")}, on="m")
        )
        falkor, _ = _build(stmt, FalkorDBDialect())
        neo4j, _ = _build(stmt, Neo4jDialect())
        assert "SET m.embedding = vecf32(row.vector)" in falkor
        assert "SET m.embedding = row.vector" in neo4j

    def test_none_clears_the_property(self) -> None:
        cypher, _ = _build(
            select(Message).set(
                {Message.embedding: None, Message.embedding_model: None}
            )
        )
        assert "SET n.embedding = NULL, n.embedding_model = NULL" in cypher

    def test_a_plain_value_is_bound(self) -> None:
        cypher, params = _build(select(Message).set({Message.subject: "hello"}))
        assert "SET n.subject = $p0" in cypher
        assert params == {"p0": "hello"}

    def test_a_parameter_is_declared_not_bound(self) -> None:
        stmt = select(Message).set({Message.embedding_model: param("model")})
        cypher, params = _build(stmt)
        assert "SET n.embedding_model = $model" in cypher
        assert params == {}
        assert stmt.parameter_names() == ("model",)

    def test_an_assignment_target_is_validated(self) -> None:
        with pytest.raises(ValueError, match="assignment target"):
            _build(select(Message).set({"n.x = 1 DETACH DELETE n //": 1}))


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


class TestDelete:
    def test_detach_delete_for_nodes(self) -> None:
        stmt = (
            select(Group)
            .with_("n", limit=param("batch"))
            .delete(detach=True)
            .returning(count("n").as_("removed"))
        )
        cypher, _ = _build(stmt)
        assert (
            "WITH n\nLIMIT $batch\nDETACH DELETE n\nRETURN count(n) AS removed"
            in cypher
        )

    def test_plain_delete_for_an_edge_keeps_its_endpoints(self) -> None:
        """Detaching here would take both addresses and everything on them."""
        a = alias(Address, "a")
        stmt = (
            select(a)
            .traverse(a.co_addressed, to="b", edge="r", direction="OUTGOING")
            .with_("r", limit=param("batch"))
            .delete("r")
        )
        cypher, _ = _build(stmt)
        assert "DELETE r" in cypher
        assert "DETACH" not in cypher

    def test_defaults_to_the_current_target(self) -> None:
        cypher, _ = _build(select(Group).delete())
        assert cypher.splitlines()[-1] == "DELETE n"

    def test_a_target_is_validated(self) -> None:
        with pytest.raises(ValueError, match="delete target"):
            select(Group).delete("n DETACH DELETE x //")


# ---------------------------------------------------------------------------
# Row encoding
# ---------------------------------------------------------------------------


class TestRowEncoding:
    def test_datetimes_are_serialised_for_a_rows_payload(self) -> None:
        """Values in $rows never pass through the mapper."""
        moment = datetime(2026, 3, 4, tzinfo=UTC)
        [encoded] = encode_rows(Group, [{"id": "g1", "first_seen": moment}])
        assert isinstance(encoded["first_seen"], str)

    def test_edge_rows_encode_through_their_edge_class(self) -> None:
        moment = datetime(2026, 3, 4, tzinfo=UTC)
        [encoded] = encode_rows(
            CoAddressed, [{"left": "a1", "right": "a2", "first_seen": moment}]
        )
        assert isinstance(encoded["first_seen"], str)
        assert encoded["left"] == "a1"
