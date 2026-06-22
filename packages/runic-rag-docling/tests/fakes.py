"""Deterministic, docling-free fakes for the add-on unit suite.

These doubles stand in for the heavy Docling collaborators so the unit tests run
without ``docling`` / ``docling-core`` installed (concept §11). They mirror the
narrow seams the adapters depend on (DIP): :class:`FakeConverter` implements the
``_DoclingConverter`` protocol, and :class:`FakeHybridChunker` mimics the slice
of Docling's ``HybridChunker`` that :class:`DoclingChunker` actually calls
(``chunk`` + ``contextualize``). No ``docling`` import lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "FakeConverter",
    "FakeHybridChunker",
    "FakeRawChunk",
    "SentinelDoc",
]

# Canned Markdown the fake converter returns for any path. Kept tiny but
# multi-block so ``parse`` assertions stay meaningful.
CANNED_MARKDOWN = "# Title\n\nFirst body paragraph.\n\nSecond body paragraph.\n"


@dataclass(frozen=True)
class SentinelDoc:
    """Trivial stand-in for a ``DoclingDocument``.

    Carries only the originating path so tests can assert the converter handed
    the *same* document object on to the chunker; it has no Docling behavior.
    """

    source: str


@dataclass(frozen=True)
class FakeRawChunk:
    """Trivial stand-in for a raw ``HybridChunker`` chunk (pre-contextualize)."""

    body: str


class FakeConverter:
    """In-memory :class:`_DoclingConverter`: no parsing, fully deterministic.

    ``document_from_path`` returns a :class:`SentinelDoc` tagged with the path;
    ``markdown_from_path`` returns :data:`CANNED_MARKDOWN`. Both record their
    calls so tests can assert the adapter delegated exactly once.
    """

    def __init__(self, markdown: str = CANNED_MARKDOWN) -> None:
        self._markdown = markdown
        self.document_calls: list[str] = []
        self.markdown_calls: list[str] = []

    def document_from_path(self, path: str | Path) -> SentinelDoc:
        """Return a sentinel document tagged with *path*."""
        self.document_calls.append(str(path))
        return SentinelDoc(source=str(path))

    def markdown_from_path(self, path: str | Path) -> str:
        """Return the canned Markdown for *path*."""
        self.markdown_calls.append(str(path))
        return self._markdown


class FakeHybridChunker:
    """Mimic the ``HybridChunker`` slice :class:`DoclingChunker` consumes.

    ``chunk(doc)`` yields a few :class:`FakeRawChunk` objects; ``contextualize``
    prepends a deterministic ``"ctx:"`` marker so tests can prove the adapter
    stores the *contextualized* text (headings/captions prepended), not the raw
    body. The default bodies are independent of *doc*, which is all the unit
    tests need.
    """

    def __init__(self, bodies: list[str] | None = None) -> None:
        self._bodies = bodies if bodies is not None else ["alpha", "beta", "gamma"]
        self.chunk_calls: list[Any] = []

    def chunk(self, doc: Any) -> Iterator[FakeRawChunk]:
        """Yield one raw chunk per configured body (order preserved)."""
        self.chunk_calls.append(doc)
        for body in self._bodies:
            yield FakeRawChunk(body=body)

    def contextualize(self, raw: FakeRawChunk) -> str:
        """Return the deterministic contextualized text for *raw*."""
        return "ctx:" + raw.body
