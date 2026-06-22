"""Live integration test for the local Docling pipeline (opt-in).

Marked ``integration`` and gated behind ``pytest.importorskip("docling")`` so the
default unit run (no ``docling`` installed) skips it cleanly. When ``docling`` is
present it builds a real one-page PDF with PyMuPDF (``fitz``, available via
``runic-py[graphrag]``) and asserts the in-process :class:`DoclingChunker`
returns non-empty, well-formed chunks — exercising the real ``DocumentConverter``
and ``HybridChunker`` end to end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from runic_rag_docling import DoclingChunker, DoclingSettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

# Skip the whole module unless docling is actually installed.
pytest.importorskip("docling")


def _one_page_pdf(tmp_path: Path) -> Path:
    """Render a tiny one-page PDF with a paragraph of text via PyMuPDF."""
    import fitz  # ty: ignore[unresolved-import]

    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Runic Graph-RAG turns documents into a knowledge graph. "
        "Docling parses this PDF structure-aware before chunking.",
        fontsize=12,
    )
    doc.save(str(path))
    doc.close()
    return path


def test_local_chunker_produces_non_empty_chunks(tmp_path: Path) -> None:
    """A real local Docling parse+chunk yields non-empty, source-tagged chunks."""
    pdf = _one_page_pdf(tmp_path)
    chunker = DoclingChunker(DoclingSettings(mode="local"))

    chunks = chunker.chunk_document(pdf)

    assert chunks, "expected at least one chunk from the one-page PDF"
    assert all(chunk.text.strip() for chunk in chunks)
    assert all(chunk.source == str(pdf) for chunk in chunks)
    assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))
