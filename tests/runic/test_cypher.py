"""Unit tests for the shared Cypher escaping helpers."""

import pytest

from runic.cypher import escape_identifier, escape_string, validate_identifier


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
