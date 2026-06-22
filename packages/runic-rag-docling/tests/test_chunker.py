"""Unit tests for :class:`runic_rag_docling.chunker.DoclingChunker`.

All tests are docling-free: a :class:`~tests.fakes.FakeConverter` and a
:class:`~tests.fakes.FakeHybridChunker` are injected (DIP), so the real
``HybridChunker`` is never built. The suite proves the adapter satisfies the
core ``DocumentChunker`` port, mirrors the core chunk-id formula exactly (so
re-ingest is idempotent), claims the right suffixes, and surfaces a missing
``docling`` install as a :class:`~runic.rag.RagError` with the install hint.
"""

from __future__ import annotations

import sys
import types

import pytest
from runic.rag import RagError
from runic.rag.ports import DocumentChunker

from runic_rag_docling import DoclingChunker, DoclingSettings
from runic_rag_docling._converters import (
    LocalDoclingConverter,
    ServerDoclingConverter,
)
from runic_rag_docling._ids import make_chunk_id
from tests.fakes import FakeConverter, FakeHybridChunker


def _chunker(bodies: list[str] | None = None) -> tuple[DoclingChunker, FakeConverter]:
    """Build a DoclingChunker over fresh fakes; return it with its converter."""
    converter = FakeConverter()
    chunker = DoclingChunker(
        converter=converter,
        hybrid_chunker=FakeHybridChunker(bodies),
    )
    return chunker, converter


# ── Port conformance ─────────────────────────────────────────────────────────


def test_satisfies_document_chunker_port() -> None:
    """The adapter structurally satisfies the runtime-checkable port."""
    chunker, _ = _chunker()
    assert isinstance(chunker, DocumentChunker)


# ── chunk_document content ───────────────────────────────────────────────────


def test_chunk_document_returns_contextualized_chunks_in_order() -> None:
    """Each chunk holds the contextualized text with the right seq and source."""
    chunker, converter = _chunker(["alpha", "beta"])

    chunks = chunker.chunk_document("paper.pdf")

    assert [c.text for c in chunks] == ["ctx:alpha", "ctx:beta"]
    assert [c.seq for c in chunks] == [0, 1]
    assert {c.source for c in chunks} == {"paper.pdf"}
    # The converter parsed the original exactly once (fused parse+chunk).
    assert converter.document_calls == ["paper.pdf"]


def test_chunk_ids_match_core_formula_exactly() -> None:
    """Chunk ids equal ``make_chunk_id(source, seq, contextualized_text)``."""
    chunker, _ = _chunker(["alpha", "beta"])

    chunks = chunker.chunk_document("paper.pdf")

    assert [c.id for c in chunks] == [
        make_chunk_id("paper.pdf", 0, "ctx:alpha"),
        make_chunk_id("paper.pdf", 1, "ctx:beta"),
    ]


def test_explicit_source_overrides_path_for_id_and_tag() -> None:
    """A passed *source* tags the chunks and drives the id, not the path."""
    chunker, _ = _chunker(["alpha"])

    chunks = chunker.chunk_document("input/scratch.pdf", source="canonical.pdf")

    (chunk,) = chunks
    assert chunk.source == "canonical.pdf"
    assert chunk.id == make_chunk_id("canonical.pdf", 0, "ctx:alpha")


def test_chunk_ids_are_idempotent_across_calls() -> None:
    """Re-chunking the same file yields byte-identical ids (MERGE idempotency)."""
    chunker, _ = _chunker(["alpha", "beta", "gamma"])

    first = chunker.chunk_document("paper.pdf")
    second = chunker.chunk_document("paper.pdf")

    assert [c.id for c in first] == [c.id for c in second]


# ── supports() matrix ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("report.pdf", True),
        ("REPORT.PDF", True),
        ("notes.docx", True),
        ("deck.pptx", True),
        ("plain.txt", False),
        ("data.csv", False),
        ("archive.zip", False),
    ],
)
def test_supports_matrix(source: str, expected: bool) -> None:
    """``supports`` accepts Docling document suffixes, rejects the rest."""
    chunker, _ = _chunker()
    assert chunker.supports(source) is expected


# ── Converter selection (no docling import) ──────────────────────────────────


def test_default_converter_is_local_for_local_mode() -> None:
    """With no injected converter, ``local`` mode builds a LocalDoclingConverter."""
    chunker = DoclingChunker(
        DoclingSettings(mode="local"),
        hybrid_chunker=FakeHybridChunker(),
    )
    assert isinstance(chunker._converter, LocalDoclingConverter)


