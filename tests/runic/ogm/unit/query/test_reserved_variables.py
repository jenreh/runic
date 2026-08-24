"""An alias the backend cannot parse is refused at compile time, not at the store.

Property keys are backtick-quoted on the way out, so a model may declare a field
named ``count``.  A Cypher *variable* has no such escape — quoting one is worse
than leaving it bare:

    Memgraph   MATCH (`n`:X) WITH `n` ...  -> Unbound variable: n
    ArcadeDB   MATCH (`n`:X) DETACH DELETE `n` -> UndefinedVariable: '`n`'

so the builder refuses the alias instead.  The refusal is per-dialect because
the answer is: Apache AGE cannot use 52 of the 119 names swept, every other
backend only ``true`` and ``false``.  Banning AGE's list everywhere would reject
``alias("count")`` on four backends that handle it fine.

The set itself is verified against live backends by
:mod:`tests.runic.ogm.integration.test_reserved_variable_names`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.cypher import UNIVERSAL_RESERVED_VARIABLES, validate_variable_name
from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.core.models import Node
from runic.ogm.driver.age import AGEDialect
from runic.ogm.driver.arcadedb import ArcadeDBDialect
from runic.ogm.driver.falkordb import FalkorDBDialect
from runic.ogm.driver.memgraph import MemgraphDialect
from runic.ogm.driver.neo4j import Neo4jDialect
from runic.ogm.driver.neptune import NeptuneDialect
from runic.ogm.driver.neptune_analytics import NeptuneAnalyticsDialect
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.mutation import unwind
from runic.ogm.query.values import param, row

ALL_DIALECTS = [
    FalkorDBDialect,
    Neo4jDialect,
    MemgraphDialect,
    ArcadeDBDialect,
    AGEDialect,
    NeptuneDialect,
    NeptuneAnalyticsDialect,
]


class RvNode(Node, labels=["RvNode"]):
    id: str = Field(primary_key=True)
    size: int | None = Field(default=None)
    peers: list[RvNode] = Relation(
        relationship="RV_PEER", direction="OUTGOING", target="RvNode"
    )


def _session(dialect: Any) -> Any:
    mapper = Mapper(_real_meta, dialect)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


# ---------------------------------------------------------------------------
# The sets themselves
# ---------------------------------------------------------------------------


class TestDialectSets:
    @pytest.mark.parametrize("dialect", ALL_DIALECTS, ids=lambda d: d.__name__)
    def test_every_dialect_declares_a_set(self, dialect: Any) -> None:
        assert isinstance(dialect.reserved_variable_names, frozenset)

    @pytest.mark.parametrize("dialect", ALL_DIALECTS, ids=lambda d: d.__name__)
    def test_boolean_literals_are_reserved_everywhere(self, dialect: Any) -> None:
        """The one thing no backend accepts as a variable, quoted or not."""
        assert UNIVERSAL_RESERVED_VARIABLES <= dialect.reserved_variable_names

    def test_only_age_needs_more_than_the_literals(self) -> None:
        """Banning AGE's list everywhere would reject aliases four backends allow."""
        for dialect in ALL_DIALECTS:
            if dialect is AGEDialect:
                continue
            assert dialect.reserved_variable_names == UNIVERSAL_RESERVED_VARIABLES

    def test_age_covers_the_words_that_actually_fail(self) -> None:
        reserved = AGEDialect.reserved_variable_names
        for word in ("count", "end", "order", "where", "match", "with", "return"):
            assert word in reserved, word


class TestValidateVariableName:
    def test_accepts_an_ordinary_name(self) -> None:
        assert validate_variable_name("m", frozenset({"true"}), backend="X") == "m"

    def test_rejects_case_insensitively(self) -> None:
        """`COUNT` is the same token to the parser as `count`."""
        with pytest.raises(ValueError, match="reserved word"):
            validate_variable_name("COUNT", frozenset({"count"}), backend="AGE")

    def test_names_the_backend_and_the_way_out(self) -> None:
        with pytest.raises(ValueError) as exc:
            validate_variable_name("count", frozenset({"count"}), backend="AGE")
        message = str(exc.value)
        assert "AGE" in message
        assert "Choose another name" in message


# ---------------------------------------------------------------------------
# Where the builder applies it
# ---------------------------------------------------------------------------


class TestQueryBuilder:
    def test_reserved_alias_is_refused_on_age(self) -> None:
        query = QueryBuilder(_session(AGEDialect()), RvNode, "count")
        with pytest.raises(ValueError, match="cannot be used as a Cypher alias"):
            query.build()

    def test_the_same_alias_is_allowed_where_it_works(self) -> None:
        """FalkorDB parses `count` as a variable, so runic does not stand in the way."""
        cypher, _ = QueryBuilder(_session(FalkorDBDialect()), RvNode, "count").build()
        assert "MATCH (count:RvNode)" in cypher

    def test_boolean_literal_is_refused_on_every_backend(self) -> None:
        for dialect in ALL_DIALECTS:
            query = QueryBuilder(_session(dialect()), RvNode, "true")
            with pytest.raises(ValueError, match="reserved word"):
                query.build()

    def test_a_traversal_alias_is_checked_too(self) -> None:
        query = QueryBuilder(_session(AGEDialect()), RvNode, "a").traverse(
            RvNode.peers, to="end"
        )
        with pytest.raises(ValueError, match="cannot be used as a Cypher alias"):
            query.build()

    def test_an_ordinary_query_is_untouched(self) -> None:
        cypher, _ = QueryBuilder(_session(AGEDialect()), RvNode).build()
        assert "MATCH (n:RvNode)" in cypher


class TestMutationBuilder:
    def test_reserved_unwind_variable_is_refused(self) -> None:
        stmt = unwind(param("rows"), as_="end").merge(
            RvNode, key={RvNode.id: row("id")}, alias="g"
        )
        with (
            pytest.raises(ValueError, match="UNWIND variable"),
            stmt._bound_to(_session(AGEDialect())) as bound,
        ):
            bound.build()

    def test_reserved_node_alias_is_refused(self) -> None:
        stmt = unwind(param("rows")).merge(
            RvNode, key={RvNode.id: row("id")}, alias="order"
        )
        with (
            pytest.raises(ValueError, match="cannot be used as a Cypher alias"),
            stmt._bound_to(_session(AGEDialect())) as bound,
        ):
            bound.build()

    def test_an_ordinary_write_is_untouched(self) -> None:
        stmt = unwind(param("rows")).merge(
            RvNode, key={RvNode.id: row("id")}, alias="g"
        )
        with stmt._bound_to(_session(AGEDialect())) as bound:
            cypher, _ = bound.build()
        assert "UNWIND $rows AS row" in cypher
