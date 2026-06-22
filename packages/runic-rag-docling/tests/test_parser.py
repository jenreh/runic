"""Unit tests for :class:`runic_rag_docling.parser.DoclingParser`.

Docling-free: an injected :class:`~tests.fakes.FakeConverter` provides the
Markdown, so the real ``DocumentConverter`` is never built. The suite proves the
parser satisfies the core ``DocumentParser`` port, returns the converter's
Markdown verbatim (delegating exactly once), and claims the right suffixes.
"""

from __future__ import annotations

import pytest
from runic.rag import RagError
from runic.rag.ports import DocumentParser

from runic_rag_docling import DoclingParser, DoclingSettings
from runic_rag_docling._converters import (
    LocalDoclingConverter,
    ServerDoclingConverter,
)
from tests.fakes import CANNED_MARKDOWN, FakeConverter


def test_satisfies_document_parser_port() -> None:
    """The adapter structurally satisfies the runtime-checkable port."""
    parser = DoclingParser(converter=FakeConverter())
    assert isinstance(parser, DocumentParser)


def test_parse_returns_converter_markdown() -> None:
    """``parse`` returns the converter's Markdown and delegates exactly once."""
    converter = FakeConverter()
    parser = DoclingParser(converter=converter)

    markdown = parser.parse("paper.pdf")

    assert markdown == CANNED_MARKDOWN
    assert converter.markdown_calls == ["paper.pdf"]
    # Parse-only: the structured-document path is never touched.
    assert converter.document_calls == []


def test_parse_propagates_custom_markdown() -> None:
    """A custom converter payload is returned unchanged (no re-formatting)."""
    converter = FakeConverter(markdown="# Custom\n\nbody\n")
    parser = DoclingParser(converter=converter)

    assert parser.parse("paper.docx") == "# Custom\n\nbody\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("report.pdf", True),
        ("NOTES.DOCX", True),
        ("page.html", True),
        ("plain.txt", False),
        ("data.json", False),
    ],
)
def test_supports_matrix(source: str, expected: bool) -> None:
    """``supports`` accepts Docling document suffixes, rejects the rest."""
    parser = DoclingParser(converter=FakeConverter())
    assert parser.supports(source) is expected


def test_default_converter_is_local_for_local_mode() -> None:
    """With no injected converter, ``local`` mode builds a LocalDoclingConverter."""
    parser = DoclingParser(DoclingSettings(mode="local"))
    assert isinstance(parser._converter, LocalDoclingConverter)


def test_default_converter_is_server_for_server_mode() -> None:
    """``server`` mode builds a ServerDoclingConverter from the server_url."""
    parser = DoclingParser(
        DoclingSettings(mode="server", server_url="http://localhost:5001")
    )
    assert isinstance(parser._converter, ServerDoclingConverter)


class _BoomConverter:
    """Converter whose Markdown step raises a raw (non-RagError) provider error."""

    def document_from_path(self, path: object) -> object:  # pragma: no cover - unused
        raise ValueError("document exploded")

    def markdown_from_path(self, path: object) -> str:
        raise ValueError("markdown exploded")


def test_parse_failure_is_wrapped_in_ragerror() -> None:
    """A raw converter failure surfaces as a typed RagError (cause preserved)."""
    parser = DoclingParser(converter=_BoomConverter())

    with pytest.raises(RagError) as excinfo:
        parser.parse("paper.pdf")

    assert isinstance(excinfo.value.__cause__, ValueError)


class _RagErrorConverter:
    """Converter that raises a typed RagError (e.g. a missing-install hint)."""

    def document_from_path(self, path: object) -> object:  # pragma: no cover - unused
        raise RagError("converter install hint")

    def markdown_from_path(self, path: object) -> str:
        raise RagError("converter install hint")


def test_existing_ragerror_propagates_unwrapped() -> None:
    """A RagError from the converter is re-raised as-is, not double-wrapped."""
    parser = DoclingParser(converter=_RagErrorConverter())

    with pytest.raises(RagError, match="converter install hint"):
        parser.parse("paper.pdf")
