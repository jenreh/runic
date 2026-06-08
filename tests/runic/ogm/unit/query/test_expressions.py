"""Unit tests for runic.ogm.query.expressions — FilterExpr, CompoundExpr, AggExpr."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from runic.ogm.core.descriptors import Field
from runic.ogm.core.models import Node
from runic.ogm.core.types import (
    EnumConverter,
    Vector,
)
from runic.ogm.query.expressions import (
    CompoundExpr,
    FilterExpr,
    NegatedExpr,
    avg,
    collect,
    count,
    max_,
    min_,
    sum_,
)

# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class ExprPerson(Node, labels=["ExprPerson"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    age: int | None = Field(default=None)
    active: bool = Field(default=True)
    deleted_at: str | None = Field(default=None)
    embedding: Vector = Field(index_type="VECTOR")


class Status(StrEnum):
    ACTIVE = "active"
    BANNED = "banned"


class ExprPost(Node, labels=["ExprPost"]):
    id: str = Field(primary_key=True)
    status: Status = Field(converter=EnumConverter(Status))
    created_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# FieldDescriptor operator overloads → FilterExpr
# ---------------------------------------------------------------------------


class TestFieldDescriptorOperators:
    def test_eq_scalar(self) -> None:
        expr = ExprPerson.name == "Alice"
        assert isinstance(expr, FilterExpr)
        assert expr.cls is ExprPerson
        assert expr.prop == "name"
        assert expr.op == "="
        assert expr.value == "Alice"
        assert expr.alias is None

    def test_eq_none_produces_is_null(self) -> None:
        expr = ExprPerson.deleted_at == None  # noqa: E711
        assert isinstance(expr, FilterExpr)
        assert expr.op == "IS NULL"
        assert expr.value is None

    def test_ne_scalar(self) -> None:
        expr = ExprPerson.name != "Bob"
        assert expr.op == "<>"  # ty: ignore[unresolved-attribute]
        assert expr.value == "Bob"  # ty: ignore[unresolved-attribute]

    def test_ne_none_produces_is_not_null(self) -> None:
        expr = ExprPerson.deleted_at != None  # noqa: E711
        assert expr.op == "IS NOT NULL"  # ty: ignore[unresolved-attribute]

    def test_gt(self) -> None:
        expr = ExprPerson.age > 18  # ty: ignore[unsupported-operator]
        assert expr.op == ">"
        assert expr.value == 18

    def test_ge(self) -> None:
        expr = ExprPerson.age >= 18  # ty: ignore[unsupported-operator]
        assert expr.op == ">="

    def test_lt(self) -> None:
        expr = ExprPerson.age < 65  # ty: ignore[unsupported-operator]
        assert expr.op == "<"

    def test_le(self) -> None:
        expr = ExprPerson.age <= 65  # ty: ignore[unsupported-operator]
        assert expr.op == "<="

    def test_contains(self) -> None:
        expr = ExprPerson.name.contains("ali")  # ty: ignore[unresolved-attribute]
        assert expr.op == "CONTAINS"
        assert expr.value == "ali"

    def test_startswith(self) -> None:
        expr = ExprPerson.name.startswith("A")
        assert expr.op == "STARTS WITH"  # ty: ignore[unresolved-attribute]

    def test_endswith(self) -> None:
        expr = ExprPerson.name.endswith("e")
        assert expr.op == "ENDS WITH"  # ty: ignore[unresolved-attribute]

    def test_matches_regex(self) -> None:
        expr = ExprPerson.name.matches(r".*lic.*")  # ty: ignore[unresolved-attribute]
        assert expr.op == "=~"

    def test_is_null(self) -> None:
        expr = ExprPerson.deleted_at.is_null()  # ty: ignore[unresolved-attribute]
        assert expr.op == "IS NULL"
        assert expr.value is None

    def test_is_not_null(self) -> None:
        expr = ExprPerson.deleted_at.is_not_null()  # ty: ignore[unresolved-attribute]
        assert expr.op == "IS NOT NULL"

    def test_in(self) -> None:
        expr = ExprPerson.name.in_(["Alice", "Bob"])  # ty: ignore[unresolved-attribute]
        assert expr.op == "IN"
        assert expr.value == ["Alice", "Bob"]

    def test_not_in(self) -> None:
        expr = ExprPerson.name.not_in_(["spam"])  # ty: ignore[unresolved-attribute]
        assert expr.op == "IN"
        assert expr.negate is True

    def test_descriptor_owner_is_correct(self) -> None:
        assert ExprPerson.name._owner is ExprPerson  # ty: ignore[unresolved-attribute]
        assert ExprPost.status._owner is ExprPost  # ty: ignore[unresolved-attribute]

    def test_descriptor_remains_hashable(self) -> None:
        s: set = {ExprPerson.name, ExprPerson.age}
        assert len(s) == 2


# ---------------------------------------------------------------------------
# Boolean composition
# ---------------------------------------------------------------------------


class TestBooleanComposition:
    def test_and_two_filters(self) -> None:
        compound = (ExprPerson.age > 18) & (ExprPerson.active == True)  # noqa: E712  # ty: ignore[unsupported-operator]
        assert isinstance(compound, CompoundExpr)
        assert compound.op == "AND"
        assert len(compound.operands) == 2

    def test_or_two_filters(self) -> None:
        compound = (ExprPerson.name == "Alice") | (ExprPerson.name == "Bob")
        assert isinstance(compound, CompoundExpr)
        assert compound.op == "OR"

    def test_and_flattens_same_op(self) -> None:
        a = ExprPerson.age > 18  # ty: ignore[unsupported-operator]
        b = ExprPerson.active == True  # noqa: E712
        c = ExprPerson.name == "Alice"
        compound = (a & b) & c
        assert isinstance(compound, CompoundExpr)
        assert len(compound.operands) == 3

    def test_or_flattens_same_op(self) -> None:
        a = ExprPerson.name == "Alice"
        b = ExprPerson.name == "Bob"
        c = ExprPerson.name == "Carol"
        compound = (a | b) | c
        assert len(compound.operands) == 3  # ty: ignore[unresolved-attribute]

    def test_not_wraps_filter(self) -> None:
        negated = ~(ExprPerson.active == True)  # noqa: E712
        assert isinstance(negated, NegatedExpr)
        assert isinstance(negated.operand, FilterExpr)

    def test_with_alias_returns_copy(self) -> None:
        expr = ExprPerson.name == "Alice"
        expr2 = expr.with_alias("u")  # ty: ignore[unresolved-attribute]
        assert expr2.alias == "u"
        assert (
            expr.alias is None  # ty: ignore[unresolved-attribute]
        )  # original unchanged


# ---------------------------------------------------------------------------
# AggExpr and helpers
# ---------------------------------------------------------------------------


class TestAggExpr:
    def test_count_star(self) -> None:
        agg = count()
        assert agg.func == "count"
        assert agg.field == "*"
        assert agg.distinct is False

    def test_count_with_alias(self) -> None:
        agg = count().as_("n")
        assert agg.result_alias == "n"

    def test_count_distinct(self) -> None:
        agg = count(ExprPerson.name, distinct=True)
        assert agg.distinct is True

    def test_avg(self) -> None:
        agg = avg(ExprPerson.age)
        assert agg.func == "avg"

    def test_sum(self) -> None:
        agg = sum_(ExprPerson.age)
        assert agg.func == "sum"

    def test_min(self) -> None:
        agg = min_(ExprPerson.age)
        assert agg.func == "min"

    def test_max(self) -> None:
        agg = max_(ExprPerson.age)
        assert agg.func == "max"

    def test_collect(self) -> None:
        agg = collect(ExprPerson.name)
        assert agg.func == "collect"

    def test_to_cypher_count_star(self) -> None:
        agg = count().as_("total")
        cypher = agg.to_cypher({ExprPerson: "n"})
        assert cypher == "count(*) AS total"

    def test_to_cypher_avg_field(self) -> None:
        agg = avg(ExprPerson.age).as_("avg_age")
        cypher = agg.to_cypher({ExprPerson: "n"})
        assert cypher == "avg(n.age) AS avg_age"

    def test_to_cypher_count_distinct(self) -> None:
        agg = count(ExprPerson.name, distinct=True).as_("unique")
        cypher = agg.to_cypher({ExprPerson: "n"})
        assert cypher == "count(DISTINCT n.name) AS unique"

    def test_to_cypher_no_alias(self) -> None:
        agg = count()
        cypher = agg.to_cypher({})
        assert cypher == "count(*)"
