"""Unit tests for the document loaders (no network).

The PDF tests build a tiny PDF in memory with PyMuPDF and write it to a temp
file; if PDF creation is unsupported in the environment they skip rather than
fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runic.rag.adapters.documents import (
    load_markdown,
    load_pdf,
    load_pdf_pages,
    load_text,
    normalize_whitespace,
)


def _make_pdf(path: Path, pages: list[str]) -> None:
    """Write a small multi-page PDF at *path*, one string per page.

    Skips the calling test if PyMuPDF cannot create PDFs here.
    """
    import fitz

    try:
        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            page.insert_text((72, 72), body)
        doc.save(str(path))
        doc.close()
    except Exception as exc:  # noqa: BLE001 - environment may lack PDF write support
        pytest.skip(f"PDF creation unsupported: {exc}")


# ── normalize_whitespace ─────────────────────────────────────────────────────


def test_normalize_collapses_horizontal_runs() -> None:
    assert normalize_whitespace("a    b\t\tc") == "a b c"


def test_normalize_strips_outer_whitespace() -> None:
    assert normalize_whitespace("  \n  hello  \n  ") == "hello"


def test_normalize_collapses_blank_line_runs() -> None:
    assert normalize_whitespace("a\n\n\n\nb") == "a\n\nb"


def test_normalize_strips_trailing_spaces_per_line() -> None:
    assert normalize_whitespace("a   \nb   ") == "a\nb"


def test_normalize_empty_string() -> None:
    assert normalize_whitespace("") == ""


# ── load_text / load_markdown ────────────────────────────────────────────────


def test_load_text_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "doc.txt"
    path.write_text("Hello    world\n\n\n\nNext   paragraph\n", encoding="utf-8")
    assert load_text(path) == "Hello world\n\nNext paragraph"


def test_load_text_accepts_str_path(tmp_path: Path) -> None:
    path = tmp_path / "doc.txt"
    path.write_text("just text", encoding="utf-8")
    assert load_text(str(path)) == "just text"


def test_load_markdown_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Title\n\nSome   **bold**   text.\n", encoding="utf-8")
    assert load_markdown(path) == "# Title\n\nSome **bold** text."


def test_load_text_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_text(tmp_path / "nope.txt")


# ── load_pdf / load_pdf_pages ────────────────────────────────────────────────


def test_load_pdf_extracts_text(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, ["Hello PDF World"])
    text = load_pdf(path)
    assert "Hello PDF World" in text


def test_load_pdf_pages_returns_numbered_pages(tmp_path: Path) -> None:
    path = tmp_path / "multi.pdf"
    _make_pdf(path, ["First page body", "Second page body"])
    pages = load_pdf_pages(path)
    assert [num for num, _ in pages] == [1, 2]
    assert "First page body" in pages[0][1]
    assert "Second page body" in pages[1][1]


def test_load_pdf_page_range_is_inclusive_one_based(tmp_path: Path) -> None:
    path = tmp_path / "multi.pdf"
    _make_pdf(path, ["Alpha", "Bravo", "Charlie"])
    pages = load_pdf_pages(path, first_page=2, last_page=3)
    assert [num for num, _ in pages] == [2, 3]
    assert "Bravo" in pages[0][1]
    assert "Charlie" in pages[1][1]


def test_load_pdf_range_clamps_out_of_bounds(tmp_path: Path) -> None:
    path = tmp_path / "multi.pdf"
    _make_pdf(path, ["Alpha", "Bravo"])
    pages = load_pdf_pages(path, first_page=0, last_page=99)
    assert [num for num, _ in pages] == [1, 2]


def test_load_pdf_inverted_range_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "multi.pdf"
    _make_pdf(path, ["Alpha", "Bravo", "Charlie"])
    assert load_pdf_pages(path, first_page=3, last_page=1) == []


def test_load_pdf_first_page_only(tmp_path: Path) -> None:
    path = tmp_path / "multi.pdf"
    _make_pdf(path, ["Alpha", "Bravo"])
    text = load_pdf(path, last_page=1)
    assert "Alpha" in text
    assert "Bravo" not in text