def test_default_converter_is_server_for_server_mode() -> None:
    """``server`` mode builds a ServerDoclingConverter from the server_url."""
    chunker = DoclingChunker(
        DoclingSettings(mode="server", server_url="http://localhost:5001"),
        hybrid_chunker=FakeHybridChunker(),
    )
    assert isinstance(chunker._converter, ServerDoclingConverter)


# ── Lazy-import failure path ─────────────────────────────────────────────────


def test_missing_docling_raises_ragerror_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``HybridChunker`` can't be imported, a RagError carries the hint.

    A stub ``docling.chunking`` module without ``HybridChunker`` is installed so
    the lazy ``from docling.chunking import HybridChunker`` raises ImportError —
    exercising the guard whether or not real docling is installed.
    """
    stub_pkg = types.ModuleType("docling")
    stub_chunking = types.ModuleType("docling.chunking")  # no HybridChunker attr
    monkeypatch.setitem(sys.modules, "docling", stub_pkg)
    monkeypatch.setitem(sys.modules, "docling.chunking", stub_chunking)
    # No injected hybrid_chunker -> the adapter must build one lazily and fail.
    chunker = DoclingChunker(DoclingSettings(), converter=FakeConverter())

    with pytest.raises(RagError) as excinfo:
        chunker.chunk_document("paper.pdf")

    message = str(excinfo.value)
    assert "docling" in message
    assert "uv add 'runic-rag-docling[local]'" in message


def test_injected_hybrid_chunker_short_circuits_docling_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected hybrid chunker is used directly — docling is never imported."""
    # Build the adapter (and its fakes) first, then forbid all further imports so
    # any attempt to lazily import docling would fail loudly.
    chunker, _ = _chunker(["alpha"])

    real_import = __import__

    def _guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "docling" or name.startswith("docling."):
            raise AssertionError("docling must not be imported when one is injected")
        # Forward verbatim; ty can't match the variadic against __import__'s
        # precise typeshed overloads, which is irrelevant for this test shim.
        return real_import(name, *args, **kwargs)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr("builtins.__import__", _guarded_import)

    chunks = chunker.chunk_document("paper.pdf")

    assert [c.text for c in chunks] == ["ctx:alpha"]


# ── Runtime-failure handling (typed errors, concept §5.1) ────────────────────


class _BoomConverter:
    """Converter whose parse step raises a raw (non-RagError) provider error."""

    def document_from_path(self, path: object) -> object:
        raise ValueError("parse exploded")

    def markdown_from_path(self, path: object) -> str:  # pragma: no cover - unused
        raise ValueError("markdown exploded")


class _BoomHybrid:
    """Hybrid chunker whose ``chunk`` raises while the document is walked."""

    def chunk(self, doc: object) -> object:
        raise RuntimeError("chunk exploded")

    def contextualize(self, raw: object) -> str:  # pragma: no cover - never reached
        return ""


def test_parse_failure_is_wrapped_in_ragerror() -> None:
    """A raw converter failure surfaces as a typed RagError (cause preserved)."""
    chunker = DoclingChunker(
        converter=_BoomConverter(), hybrid_chunker=FakeHybridChunker()
    )

    with pytest.raises(RagError) as excinfo:
        chunker.chunk_document("paper.pdf")

    assert isinstance(excinfo.value.__cause__, ValueError)


def test_chunk_failure_is_wrapped_in_ragerror() -> None:
    """A HybridChunker failure during chunking surfaces as a typed RagError."""
    chunker = DoclingChunker(converter=FakeConverter(), hybrid_chunker=_BoomHybrid())

    with pytest.raises(RagError) as excinfo:
        chunker.chunk_document("paper.pdf")

    assert isinstance(excinfo.value.__cause__, RuntimeError)


class _RagErrorConverter:
    """Converter that raises a typed RagError (e.g. a missing-install hint)."""

    def document_from_path(self, path: object) -> object:
        raise RagError("converter install hint")

    def markdown_from_path(self, path: object) -> str:  # pragma: no cover - unused
        raise RagError("converter install hint")


def test_existing_ragerror_propagates_unwrapped() -> None:
    """A RagError from a collaborator is re-raised as-is, not double-wrapped."""
    chunker = DoclingChunker(
        converter=_RagErrorConverter(), hybrid_chunker=FakeHybridChunker()
    )

    with pytest.raises(RagError, match="converter install hint"):
        chunker.chunk_document("paper.pdf")
