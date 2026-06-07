"""Integration tests for Repository.find_all with skip/limit."""

from __future__ import annotations

from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.repository.repository import Repository
from runic.orm.session.session import Session

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
def item_graph(graph_driver: Any) -> Any:
    """Graph with 10 PageItem nodes ranked 1–10."""
    with Session(graph_driver) as s:
        for i in range(1, 11):
            s.add(PageItem(id=f"item{i:02d}", name=f"Item {i:02d}", rank=i))
    return graph_driver


# ---------------------------------------------------------------------------
# find_all with skip/limit
# ---------------------------------------------------------------------------


def test_find_all_no_args_returns_all(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all()
    assert len(items) == 10


def test_find_all_with_limit_returns_correct_count(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(limit=5)
    assert len(items) == 5


def test_find_all_with_skip_and_limit(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(skip=5, limit=5)
    assert len(items) == 5


def test_find_all_skip_beyond_total_returns_empty(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(skip=99, limit=10)
    assert items == []


def test_find_all_limit_larger_than_total_returns_all(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(limit=100)
    assert len(items) == 10


def test_find_all_empty_graph(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(skip=0, limit=10)
    assert items == []


def test_find_all_returns_list_type(item_graph: Any) -> None:
    with Session(item_graph) as s:
        repo = Repository(s, PageItem)
        items = repo.find_all(limit=3)
    assert isinstance(items, list)
    assert all(isinstance(i, PageItem) for i in items)
