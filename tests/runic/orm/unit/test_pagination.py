"""Unit tests for Pageable and Page."""

from __future__ import annotations

import pytest

from runic.orm.repository.pagination import Page, Pageable

# ---------------------------------------------------------------------------
# Pageable
# ---------------------------------------------------------------------------


def test_pageable_defaults() -> None:
    p = Pageable()
    assert p.page == 0
    assert p.size == 20
    assert p.sort_by is None
    assert p.direction == "ASC"


def test_pageable_offset() -> None:
    p = Pageable(page=2, size=25)
    assert p.offset == 50


def test_pageable_offset_page_zero() -> None:
    assert Pageable(page=0, size=10).offset == 0


def test_pageable_next() -> None:
    p = Pageable(page=1, size=10, sort_by="name", direction="DESC")
    n = p.next()
    assert n.page == 2
    assert n.size == 10
    assert n.sort_by == "name"
    assert n.direction == "DESC"


def test_pageable_previous() -> None:
    p = Pageable(page=3, size=10)
    assert p.previous().page == 2


def test_pageable_previous_clamped_to_zero() -> None:
    p = Pageable(page=0, size=10)
    assert p.previous().page == 0


def test_pageable_first() -> None:
    p = Pageable(page=5, size=10, sort_by="id")
    first = p.first()
    assert first.page == 0
    assert first.size == 10
    assert first.sort_by == "id"


def test_pageable_rejects_negative_page() -> None:
    with pytest.raises(ValueError, match="page must be >= 0"):
        Pageable(page=-1)


def test_pageable_rejects_zero_size() -> None:
    with pytest.raises(ValueError, match="size must be > 0"):
        Pageable(size=0)


def test_pageable_repr() -> None:
    p = Pageable(page=1, size=5, sort_by="name", direction="ASC")
    assert "page=1" in repr(p)
    assert "size=5" in repr(p)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def test_page_total_pages_exact_division() -> None:
    page = Page(items=list(range(10)), page_number=0, size=10, total_elements=30)
    assert page.total_pages == 3


def test_page_total_pages_with_remainder() -> None:
    page = Page(items=list(range(5)), page_number=0, size=10, total_elements=25)
    assert page.total_pages == 3


def test_page_total_pages_zero_elements() -> None:
    page = Page(items=[], page_number=0, size=10, total_elements=0)
    assert page.total_pages == 0


def test_page_has_next_true() -> None:
    page = Page(items=list(range(10)), page_number=0, size=10, total_elements=30)
    assert page.has_next() is True


def test_page_has_next_false_last_page() -> None:
    page = Page(items=list(range(10)), page_number=2, size=10, total_elements=30)
    assert page.has_next() is False


def test_page_has_previous_true() -> None:
    page = Page(items=[], page_number=1, size=10, total_elements=20)
    assert page.has_previous() is True


def test_page_has_previous_false_first_page() -> None:
    page = Page(items=[], page_number=0, size=10, total_elements=20)
    assert page.has_previous() is False


def test_page_iteration() -> None:
    items = ["a", "b", "c"]
    page = Page(items=items, page_number=0, size=10, total_elements=3)
    assert list(page) == items


def test_page_len() -> None:
    page = Page(items=[1, 2, 3], page_number=0, size=10, total_elements=3)
    assert len(page) == 3


def test_page_repr() -> None:
    page = Page(items=[], page_number=0, size=10, total_elements=42)
    r = repr(page)
    assert "page=0" in r
    assert "total_elements=42" in r
