"""Integration tests for Repository.find_all_paginated."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.driver.falkordb import FalkorDBDriver
from runic.orm.repository.pagination import Pageable
from runic.orm.repository.repository import Repository
from runic.orm.session.session import Session

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class PageItem(Node, labels=["PageItem"]):
    id: str = Field()
    name: str = Field()
    rank: int | None = Field(default=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph() -> Any:
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)
    g = db.select_graph(f"test_page_{secrets.token_hex(6)}")
    yield FalkorDBDriver(g)
    with contextlib.suppress(Exception):
        g.delete()


@pytest.fixture
def item_graph(graph: Any) -> Any:
    """Graph with 10 PageItem nodes ranked 1–10."""
    with Session(graph) as s:
        for i in range(1, 11):
            s.add(PageItem(id=f"item{i:02d}", name=f"Item {i:02d}", rank=i))
    return graph


# ---------------------------------------------------------------------------
# Basic pagination
# ---------------------------------------------------------------------------


def test_paginated_returns_page_instance(item_graph: Any) -> None:
    from runic.orm.repository.pagination import Page

    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert isinstance(page, Page)


def test_paginated_total_elements(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert page.total_elements == 10


def test_paginated_total_pages(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert page.total_pages == 2


def test_paginated_first_page_size(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert len(page) == 5


def test_paginated_second_page_size(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=1, size=5))
    assert len(page) == 5


def test_paginated_has_next_on_first_page(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert page.has_next() is True


def test_paginated_no_next_on_last_page(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=1, size=5))
    assert page.has_next() is False


def test_paginated_has_previous_on_second_page(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=1, size=5))
    assert page.has_previous() is True


def test_paginated_no_previous_on_first_page(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=5))
    assert page.has_previous() is False


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_paginated_order_by_rank_asc(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(
            Pageable(page=0, size=3, sort_by="rank", direction="ASC")
        )
    ranks = [item.rank for item in page]
    assert ranks == sorted(ranks)


def test_paginated_order_by_rank_desc(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(
            Pageable(page=0, size=3, sort_by="rank", direction="DESC")
        )
    ranks = [item.rank for item in page]
    assert ranks == sorted(ranks, reverse=True)


# ---------------------------------------------------------------------------
# Empty graph
# ---------------------------------------------------------------------------


def test_paginated_empty_graph(graph: Any) -> None:
    with Session(graph) as s:
        repo = Repository(s, PageItem)
        page = repo.find_all_paginated(Pageable(page=0, size=10))
    assert len(page) == 0
    assert page.total_elements == 0
    assert page.total_pages == 0
    assert page.has_next() is False
    assert page.has_previous() is False


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------


def test_pageable_next_navigates_correctly(item_graph: Any) -> None:
    pageable = Pageable(page=0, size=4)
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        page1 = repo.find_all_paginated(pageable)
        page2 = repo.find_all_paginated(pageable.next())

    ids_p1 = {item.id for item in page1}
    ids_p2 = {item.id for item in page2}
    assert len(ids_p1) == 4
    assert len(ids_p2) == 4
    assert ids_p1.isdisjoint(ids_p2)
