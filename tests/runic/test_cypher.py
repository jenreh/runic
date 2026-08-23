"""Unit tests for the shared Cypher escaping helpers."""

import pytest

from runic.cypher import (
    escape_identifier,
    escape_string,
    validate_identifier,
    validate_order_term,
    validate_reference,
)


class TestEscapeIdentifier:
    def test_plain_identifier_is_backtick_quoted(self) -> None:
        assert escape_identifier("Person") == "`Person`"

    def test_embedded_backtick_is_doubled(self) -> None:
        assert escape_identifier("we`ird") == "`we``ird`"

    def test_breakout_attempt_is_neutralised(self) -> None:
        # A label trying to close the pattern and inject Cypher stays inside the
        # backtick quoting because every backtick is doubled.
        escaped = escape_identifier("Person) DETACH DELETE n //")
        assert escaped == "`Person) DETACH DELETE n //`"
        assert escaped.startswith("`")
        assert escaped.endswith("`")

    def test_unicode_identifier_is_preserved(self) -> None:
        assert escape_identifier("Pérson") == "`Pérson`"

    def test_control_character_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="control character"):
            escape_identifier("Person\n")


class TestEscapeString:
    def test_plain_string_is_single_quoted(self) -> None:
        assert escape_string("english") == "'english'"

    def test_single_quote_is_escaped(self) -> None:
        assert escape_string("it's") == "'it\\'s'"

    def test_backslash_is_escaped(self) -> None:
        assert escape_string("a\\b") == "'a\\\\b'"

    def test_breakout_attempt_is_neutralised(self) -> None:
        # A stopword/language trying to close the literal and inject a map field
        # cannot escape because the single quote is backslash-escaped.
        escaped = escape_string("english', injected: 'true")
        assert escaped == "'english\\', injected: \\'true'"

    def test_control_character_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="control character"):
            escape_string("bad\x00value")


class TestValidateIdentifier:
    @pytest.mark.parametrize("name", ["Person", "_Internal", "WORKS_FOR", "a1_b2"])
    def test_valid_identifiers_pass_through(self, name: str) -> None:
        assert validate_identifier(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "1Person",  # leading digit
            "Person:Admin",  # namespacing
            "Per son",  # whitespace
            "Person) DETACH DELETE n //",  # injection attempt
            "`backtick`",
            "",
        ],
    )
    def test_invalid_identifiers_are_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid Cypher"):
            validate_identifier(name)

    def test_kind_appears_in_error(self) -> None:
        with pytest.raises(ValueError, match="node label"):
            validate_identifier("bad label", "node label")


class TestValidateReference:
    @pytest.mark.parametrize(
        "expr",
        ["n", "total", "_x", "n.id", "u.created_at", "n0.p1"],
    )
    def test_valid_references_pass_through(self, expr: str) -> None:
        assert validate_reference(expr) == expr

    @pytest.mark.parametrize(
        "expr",
        [
            "n.id, count(*)",  # a second return item
            "count(n)",  # a function call
            "n.a.b",  # nested access
            "n) DETACH DELETE n //",  # injection attempt
            "n.id DESC",  # a sort direction is not a reference
            "*",  # only allowed for count(*)
            "",
            "1n",
        ],
    )
    def test_non_references_are_rejected(self, expr: str) -> None:
        with pytest.raises(ValueError, match="invalid Cypher"):
            validate_reference(expr)

    def test_star_allowed_only_when_opted_in(self) -> None:
        assert validate_reference("*", allow_star=True) == "*"
        with pytest.raises(ValueError, match="invalid Cypher"):
            validate_reference("*")

    def test_kind_appears_in_error(self) -> None:
        with pytest.raises(ValueError, match="group_by key"):
            validate_reference("n) DELETE n", "group_by key")


class TestValidateOrderTerm:
    @pytest.mark.parametrize(
        "expr",
        ["n.id", "total", "n.created_at DESC", "score ASC", "score asc", "total desc"],
    )
    def test_valid_order_terms_pass_through(self, expr: str) -> None:
        assert validate_order_term(expr) == expr

    @pytest.mark.parametrize(
        "expr",
        [
            "n.id DESC WITH n MATCH (x) DETACH DELETE x //",  # appended clause
            "n.id ASC, m.id DESC",  # a second sort key
            "n.id DESCENDING",  # not a Cypher direction
            "n.id DESC NULLS LAST",  # three tokens
            "count(n) DESC",  # a function call
            "",
            "   ",
        ],
    )
    def test_invalid_order_terms_are_rejected(self, expr: str) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_order_term(expr)

    def test_non_string_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="expected a string"):
            validate_order_term(None)  # ty: ignore[invalid-argument-type]

    def test_kind_appears_in_error(self) -> None:
        with pytest.raises(ValueError, match="order_by term"):
            validate_order_term("n.id BOGUS", "order_by term")
