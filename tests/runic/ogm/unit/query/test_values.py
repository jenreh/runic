"""Unit tests for runic.ogm.query.values — the value-expression layer.

Cypher generation is asserted against a MagicMock session wired to the real
MetaData, the same arrangement ``test_builder`` uses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.ogm import alias, select
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.mapper.mapper import Mapper
from runic.ogm.query.expressions import count
from runic.ogm.query.values import (
    Alias,
    AliasedExpr,
    CaseExpr,
    FnCall,
    ParamRef,
    PropertyRef,
    RowRef,
    coalesce,
    col,
    encode_rows,
    fn,
    left,
    literal,
    param,
    row,
    to_lower,
    when,
)
from tests.runic.ogm.catalog_models import Address, Group, Message

_real_meta.finalize()


def _mock_session() -> Any:
    mapper = Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


def _build(stmt: Any) -> tuple[str, dict[str, Any]]:
    with stmt._bound_to(_mock_session()) as bound:
        return bound.build()


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


class TestCol:
    def test_bare_descriptor_defers_alias_to_the_builder(self) -> None:
        cypher, _ = _build(select(Message).project(Message.id))
        assert "RETURN n.`id`" in cypher

    def test_alias_first_form_pins_the_variable(self) -> None:
        ref = col("m", Message.id)  # ty: ignore[no-matching-overload]
        assert isinstance(ref, PropertyRef)
        assert ref.alias == "m"

    def test_keyword_form_pins_the_variable(self) -> None:
        assert col(Message.id, "m").alias == "m"  # ty: ignore[no-matching-overload]

    def test_single_descriptor_is_a_type_error(self) -> None:
        """The deferred form is the bare descriptor; col() only pins."""
        with pytest.raises(TypeError, match="bare"):
            col(Message.id)  # ty: ignore[no-matching-overload]

    def test_two_strings_is_a_type_error(self) -> None:
        with pytest.raises(TypeError, match="col"):
            col("m", "id")  # ty: ignore[no-matching-overload]


class TestAliasHandle:
    def test_renders_as_the_bare_variable(self) -> None:
        m = alias(Message, "m")
        assert m.to_cypher(MagicMock()) == "m"
        assert m.referenced_aliases(MagicMock()) == {"m"}

    def test_attribute_access_pins_a_property(self) -> None:
        m = alias(Message, "m")
        ref = m.id
        assert isinstance(ref, PropertyRef)
        assert ref.alias == "m"
        assert ref.prop == "id"

    def test_unknown_field_raises(self) -> None:
        m = alias(Message, "m")
        with pytest.raises(AttributeError, match="no field"):
            _ = m.nope

    def test_name_must_be_an_identifier(self) -> None:
        with pytest.raises(ValueError, match="alias"):
            alias(Message, "m) DETACH DELETE n //")

    def test_is_a_value_expression(self) -> None:
        assert isinstance(alias(Message, "m"), Alias)

    def test_names_the_root_variable_in_select(self) -> None:
        m = alias(Message, "m")
        cypher, _ = _build(select(m).where(m.id == param("x")))
        assert "MATCH (m:Message)" in cypher
        assert "m.`id` = $x" in cypher


class TestParam:
    def test_renders_as_a_named_parameter(self) -> None:
        cypher, params = _build(select(Message).where(Message.id == param("wanted")))  # ty: ignore[invalid-argument-type]
        assert "n.`id` = $wanted" in cypher
        assert params == {}, "a declared parameter carries no value"

    def test_is_reported_by_parameter_names(self) -> None:
        stmt = select(Message).where(Message.id == param("wanted")).limit(param("cap"))  # ty: ignore[invalid-argument-type]
        assert stmt.parameter_names() == ("cap", "wanted")

    def test_rejects_a_name_that_is_not_an_identifier(self) -> None:
        with pytest.raises(ValueError, match="parameter name"):
            param("limit; DROP")

    def test_repeated_use_declares_once(self) -> None:
        stmt = select(Message).where(
            (Message.id > param("bound")) & (Message.subject != param("bound"))  # ty: ignore[unsupported-operator]
        )
        assert stmt.parameter_names() == ("bound",)


class TestLiteralAndRow:
    def test_literal_is_bound_not_interpolated(self) -> None:
        cypher, params = _build(select(Message).project(literal(42).as_("answer")))
        assert "$p0 AS `answer`" in cypher
        assert params == {"p0": 42}

    def test_row_renders_the_unwind_variable(self) -> None:
        assert isinstance(row("group_id"), RowRef)
        assert row("group_id").to_cypher(MagicMock()) == "row.`group_id`"

    def test_row_variable_is_configurable(self) -> None:
        assert row("id", var="entry").to_cypher(MagicMock()) == "entry.`id`"

    def test_row_key_must_be_an_identifier(self) -> None:
        with pytest.raises(ValueError, match="row key"):
            row("id} SET n.x = 1 //")


class TestFunctions:
    def test_fn_binds_its_arguments(self) -> None:
        cypher, params = _build(
            select(Message).project(
                left(Message.body_clean, param("max_chars")).as_("body")
            )
        )
        assert "left(n.`body_clean`, $max_chars) AS `body`" in cypher
        assert params == {}

    def test_plain_values_in_a_function_are_bound(self) -> None:
        cypher, params = _build(
            select(Message).project(fn("left", Message.subject, 80).as_("s"))
        )
        assert "left(n.`subject`, $p0) AS `s`" in cypher
        assert params == {"p0": 80}

    def test_coalesce_and_to_lower(self) -> None:
        cypher, _ = _build(
            select(Message).project(
                coalesce(Message.subject, Message.subject_norm).as_("t"),
                to_lower(Message.subject).as_("lower"),
            )
        )
        assert "coalesce(n.`subject`, n.`subject_norm`) AS `t`" in cypher
        assert "toLower(n.`subject`) AS `lower`" in cypher

    def test_function_name_must_be_an_identifier(self) -> None:
        with pytest.raises(ValueError, match="function name"):
            fn("left(x) RETURN n //", Message.subject)

    def test_is_an_fncall(self) -> None:
        assert isinstance(left(Message.id, 3), FnCall)


class TestCase:
    def test_conditional_aggregation(self) -> None:
        cypher, _ = _build(
            select(Message).project(
                count(when(Message.embedding_model == param("model"), 1)).as_(  # ty: ignore[invalid-argument-type]
                    "embedded"
                )
            )
        )
        assert "count(CASE WHEN n.`embedding_model` = $model THEN" in cypher
        assert "END) AS `embedded`" in cypher

    def test_else_is_omitted_unless_asked_for(self) -> None:
        cypher, _ = _build(
            select(Message).project(when(Message.id == param("x"), 1).as_("flag"))  # ty: ignore[invalid-argument-type]
        )
        assert "ELSE" not in cypher

    def test_else_is_emitted_when_given(self) -> None:
        cypher, _ = _build(
            select(Message).project(
                when(Message.id == param("x"), 1, else_=0).as_("flag")  # ty: ignore[invalid-argument-type]
            )
        )
        assert "ELSE" in cypher

    def test_several_branches(self) -> None:
        expr = when(
            Message.id == param("a"),  # ty: ignore[invalid-argument-type]
            1,
            Message.id == param("b"),
            2,
        )
        assert isinstance(expr, CaseExpr)
        assert len(expr.branches) == 2

    def test_odd_number_of_extra_args_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="condition/value pairs"):
            when(Message.id == param("a"), 1, Message.id == param("b"))  # ty: ignore[invalid-argument-type]


class TestAliasing:
    def test_as_wraps_in_an_aliased_expression(self) -> None:
        aliased = Message.id.as_("identifier")  # ty: ignore[unresolved-attribute]
        assert isinstance(aliased, AliasedExpr)
        assert aliased.result_name == "identifier"

    def test_alias_must_be_an_identifier(self) -> None:
        with pytest.raises(ValueError, match="result alias"):
            Message.id.as_("id, count(*)")  # ty: ignore[unresolved-attribute]


# ---------------------------------------------------------------------------
# Comparison between expressions
# ---------------------------------------------------------------------------


class TestFieldToFieldComparison:
    def test_two_properties_compare_without_a_parameter(self) -> None:
        a, b = alias(Address, "a"), alias(Address, "b")
        stmt = select(a).traverse(a.co_addressed, to=b, edge="r").where(a.id < b.id)
        cypher, params = _build(stmt)
        assert "a.`id` < b.`id`" in cypher
        assert params == {}

    def test_bare_descriptors_compare_without_a_parameter(self) -> None:
        """A field against a field never binds the descriptor as a value."""
        cypher, params = _build(
            select(Message).where(Message.id < Message.subject)  # ty: ignore[unsupported-operator]
        )
        assert "n.`id` < n.`subject`" in cypher
        assert params == {}

    def test_cross_alias_predicate_follows_the_traversal(self) -> None:
        """It cannot precede the MATCH that introduces the other variable."""
        a, b = alias(Address, "a"), alias(Address, "b")
        stmt = select(a).traverse(a.co_addressed, to=b, edge="r").where(a.id < b.id)
        cypher, _ = _build(stmt)
        assert cypher.index("MATCH (a)-[r:CO_ADDRESSED]-") < cypher.index(
            "a.`id` < b.`id`"
        )

    def test_root_only_predicate_still_precedes_the_traversal(self) -> None:
        a, b = alias(Address, "a"), alias(Address, "b")
        stmt = (
            select(a)
            .where(a.id == param("wanted"))
            .traverse(a.co_addressed, to=b, edge="r")
        )
        cypher, _ = _build(stmt)
        assert cypher.index("a.`id` = $wanted") < cypher.index("MATCH (a)-[r:")


class TestReverseMembership:
    def test_any_of_asks_the_list_containment_question(self) -> None:
        cypher, _ = _build(
            select(Message).where(Message.refs.any_of(param("token")))  # ty: ignore[unresolved-attribute]
        )
        assert "$token IN n.`refs`" in cypher

    def test_in_asks_the_opposite_question(self) -> None:
        cypher, _ = _build(select(Message).where(Message.id.in_(["a", "b"])))  # ty: ignore[unresolved-attribute]
        assert "n.`id` IN $p0" in cypher


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


class TestParameterisedPaging:
    def test_limit_accepts_a_parameter(self) -> None:
        cypher, _ = _build(select(Message).limit(param("limit")))
        assert cypher.endswith("LIMIT $limit")

    def test_skip_accepts_a_parameter(self) -> None:
        cypher, _ = _build(select(Message).skip(param("offset")).limit(param("limit")))
        assert "SKIP $offset" in cypher
        assert "LIMIT $limit" in cypher

    def test_integers_still_work(self) -> None:
        cypher, _ = _build(select(Message).limit(10))
        assert cypher.endswith("LIMIT 10")


# ---------------------------------------------------------------------------
# bind()
# ---------------------------------------------------------------------------


class TestBind:
    def test_merges_supplied_values_over_auto_bound_ones(self) -> None:
        stmt = select(Message).where(
            (Message.subject == "hi") & (Message.id > param("after"))  # ty: ignore[unsupported-operator]
        )
        with stmt._bound_to(_mock_session()) as bound:
            bound.build()
            merged = bound.bind({"after": "m1"})
        assert merged == {"p0": "hi", "after": "m1"}

    def test_missing_parameter_is_refused(self) -> None:
        stmt = select(Message).limit(param("limit"))
        stmt.build()
        with pytest.raises(ValueError, match=r"missing values.*limit"):
            stmt.bind({})

    def test_extra_parameters_are_tolerated(self) -> None:
        stmt = select(Message).limit(param("limit"))
        stmt.build()
        assert stmt.bind({"limit": 5, "unused": 1})["limit"] == 5


# ---------------------------------------------------------------------------
# encode_rows
# ---------------------------------------------------------------------------


class TestEncodeRows:
    def test_applies_field_converters(self) -> None:
        moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        [encoded] = encode_rows(Group, [{"id": "g1", "first_seen": moment}])
        assert encoded["id"] == "g1"
        assert isinstance(encoded["first_seen"], str), "datetime must be serialised"
        assert encoded["first_seen"].startswith("2026-01-02")

    def test_leaves_none_alone(self) -> None:
        [encoded] = encode_rows(Group, [{"id": "g1", "first_seen": None}])
        assert encoded["first_seen"] is None

    def test_passes_through_keys_that_are_not_fields(self) -> None:
        """An edge row carries endpoint ids alongside the edge's own properties."""
        [encoded] = encode_rows(Group, [{"message_id": "m1", "group_id": "g1"}])
        assert encoded == {"message_id": "m1", "group_id": "g1"}

    def test_handles_an_empty_input(self) -> None:
        assert encode_rows(Group, []) == []


# ---------------------------------------------------------------------------
# Statement reuse — the property a catalogue depends on
# ---------------------------------------------------------------------------


class TestStatementReuse:
    def test_a_statement_compiles_identically_twice(self) -> None:
        stmt = select(Message).where(Message.id > param("after")).limit(param("limit"))
        assert _build(stmt) == _build(stmt)

    def test_declared_parameters_do_not_accumulate(self) -> None:
        stmt = select(Message).where(Message.id > param("after"))
        stmt.build()
        stmt.build()
        assert stmt.parameter_names() == ("after",)

    def test_a_parameterised_statement_binds_no_values_of_its_own(self) -> None:
        """No caller input is baked in, which is what makes it safe to share."""
        stmt = select(Message).where(Message.id > param("after")).limit(param("limit"))
        _, params = _build(stmt)
        assert params == {}


def test_param_ref_type() -> None:
    assert isinstance(param("x"), ParamRef)
