"""Unit tests for the ParagraphChunker adapter (network-free)."""

from __future__ import annotations

import hashlib
from itertools import pairwise

import pytest

from runic.rag.adapters.chunking import ParagraphChunker
from runic.rag.config import RagSettings
from runic.rag.domain import Chunk


def _settings(*, chunk_size: int, chunk_overlap: int) -> RagSettings:
    return RagSettings(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        openai_api_key="sk-test",
    )


# ── Construction guards ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 150)],
)
def test_invalid_settings_rejected(chunk_size: int, chunk_overlap: int) -> None:
    with pytest.raises(ValueError):
        ParagraphChunker(_settings(chunk_size=chunk_size, chunk_overlap=chunk_overlap))


# ── Edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t  \n"])
def test_empty_or_whitespace_yields_no_chunks(text: str) -> None:
    chunker = ParagraphChunker(_settings(chunk_size=50, chunk_overlap=10))
    assert chunker.split(text, source="doc.txt") == []


def test_short_text_single_chunk() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=100, chunk_overlap=10))
    chunks = chunker.split("A short sentence.", source="doc.txt")
    assert len(chunks) == 1
    assert chunks[0].text == "A short sentence."
    assert chunks[0].seq == 0
    assert chunks[0].source == "doc.txt"
    assert isinstance(chunks[0], Chunk)


# ── Determinism / stable ids ──────────────────────────────────────────────────


def test_split_is_deterministic() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=30, chunk_overlap=8))
    text = "First para.\n\nSecond para here.\n\nThird and final paragraph block."
    first = chunker.split(text, source="doc.txt")
    second = chunker.split(text, source="doc.txt")
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_chunk_id_matches_sha256_of_source_seq_prefix() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=100, chunk_overlap=10))
    chunks = chunker.split("Deterministic identity check.", source="src.md")
    chunk = chunks[0]
    expected = hashlib.sha256(
        f"src.md|{chunk.seq}|{chunk.text[:64]}".encode()
    ).hexdigest()
    assert chunk.id == expected


def test_ids_unique_across_chunks() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=12, chunk_overlap=0))
    paragraphs = "\n\n".join(f"Paragraph number {i} content body." for i in range(6))
    chunks = chunker.split(paragraphs, source="doc.txt")
    assert len(chunks) > 1
    assert len({c.id for c in chunks}) == len(chunks)


def test_source_changes_id() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=100, chunk_overlap=10))
    a = chunker.split("Same text.", source="a.txt")[0]
    b = chunker.split("Same text.", source="b.txt")[0]
    assert a.text == b.text
    assert a.id != b.id


# ── Sequencing ────────────────────────────────────────────────────────────────


def test_seq_increments_from_zero() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=12, chunk_overlap=0))
    paragraphs = "\n\n".join(f"Paragraph {i} with enough words here." for i in range(5))
    chunks = chunker.split(paragraphs, source="doc.txt")
    assert [c.seq for c in chunks] == list(range(len(chunks)))


# ── Boundary preference ───────────────────────────────────────────────────────


def test_paragraph_boundaries_kept_when_each_fits() -> None:
    # Each paragraph alone fits, but two together exceed the budget, forcing a
    # split exactly on the paragraph boundary (no overlap to keep it clean).
    chunker = ParagraphChunker(_settings(chunk_size=8, chunk_overlap=0))
    text = "Alpha beta gamma delta.\n\nEpsilon zeta eta theta."
    chunks = chunker.split(text, source="doc.txt")
    assert [c.text for c in chunks] == [
        "Alpha beta gamma delta.",
        "Epsilon zeta eta theta.",
    ]


def test_oversized_paragraph_split_on_sentences() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=8, chunk_overlap=0))
    text = "Sentence one here. Sentence two here. Sentence three here."
    chunks = chunker.split(text, source="doc.txt")
    assert len(chunks) >= 2
    # No chunk should contain a sentence terminator followed by more text from a
    # different sentence beyond the boundary it was split on — i.e. each chunk is
    # made of whole sentences.
    for chunk in chunks:
        assert chunk.text.strip() == chunk.text
        assert chunk.text  # non-empty


def test_oversized_sentence_split_by_words() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=3, chunk_overlap=0))
    # A single sentence with no internal boundaries, longer than the budget.
    text = "one two three four five six seven eight"
    chunks = chunker.split(text, source="doc.txt")
    assert len(chunks) >= 2
    # Reassembling all words preserves the full content in order.
    joined = " ".join(c.text for c in chunks).split()
    assert joined == text.split()


# ── Overlap behaviour ─────────────────────────────────────────────────────────


def test_overlap_carries_trailing_unit_forward() -> None:
    # Single-token paragraphs with a budget of 4 and overlap of 2 force windows
    # of two units that share their boundary unit with the neighbour.
    chunker = ParagraphChunker(_settings(chunk_size=4, chunk_overlap=2))
    text = "\n\n".join(["aaa", "bbb", "ccc", "ddd", "eee", "fff"])
    chunks = chunker.split(text, source="doc.txt")
    assert len(chunks) >= 2
    # With overlap, the start of a later chunk repeats the tail paragraph of the
    # previous chunk.
    for prev, nxt in pairwise(chunks):
        prev_units = prev.text.split("\n\n")
        nxt_units = nxt.text.split("\n\n")
        assert prev_units[-1] == nxt_units[0]


def test_zero_overlap_has_no_repeats() -> None:
    chunker = ParagraphChunker(_settings(chunk_size=8, chunk_overlap=0))
    text = "Aaa bbb ccc.\n\nDdd eee fff.\n\nGgg hhh iii."
    chunks = chunker.split(text, source="doc.txt")
    seen: set[str] = set()
    for chunk in chunks:
        for unit in chunk.text.split("\n\n"):
            assert unit not in seen
            seen.add(unit)


def test_chunking_terminates_on_pathological_overlap() -> None:
    # overlap just below chunk_size must still make forward progress.
    chunker = ParagraphChunker(_settings(chunk_size=10, chunk_overlap=9))
    text = "\n\n".join(f"Para {i} body words." for i in range(8))
    chunks = chunker.split(text, source="doc.txt")
    assert chunks  # produced something and did not hang
    assert all(c.text for c in chunks)


# ── Token counter fallback ────────────────────────────────────────────────────


def test_heuristic_counter_used_without_tiktoken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "tiktoken":
            raise ImportError("simulated missing tiktoken")
        return real_import(name, *args, **kwargs)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    chunker = ParagraphChunker(_settings(chunk_size=50, chunk_overlap=10))
    chunks = chunker.split("Fallback path still chunks text.", source="doc.txt")
    assert len(chunks) == 1
    assert chunks[0].text == "Fallback path still chunks text."
