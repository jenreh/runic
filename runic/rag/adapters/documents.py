"""Dependency-light document loaders for runic.rag ingestion.

These helpers turn on-disk documents into normalized plain text suitable for
chunking. Plain-text and Markdown files are read directly; PDFs are parsed with
PyMuPDF (imported as ``fitz``). All loaders collapse runs of whitespace so the
downstream chunker sees clean, predictable input.

The loaders are intentionally free of any RAG domain types: they map a path to
``str`` (or, for :func:`load_pdf_pages`, to per-page text), and nothing more.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

log = logging.getLogger(__name__)

__all__ = [
    "load_markdown",
    "load_pdf",
    "load_pdf_pages",
    "load_text",
    "normalize_whitespace",
]

# Collapse any run of horizontal whitespace to a single space.
_HSPACE_RE = re.compile(r"[^\S\n]+")
# Collapse three-or-more newlines (paragraph gaps) to exactly two.
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    """Return *text* with whitespace collapsed and trimmed.

    Horizontal whitespace runs become a single space, trailing spaces on each
    line are stripped, and three-or-more consecutive newlines collapse to a
    blank-line separator. Leading/trailing whitespace of the whole string is
    removed.
    """
    collapsed = _HSPACE_RE.sub(" ", text)
    # Strip trailing spaces left on each line after horizontal collapse.
    collapsed = "\n".join(line.rstrip() for line in collapsed.split("\n"))
    collapsed = _BLANK_LINES_RE.sub("\n\n", collapsed)
    return collapsed.strip()


def load_text(path: str | Path) -> str:
    """Read a UTF-8 text file at *path* and return normalized text."""
    raw = Path(path).read_text(encoding="utf-8")
    log.debug("Loaded text file %s (%d chars)", path, len(raw))
    return normalize_whitespace(raw)


def load_markdown(path: str | Path) -> str:
    """Read a Markdown file at *path* and return normalized text.

    Markdown is treated as plain text here; structure-aware parsing is left to
    the chunker. Whitespace is normalized like :func:`load_text`.
    """
    raw = Path(path).read_text(encoding="utf-8")
    log.debug("Loaded markdown file %s (%d chars)", path, len(raw))
    return normalize_whitespace(raw)


def load_pdf(
    path: str | Path,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
) -> str:
    """Extract normalized text from a PDF, optionally bounded by page range.

    *first_page* and *last_page* are 1-based and inclusive (matching how people
    refer to PDF pages); ``None`` means "from the start" / "to the end". Pages
    are joined with a blank line and the whole result is whitespace-normalized.
    """
    pages = load_pdf_pages(path, first_page=first_page, last_page=last_page)
    joined = "\n\n".join(text for _, text in pages)
    return normalize_whitespace(joined)


def load_pdf_pages(
    path: str | Path,
    *,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[tuple[int, str]]:
    """Return ``(page_number, text)`` pairs for a PDF, page numbers 1-based.

    Each page's text is whitespace-normalized independently so callers can do
    page-aware or bounded ingestion. *first_page* / *last_page* are 1-based and
    inclusive; out-of-range bounds are clamped to the document.
    """
    spec = str(path)
    with fitz.open(spec) as doc:
        start, end = _resolve_page_range(doc.page_count, first_page, last_page)
        results: list[tuple[int, str]] = []
        for index in range(start, end):
            text = normalize_whitespace(doc[index].get_text())
            results.append((index + 1, text))
    log.debug(
        "Loaded PDF %s pages %d-%d (%d pages)", path, start + 1, end, len(results)
    )
    return results


def _resolve_page_range(
    page_count: int,
    first_page: int | None,
    last_page: int | None,
) -> tuple[int, int]:
    """Translate 1-based inclusive bounds to a 0-based half-open ``[start, end)``.

    Bounds are clamped into ``[0, page_count]``; an inverted range yields an
    empty slice (``start == end``).
    """
    start = 0 if first_page is None else max(first_page - 1, 0)
    end = page_count if last_page is None else min(last_page, page_count)
    start = min(start, page_count)
    end = max(end, start)
    return start, end
