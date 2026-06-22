"""Stable chunk ids and the shared supported-suffix set.

:func:`make_chunk_id` mirrors the runic.rag default scheme byte-for-byte so a
Docling-produced :class:`~runic.rag.Chunk` collides with the built-in chunk of
the same ``(source, seq, text)`` — the ``MERGE`` on re-ingest stays idempotent
and never duplicates. :data:`SUPPORTED_SUFFIXES` is the single source of truth
for the file types the Docling adapters claim, shared by both
:class:`~runic_rag_docling.chunker.DoclingChunker` and
:class:`~runic_rag_docling.parser.DoclingParser` (DRY).
"""

from __future__ import annotations

import hashlib

__all__ = ["SUPPORTED_SUFFIXES", "make_chunk_id"]

# Number of leading characters of chunk text folded into its stable id.
# Mirrors ``runic.rag.adapters.chunking._ID_TEXT_PREFIX`` exactly.
_ID_TEXT_PREFIX = 64

# Lowercase file suffixes Docling parses structure-aware. ``str.endswith``
# accepts a tuple, so this doubles as the argument to ``supports()`` checks.
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".adoc",
    ".asciidoc",
    ".epub",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
)


def make_chunk_id(source: str, seq: int, text: str) -> str:
    """Return the deterministic chunk id for *source*, *seq*, and *text*.

    Identical to the runic.rag default (``runic.rag.adapters.chunking``): the
    SHA-256 hexdigest of the UTF-8 bytes of ``"{source}|{seq}|{text[:64]}"``.
    Keeping the formula byte-for-byte identical guarantees idempotent re-ingest.
    """
    payload = f"{source}|{seq}|{text[:_ID_TEXT_PREFIX]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
