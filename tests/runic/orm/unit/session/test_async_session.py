"""Unit tests for AsyncSession lifecycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.driver.falkordb import AsyncFalkorDBDriver
from runic.orm.exceptions import DetachedEntityError, OrmError
from runic.orm.session.async_session import AsyncSession

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class Widget(Node, labels=["Widget"]):
    id: str = Field()
    label: str = Field()


class GenWidget(Node, labels=["GenWidget"]):
    id: int | None = Field(default=None, generated=True)
    label: str = Field()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _empty_result() -> MagicMock:
    r = MagicMock()
    r.result_set = []
    return r


def _node_result(node_id: Any, labels: list[str], props: dict) -> MagicMock:
    falkor_node = MagicMock()
    falkor_node.id = node_id
    falkor_node.labels = labels
    falkor_node.properties = props
    r = MagicMock()
    r.result_set = [[falkor_node]]
    return r


@pytest.fixture
def async_graph() -> MagicMock:
    g = MagicMock()
    g.query = AsyncMock(return_value=_empty_result())
    return g


@pytest.fixture
def asession(async_graph: MagicMock) -> AsyncSession:
    return AsyncSession(AsyncFalkorDBDriver(async_graph))


# ---------------------------------------------------------------------------
# add / add_all
# ---------------------------------------------------------------------------


def test_async_add_pending(asession: AsyncSession) -> None:
    w = Widget(id="w1", label="Alpha")
    asession.add(w)
    assert w in asession._pending


def test_async_add_all(asession: AsyncSession) -> None:
    w1 = Widget(id="w1", label="A")
    w2 = Widget(id="w2", label="B")
    asession.add_all([w1, w2])
    assert w1 in asession._pending
    assert w2 in asession._pending


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


async def test_async_get_queries_graph(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    assert w.id == "w1"
    assert w.label == "X"
    async_graph.query.assert_awaited_once()


async def test_async_get_identity_map_hit(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w1 = await asession.get(Widget, "w1")
    w2 = await asession.get(Widget, "w1")
    assert w1 is w2
    async_graph.query.assert_awaited_once()


async def test_async_get_returns_none_when_missing(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    assert await asession.get(Widget, "missing") is None


# ---------------------------------------------------------------------------
# flush / commit
# ---------------------------------------------------------------------------


async def test_async_flush_creates_entity(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    w = Widget(id="w1", label="A")
    asession.add(w)
    await asession.flush()

    async_graph.query.assert_awaited()
    cypher: str = async_graph.query.call_args[0][0]
    assert "CREATE" in cypher


async def test_async_commit_clears_pending(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    asession.add(Widget(id="w1", label="A"))
    await asession.commit()
    assert len(asession._pending) == 0


async def test_async_flush_assigns_generated_id(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(99, ["GenWidget"], {"label": "G"})
    gw = GenWidget(label="G")
    asession.add(gw)
    await asession.flush()
    assert gw.id == 99
    assert (GenWidget, 99) in asession._identity_map


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


async def test_async_rollback_discards_pending(asession: AsyncSession) -> None:
    asession.add(Widget(id="w1", label="A"))
    await asession.rollback()
    assert len(asession._pending) == 0


async def test_async_rollback_expires_persistent(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    await asession.rollback()
    assert w.__dict__.get("_expired") is True


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_async_delete_stages_for_deletion(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    asession.delete(w)
    assert w in asession._deleted


async def test_async_delete_detached_raises(asession: AsyncSession) -> None:
    w = Widget(id="w1", label="X")
    with pytest.raises((DetachedEntityError, OrmError)):
        asession.delete(w)


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager_commits(async_graph: MagicMock) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    async with AsyncSession(AsyncFalkorDBDriver(async_graph)) as s:
        s.add(Widget(id="w1", label="A"))
    assert len(s._pending) == 0


async def test_async_context_manager_rolls_back_on_error(
    async_graph: MagicMock,
) -> None:
    w = Widget(id="w1", label="A")
    with pytest.raises(ValueError):
        async with AsyncSession(AsyncFalkorDBDriver(async_graph)) as s:
            s.add(w)
            raise ValueError("boom")
    assert len(s._pending) == 0


# ---------------------------------------------------------------------------
# expire / refresh
# ---------------------------------------------------------------------------


async def test_async_expire_marks_entity(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    asession.expire(w)
    assert w.__dict__.get("_expired") is True


async def test_async_refresh_reloads(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "Old"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None

    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "New"}
    )
    await asession.refresh(w)
    assert w.label == "New"


# ---------------------------------------------------------------------------
# expunge
# ---------------------------------------------------------------------------


async def test_async_expunge_removes_from_identity_map(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "X"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    asession.expunge(w)
    assert (Widget, "w1") not in asession._identity_map


async def test_async_execute_calls_graph(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    result = await asession.execute("MATCH (n) RETURN n")
    async_graph.query.assert_awaited()
    assert result is not None
