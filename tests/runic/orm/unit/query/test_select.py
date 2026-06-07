"""Unit tests for the select() free-function / session-based execution pattern.

Verifies:
- select() creates an unbound QueryBuilder (session=None)
- build() works on unbound statements (no session required)
- Calling terminal methods on unbound statements raises RuntimeError
- session.scalars/scalar/all_rows/all_with_edges/count execute and return typed results
- Statements are reusable across multiple session calls
- scalar() does not permanently mutate _limit_val on the original statement
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from runic.orm.core.descriptors import Field, Relation
from runic.orm.core.metadata import metadata as _real_meta
from runic.orm.core.models import Edge, Node
from runic.orm.mapper.mapper import Mapper
from runic.orm.query import select
from runic.orm.query.builder import QueryBuilder
from runic.orm.session.session import Session

# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class SPerson(Node, labels=["SPerson"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    age: int | None = Field(default=None)
    active: bool = Field(default=True)


class SPost(Node, labels=["SPost"]):
    id: str = Field(primary_key=True)
    title: str = Field()
    published: bool = Field(default=False)


class SFollows(Edge, type="SFOLLOWS"):
    since: int | None = Field(default=None)


class SPersonWithRel(Node, labels=["SPersonWithRel"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    follows: list[SPersonWithRel] = Relation(
        relationship="SFOLLOWS",
        direction="OUTGOING",
        target="SPersonWithRel",
        edge_model="SFollows",
    )


_real_meta.finalize()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(rows: list[list[Any]], columns: list[str] | None = None) -> Any:
    """Build a minimal GraphResult-like object for testing."""
    result = MagicMock()
    result.rows = rows
    result.columns = columns or []
    return result


def _make_session(result: Any | None = None) -> Session:
    """Return a real Session with a mocked driver that returns *result*."""
    driver = MagicMock()
    driver.dialect = None
    r = result or _make_result([])
    driver.execute.return_value = r
    # Session checks isinstance(driver, TransactionalGraphDriver) — make it False
    driver.__class__ = type("FakeDriver", (), {})
    sess = Session(driver)
    sess._run_query = MagicMock(return_value=r)  # ty: ignore[invalid-assignment]
    return sess


# ---------------------------------------------------------------------------
# select() basics
# ---------------------------------------------------------------------------


class TestSelectFactory:
    def test_select_returns_query_builder(self) -> None:
        stmt = select(SPerson)
        assert isinstance(stmt, QueryBuilder)

    def test_select_unbound(self) -> None:
        stmt = select(SPerson)
        assert stmt._session is None

    def test_select_chains_where(self) -> None:
        stmt = select(SPerson).where(SPerson.active == True)  # noqa: E712  # ty: ignore[invalid-argument-type]
        assert len(stmt._where_exprs) == 1

    def test_select_dynamic_filters(self) -> None:
        stmt = select(SPerson)
        stmt = stmt.where(SPerson.active == True)  # noqa: E712  # ty: ignore[invalid-argument-type]
        # Conditionally add another filter
        min_age = 18
        if min_age > 0:
            stmt = stmt.where(SPerson.age >= min_age)  # ty: ignore[unsupported-operator]
        assert len(stmt._where_exprs) == 2

    def test_build_works_without_session(self) -> None:
        stmt = select(SPerson).where(SPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        cypher, params = stmt.build()
        assert "MATCH" in cypher
        assert "SPerson" in cypher
        assert "WHERE" in cypher
        assert params["p0"] == "Alice"

    def test_build_multiple_times_is_idempotent(self) -> None:
        stmt = select(SPerson).where(SPerson.name == "Alice")  # ty: ignore[invalid-argument-type]
        c1, p1 = stmt.build()
        c2, p2 = stmt.build()
        assert c1 == c2
        assert p1 == p2


# ---------------------------------------------------------------------------
# Terminal method guards
# ---------------------------------------------------------------------------


class TestUnboundGuards:
    def test_all_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.all()

    def test_one_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.one()

    def test_all_with_edges_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.all_with_edges()

    def test_all_rows_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.all_rows()

    def test_count_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.count()

    def test_scalar_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.scalar()

    def test_scalars_raises_on_unbound(self) -> None:
        stmt = select(SPerson)
        with pytest.raises(RuntimeError, match="not bound to a session"):
            stmt.scalars()


# ---------------------------------------------------------------------------
# Session execution methods
# ---------------------------------------------------------------------------


class TestSessionScalars:
    def test_scalars_returns_empty_list(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        result = sess.scalars(stmt)
        assert result == []

    def test_scalars_decodes_node(self) -> None:
        raw_node = {"id": "1", "name": "Alice", "age": None, "active": True}
        mock_result = _make_result([[raw_node]])

        stmt = select(SPerson)
        sess = _make_session(mock_result)

        # Patch mapper.decode_node to return a SPerson-like object
        mapper = Mapper(_real_meta)
        sess._mapper = mapper
        person = SPerson(id="1", name="Alice")
        with patch.object(mapper, "decode_node", return_value=person):
            entities = sess.scalars(stmt)

        assert len(entities) == 1
        assert entities[0] is person

    def test_scalars_leaves_stmt_unbound_after_call(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        sess.scalars(stmt)
        assert stmt._session is None

    def test_scalars_stmt_reusable(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        sess.scalars(stmt)
        sess.scalars(stmt)  # second call must not fail
        assert stmt._session is None

    def test_scalars_generates_correct_cypher(self) -> None:
        stmt = select(SPerson).where(SPerson.name == "Bob")  # ty: ignore[invalid-argument-type]
        sess = _make_session(_make_result([]))
        sess.scalars(stmt)
        call_args = sess._run_query.call_args  # ty: ignore[unresolved-attribute]
        cypher = call_args[0][0]
        assert "WHERE n.name = $p0" in cypher


class TestSessionScalar:
    def test_scalar_returns_none_on_empty(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        result = sess.scalar(stmt)
        assert result is None

    def test_scalar_adds_limit_1_transiently(self) -> None:
        stmt = select(SPerson)
        assert stmt._limit_val is None

        sess = _make_session(_make_result([]))
        sess.scalar(stmt)

        # original limit must be restored
        assert stmt._limit_val is None

    def test_scalar_limit_1_in_cypher(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        sess.scalar(stmt)
        cypher = sess._run_query.call_args[0][0]  # ty: ignore[unresolved-attribute]
        assert "LIMIT 1" in cypher

    def test_scalar_returns_first_entity(self) -> None:
        raw_node = {"id": "2", "name": "Bob", "age": None, "active": True}
        mock_result = _make_result([[raw_node]])
        stmt = select(SPerson)
        sess = _make_session(mock_result)
        mapper = Mapper(_real_meta)
        sess._mapper = mapper
        person = SPerson(id="2", name="Bob")
        with patch.object(mapper, "decode_node", return_value=person):
            entity = sess.scalar(stmt)
        assert entity is person

    def test_scalar_leaves_stmt_unbound(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([]))
        sess.scalar(stmt)
        assert stmt._session is None


class TestSessionCount:
    def test_count_returns_zero_on_empty(self) -> None:
        mock_result = _make_result([[0]])
        stmt = select(SPerson)
        sess = _make_session(mock_result)
        n = sess.count(stmt)
        assert n == 0

    def test_count_returns_integer(self) -> None:
        mock_result = _make_result([[42]])
        stmt = select(SPerson)
        sess = _make_session(mock_result)
        n = sess.count(stmt)
        assert n == 42

    def test_count_cypher_contains_count_star(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([[0]]))
        sess.count(stmt)
        cypher = sess._run_query.call_args[0][0]  # ty: ignore[unresolved-attribute]
        assert (
            "count(*)" in cypher.lower()
            or "count(n)" in cypher.lower()
            or "count" in cypher.lower()
        )

    def test_count_leaves_stmt_unbound(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([[0]]))
        sess.count(stmt)
        assert stmt._session is None

    def test_count_does_not_mutate_return_aliases(self) -> None:
        stmt = select(SPerson)
        original_return = stmt._return_aliases
        sess = _make_session(_make_result([[5]]))
        sess.count(stmt)
        assert stmt._return_aliases == original_return


class TestSessionAllRows:
    def test_all_rows_returns_empty(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([], ["n"]))
        rows = sess.all_rows(stmt)
        assert rows == []

    def test_all_rows_leaves_stmt_unbound(self) -> None:
        stmt = select(SPerson)
        sess = _make_session(_make_result([], ["n"]))
        sess.all_rows(stmt)
        assert stmt._session is None


class TestSessionAllWithEdges:
    def test_all_with_edges_returns_empty(self) -> None:
        stmt = select(SPersonWithRel)
        sess = _make_session(_make_result([]))
        rows = sess.all_with_edges(stmt)
        assert rows == []

    def test_all_with_edges_leaves_stmt_unbound(self) -> None:
        stmt = select(SPersonWithRel)
        sess = _make_session(_make_result([]))
        sess.all_with_edges(stmt)
        assert stmt._session is None


# ---------------------------------------------------------------------------
# Type error on non-QueryBuilder input
# ---------------------------------------------------------------------------


class TestTypeGuards:
    def test_scalars_rejects_raw_string(self) -> None:
        sess = _make_session()
        with pytest.raises(TypeError, match="QueryBuilder"):
            sess.scalars("MATCH (n) RETURN n")  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def test_scalar_rejects_raw_string(self) -> None:
        sess = _make_session()
        with pytest.raises(TypeError, match="QueryBuilder"):
            sess.scalar("MATCH (n) RETURN n")  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def test_count_rejects_raw_string(self) -> None:
        sess = _make_session()
        with pytest.raises(TypeError, match="QueryBuilder"):
            sess.count("MATCH (n) RETURN n")  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
