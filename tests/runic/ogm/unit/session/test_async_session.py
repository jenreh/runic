"""Unit tests for AsyncSession lifecycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runic.ogm.core.descriptors import _NOT_LOADED, Field, Relation
from runic.ogm.core.models import Node
from runic.ogm.driver.falkordb import AsyncFalkorDBDriver
from runic.ogm.exceptions import DetachedEntityError, LazyLoadError, OrmError
from runic.ogm.query import select
from runic.ogm.session.async_session import AsyncSession

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class Gadget(Node, labels=["AsyncGadget"]):
    id: str = Field()
    label: str = Field()


class Widget(Node, labels=["Widget"]):
    id: str = Field()
    label: str = Field()
    gadgets: list[Gadget] = Relation(
        relationship="HAS_GADGET", direction="OUTGOING", target=Gadget
    )


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


# ---------------------------------------------------------------------------
# relate / unrelate
#
# These and the query-builder terminals below mirror methods that AsyncSession
# spells out separately from Session. The sync twin is covered by the live
# integration suite; the async one has no live backend (redislite offers no
# working async client), so the await-and-delegate wiring is pinned here.
# ---------------------------------------------------------------------------


async def test_async_relate_runs_the_query_and_expires_the_field(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    src = await asession.get(Widget, "w1")
    tgt = Gadget(id="g1", label="B")
    assert src is not None

    async_graph.query.reset_mock()
    async_graph.query.return_value = _empty_result()
    await asession.relate(src, "gadgets", tgt)

    async_graph.query.assert_awaited()
    cypher: str = async_graph.query.call_args[0][0]
    assert "MERGE" in cypher
    assert src.__dict__.get("gadgets") is _NOT_LOADED


async def test_async_unrelate_runs_the_query_and_expires_the_field(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    src = await asession.get(Widget, "w1")
    tgt = Gadget(id="g1", label="B")
    assert src is not None

    async_graph.query.reset_mock()
    async_graph.query.return_value = _empty_result()
    await asession.unrelate(src, "gadgets", tgt)

    async_graph.query.assert_awaited()
    cypher: str = async_graph.query.call_args[0][0]
    assert "DELETE" in cypher
    assert src.__dict__.get("gadgets") is _NOT_LOADED


# ---------------------------------------------------------------------------
# Query-builder terminals
# ---------------------------------------------------------------------------


async def test_async_scalars_decodes_nodes(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    widgets = await asession.scalars(select(Widget))
    async_graph.query.assert_awaited()
    assert [w.id for w in widgets] == ["w1"]


async def test_async_scalar_returns_the_first_row(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    widget = await asession.scalar(select(Widget))
    assert widget is not None
    assert widget.id == "w1"


async def test_async_scalar_returns_none_when_empty(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    assert await asession.scalar(select(Widget)) is None


async def test_async_scalar_restores_the_statement_limit(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    """The LIMIT 1 that scalar() imposes must not leak back to the caller."""
    async_graph.query.return_value = _empty_result()
    stmt = select(Widget).limit(25)
    await asession.scalar(stmt)
    assert stmt._limit_val == 25


async def test_async_all_rows_returns_column_keyed_dicts(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    result = MagicMock()
    result.result_set = [["w1", "A"]]
    result.header = [(1, "id"), (1, "label")]
    async_graph.query.return_value = result

    rows = await asession.all_rows(select(Widget).project(Widget.id, Widget.label))
    assert rows == [{"id": "w1", "label": "A"}]


async def test_async_all_with_edges_decodes_edge_rows(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    assert await asession.all_with_edges(select(Widget)) == []
    async_graph.query.assert_awaited()


async def test_async_count_returns_the_scalar(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    result = MagicMock()
    result.result_set = [[7]]
    result.header = [(1, "_count")]
    async_graph.query.return_value = result

    assert await asession.count(select(Widget)) == 7
    cypher: str = async_graph.query.call_args[0][0]
    assert "count(*)" in cypher


async def test_async_count_returns_zero_when_empty(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    assert await asession.count(select(Widget)) == 0


async def test_async_count_restores_the_statement_projection(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    """count() swaps the RETURN out and back; the caller's stmt must survive."""
    async_graph.query.return_value = _empty_result()
    stmt = select(Widget).project(Widget.label).limit(5)
    before = list(stmt._project_fields)
    await asession.count(stmt)
    assert stmt._project_fields == before
    assert stmt._limit_val == 5


async def test_async_query_terminals_reject_a_raw_string(
    asession: AsyncSession,
) -> None:
    with pytest.raises(TypeError, match="expects a QueryBuilder"):
        await asession.scalars("MATCH (n) RETURN n")  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# get(fetch=...) / flush of dirty and deleted entities
# ---------------------------------------------------------------------------


async def test_async_get_with_fetch_issues_one_query(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _empty_result()
    assert await asession.get(Widget, "w1", fetch=["gadgets"]) is None
    async_graph.query.assert_awaited_once()


async def test_async_flush_updates_a_dirty_entity(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "Old"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None

    w.label = "New"
    assert w._dirty is True

    async_graph.query.reset_mock()
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "New"}
    )
    await asession.flush()

    async_graph.query.assert_awaited()
    cypher: str = async_graph.query.call_args[0][0]
    assert "SET" in cypher or "MERGE" in cypher
    assert w._dirty is False


async def test_async_flush_deletes_a_staged_entity(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    asession.delete(w)

    async_graph.query.reset_mock()
    async_graph.query.return_value = _empty_result()
    await asession.flush()

    cypher: str = async_graph.query.call_args[0][0]
    assert "DETACH DELETE" in cypher
    assert (Widget, "w1") not in asession._identity_map


# ---------------------------------------------------------------------------
# Deliberate divergences from Session
# ---------------------------------------------------------------------------


async def test_async_lazy_relationship_load_is_refused(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    """Lazy loading is unsupported in async and must stay a loud failure.

    This is an intentional divergence from Session, not drift: touching a
    relationship would need a blocking query. The message has to name the
    eager alternative, because the attribute access that triggers it looks
    innocuous at the call site.
    """
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "A"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None

    with pytest.raises(LazyLoadError, match="fetch="):
        asession.load_relationship(w, "gadgets")


async def test_async_query_returns_an_async_builder(asession: AsyncSession) -> None:
    from runic.ogm.query.specialised import AsyncQueryBuilder

    assert isinstance(asession.query(Widget), AsyncQueryBuilder)


async def test_async_get_reloads_an_expired_entity(
    asession: AsyncSession, async_graph: MagicMock
) -> None:
    """An expired entity in the identity map is re-fetched, not served stale."""
    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "Old"}
    )
    w = await asession.get(Widget, "w1")
    assert w is not None
    asession.expire(w)

    async_graph.query.return_value = _node_result(
        0, ["Widget"], {"id": "w1", "label": "Fresh"}
    )
    again = await asession.get(Widget, "w1")
    assert again is w
    assert again.label == "Fresh"
