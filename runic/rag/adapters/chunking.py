"""Paragraph-aware text chunking adapter for runic.rag.

:class:`ParagraphChunker` is the default :class:`~runic.rag.ports.Chunker`. It
splits raw text into overlapping windows of roughly ``chunk_size`` tokens,
preferring paragraph and then sentence boundaries so chunks stay semantically
coherent. Token counting uses :mod:`tiktoken` when importable and falls back to
a ``~4 chars/token`` heuristic otherwise; either way chunking is deterministic
and never touches the network.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Protocol

from runic.rag.domain import Chunk

if TYPE_CHECKING:
    from tiktoken import Encoding

    from runic.rag.config import RagSettings

log = logging.getLogger(__name__)

__all__ = ["ParagraphChunker"]

# Average characters per token for the heuristic fallback (OpenAI rule of thumb).
_CHARS_PER_TOKEN = 4
# Number of leading characters of chunk text folded into its stable id.
_ID_TEXT_PREFIX = 64

# Paragraphs are separated by one or more blank lines.
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
# Sentence boundaries: terminator + following whitespace (kept on the left side).
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class _TokenCounter(Protocol):
    """Strategy for counting tokens in a piece of text."""

    def count(self, text: str) -> int:
        """Return the number of tokens in *text*."""
        ...


class _TiktokenCounter:
    """Token counter backed by a :mod:`tiktoken` encoding."""

    def __init__(self, encoding: Encoding) -> None:
        self._encoding = encoding

    def count(self, text: str) -> int:
        """Return the exact tiktoken token count for *text*."""
        return len(self._encoding.encode(text))


class _HeuristicCounter:
    """Character-based token estimator (~``_CHARS_PER_TOKEN`` chars/token)."""

    def count(self, text: str) -> int:
        """Estimate the token count of *text* from its length."""
        if not text:
            return 0
        # Round up so any non-empty text counts as at least one token.
        return -(-len(text) // _CHARS_PER_TOKEN)


def _build_counter() -> _TokenCounter:
    """Return a tiktoken-backed counter, or the heuristic if unavailable."""
    try:
        import tiktoken
    except ImportError:
        log.debug("tiktoken unavailable; using char-based token heuristic")
        return _HeuristicCounter()
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - any encoding load failure → heuristic
        log.warning("tiktoken encoding load failed; using char-based heuristic")
        return _HeuristicCounter()
    return _TiktokenCounter(encoding)


class ParagraphChunker:
    """Default chunker splitting text on paragraph/sentence boundaries.

    Greedily packs whole paragraphs into a window until adding the next would
    exceed ``chunk_size`` tokens; paragraphs larger than the budget are split on
    sentence boundaries (and, as a last resort, by word count). Consecutive
    chunks overlap by approximately ``chunk_overlap`` tokens to preserve context
    across boundaries.
    """

    def __init__(self, settings: RagSettings) -> None:
        if settings.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if settings.chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if settings.chunk_overlap >= settings.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self._chunk_size = settings.chunk_size
        self._chunk_overlap = settings.chunk_overlap
        self._counter = _build_counter()

    def split(self, text: str, *, source: str) -> list[Chunk]:
        """Return ordered :class:`Chunk` objects for *text* tagged *source*."""
        units = self._segment(text)
        if not units:
            return []
        windows = self._pack(units)
        return [
            self._make_chunk(window, seq=seq, source=source)
            for seq, window in enumerate(windows)
        ]

    # ── Segmentation ────────────────────────────────────────────────────────

    def _segment(self, text: str) -> list[str]:
        """Split *text* into sentence-or-smaller units within the token budget."""
        units: list[str] = []
        for paragraph in _PARAGRAPH_RE.split(text):
            cleaned = paragraph.strip()
            if not cleaned:
                continue
            if self._counter.count(cleaned) <= self._chunk_size:
                units.append(cleaned)
            else:
                units.extend(self._split_paragraph(cleaned))
        return units

    def _split_paragraph(self, paragraph: str) -> list[str]:
        """Break an oversized *paragraph* into budget-sized sentence groups."""
        units: list[str] = []
        for sentence in _SENTENCE_RE.split(paragraph):
            cleaned = sentence.strip()
            if not cleaned:
                continue
            if self._counter.count(cleaned) <= self._chunk_size:
                units.append(cleaned)
            else:
                units.extend(self._split_by_words(cleaned))
        return units

    def _split_by_words(self, sentence: str) -> list[str]:
        """Last-resort split of an oversized *sentence* by word count."""
        words = sentence.split()
        units: list[str] = []
        current: list[str] = []
        for word in words:
            current.append(word)
            if self._counter.count(" ".join(current)) > self._chunk_size:
                # The last word tipped us over; flush the preceding words.
                if len(current) == 1:
                    units.append(word)
                    current = []
                else:
                    current.pop()
                    units.append(" ".join(current))
                    current = [word]
        if current:
            units.append(" ".join(current))
        return units

    # ── Packing & overlap ─────────────────────────────────────────────────────

    def _pack(self, units: list[str]) -> list[str]:
        """Greedily pack *units* into overlapping ``chunk_size`` windows."""
        windows: list[str] = []
        current: list[str] = []
        index = 0
        while index < len(units):
            unit = units[index]
            candidate = [*current, unit]
            if current and self._counter.count("\n\n".join(candidate)) > (
                self._chunk_size
            ):
                windows.append("\n\n".join(current))
                current = self._overlap_tail(current)
                # Re-evaluate the same unit against the new (overlapped) window.
                continue
            current = candidate
            index += 1
        if current:
            windows.append("\n\n".join(current))
        return windows

    def _overlap_tail(self, units: list[str]) -> list[str]:
        """Return the trailing units to carry into the next window as overlap."""
        if self._chunk_overlap <= 0:
            return []
        tail: list[str] = []
        for unit in reversed(units):
            candidate = [unit, *tail]
            if tail and self._counter.count("\n\n".join(candidate)) > (
                self._chunk_overlap
            ):
                break
            tail = candidate
            if len(tail) == len(units):
                # Never carry the entire window forward; that stalls progress.
                tail = tail[1:]
                break
        return tail

    # ── Chunk construction ────────────────────────────────────────────────────

    def _make_chunk(self, text: str, *, seq: int, source: str) -> Chunk:
        """Build a :class:`Chunk` with a stable content-addressed id."""
        return Chunk(id=_chunk_id(source, seq, text), text=text, seq=seq, source=source)


def _chunk_id(source: str, seq: int, text: str) -> str:
    """Return a deterministic id from *source*, *seq*, and a text prefix."""
    payload = f"{source}|{seq}|{text[:_ID_TEXT_PREFIX]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
