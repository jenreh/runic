"""Unit tests for Repository and AsyncRepository (mocked session)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.repository.async_repository import AsyncRepository
from runic.orm.repository.repository import Repository
from tests.runic.orm.unit.mock_helpers import (
    empty_result as _empty_result,
)
from tests.runic.orm.unit.mock_helpers import (
    multi_node_result as _multi_node_result,
)
from tests.runic.orm.unit.mock_helpers import (
    scalar_result as _scalar_result,
)

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class RepoPerson(Node, labels=["RepoPerson"]):
    id: str = Field()
    name: str = Field()


class RepoTag(Node, labels=["RepoTag"]):
    id: int | None = Field(default=None, generated=True)
    label: str = Field()


def _make_session(
    execute_results: list[Any] | None = None,
) -> MagicMock:
    """Build a mock Session with wired mapper and rel_loader."""
    session = MagicMock()
    session._identity_map = {}

    # Mapper stubs
    mapper = MagicMock()
    mapper.build_find_all_query.return_value = ("MATCH...", {})
    mapper.build_find_all_by_ids_query.return_value = ("MATCH...", {})
    mapper.build_count_query.return_value = ("COUNT...", {})
    mapper.build_exists_query.return_value = ("EXISTS...", {})
    session.mapper = mapper

    # rel_loader stubs
    rel_loader = MagicMock()
    rel_loader.build_find_all_with_fetch_query.return_value = ("FETCH_ALL...", {}, [])
    rel_loader.build_find_all_by_ids_with_fetch_query.return_value = (
        "FETCH_IDS...",
        {},
        [],
    )
    rel_loader.decode_eager_columns.return_value = []
    session.rel_loader = rel_loader

    # Queue execute return values
    results = list(execute_results or [_empty_result()])
    session.execute.side_effect = results

    # register_or_get: identity pass-through in tests
    session.register_or_get.side_effect = lambda e: e

    return session


# ---------------------------------------------------------------------------
# Repository — find_all
# ---------------------------------------------------------------------------


def test_find_all_returns_empty_when_no_results() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.find_all() == []


def test_find_all_decodes_nodes() -> None:
    result = _multi_node_result([(["RepoPerson"], {"id": "p1", "name": "Alice"})])
    session = _make_session([result])
    decoded = RepoPerson(id="p1", name="Alice")
    session.mapper.decode_node.return_value = decoded

    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    items = repo.find_all()

    assert len(items) == 1
    session.mapper.build_find_all_query.assert_called_once_with(
        RepoPerson, skip=0, limit=None
    )
    session.register_or_get.assert_called_once_with(decoded)


def test_find_all_with_skip_and_limit_calls_correct_query() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    repo.find_all(skip=5, limit=10)

    session.mapper.build_find_all_query.assert_called_once_with(
        RepoPerson, skip=5, limit=10
    )


def test_find_all_with_fetch_uses_rel_loader() -> None:
    session = _make_session([_empty_result()])
    session.rel_loader.build_find_all_with_fetch_query.return_value = (
        "FETCH_Q",
        {},
        [],
    )
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    repo.find_all(fetch=["company"])

    session.rel_loader.build_find_all_with_fetch_query.assert_called_once_with(
        RepoPerson, ["company"]
    )


def test_find_all_fetch_and_skip_raises_value_error() -> None:
    session = _make_session()
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    with pytest.raises(ValueError, match="fetch="):
        repo.find_all(fetch=["company"], skip=5)


def test_find_all_fetch_and_limit_raises_value_error() -> None:
    session = _make_session()
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    with pytest.raises(ValueError, match="fetch="):
        repo.find_all(fetch=["company"], limit=10)


# ---------------------------------------------------------------------------
# Repository — find_all_by_ids
# ---------------------------------------------------------------------------


def test_find_all_by_ids_empty_list_returns_empty() -> None:
    session = _make_session()
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    result = repo.find_all_by_ids([])
    assert result == []
    session.execute.assert_not_called()


def test_find_all_by_ids_calls_correct_query() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    repo.find_all_by_ids(["p1", "p2"])

    session.mapper.build_find_all_by_ids_query.assert_called_once_with(
        RepoPerson, ["p1", "p2"]
    )


# ---------------------------------------------------------------------------
# Repository — count
# ---------------------------------------------------------------------------


def test_count_returns_integer() -> None:
    session = _make_session([_scalar_result(42)])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.count() == 42


def test_count_returns_zero_on_empty_result() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.count() == 0


# ---------------------------------------------------------------------------
# Repository — exists
# ---------------------------------------------------------------------------


def test_exists_true_when_count_positive() -> None:
    session = _make_session([_scalar_result(1)])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.exists("p1") is True


def test_exists_false_when_count_zero() -> None:
    session = _make_session([_scalar_result(0)])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.exists("p99") is False


def test_exists_false_on_empty_result() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    assert repo.exists("p99") is False


# ---------------------------------------------------------------------------
# Repository — cypher helpers
# ---------------------------------------------------------------------------


def test_cypher_scalar_returns_list() -> None:
    session = _make_session([_scalar_result(7)])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    result = repo.cypher("MATCH ... RETURN count(n)", returns=int)
    assert result == [7]


def test_cypher_none_returns_returns_empty() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    result = repo.cypher("MATCH ... SET ...", write=True, returns=None)
    assert result == []


def test_cypher_one_returns_first_value() -> None:
    session = _make_session([_scalar_result(3)])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    val = repo.cypher_one("MATCH ... RETURN count(n)", returns=int)
    assert val == 3


def test_cypher_one_returns_none_on_empty() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    val = repo.cypher_one("MATCH (n) RETURN n LIMIT 1", returns=RepoPerson)
    assert val is None


def test_cypher_raw_returns_query_result() -> None:
    raw = _empty_result()
    session = _make_session([raw])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    result = repo.cypher_raw("MATCH (n) RETURN n")
    assert result is raw


def test_cypher_write_flag_forwarded() -> None:
    session = _make_session([_empty_result()])
    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    repo.cypher("SET ...", write=True, returns=None)
    session.execute.assert_called_once_with("SET ...", {}, write=True)


# ---------------------------------------------------------------------------
# Repository — identity map deduplication
# ---------------------------------------------------------------------------


def test_register_or_get_called_per_decoded_node() -> None:
    decoded = RepoPerson(id="p1", name="Alice")
    result = _multi_node_result([(["RepoPerson"], {"id": "p1", "name": "Alice"})])
    session = _make_session([result])
    session.mapper.decode_node.return_value = decoded

    repo: Repository[RepoPerson] = Repository(session, RepoPerson)
    items = repo.find_all()

    session.register_or_get.assert_called_once_with(decoded)
    assert items == [decoded]


# ---------------------------------------------------------------------------
# AsyncRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_find_all_empty() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_find_all_query.return_value = ("MATCH...", {})
    session.rel_loader = MagicMock()
    session.register_or_get.side_effect = lambda e: e

    empty = _empty_result()
    session.execute = AsyncMock(return_value=empty)

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    items = await repo.find_all()
    assert items == []


@pytest.mark.asyncio
async def test_async_find_all_with_skip_and_limit() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_find_all_query.return_value = ("MATCH...", {})
    session.rel_loader = MagicMock()
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_empty_result())

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    await repo.find_all(skip=10, limit=5)

    session.mapper.build_find_all_query.assert_called_once_with(
        RepoPerson, skip=10, limit=5
    )


@pytest.mark.asyncio
async def test_async_find_all_fetch_and_skip_raises_value_error() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.rel_loader = MagicMock()
    session.rel_loader.build_find_all_with_fetch_query.return_value = ("Q", {}, [])

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    with pytest.raises(ValueError, match="fetch="):
        await repo.find_all(fetch=["company"], skip=5)


@pytest.mark.asyncio
async def test_async_count() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_count_query.return_value = ("COUNT...", {})
    session.execute = AsyncMock(return_value=_scalar_result(5))

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    assert await repo.count() == 5


@pytest.mark.asyncio
async def test_async_exists_true() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_exists_query.return_value = ("EXISTS...", {})
    session.execute = AsyncMock(return_value=_scalar_result(1))

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    assert await repo.exists("p1") is True


@pytest.mark.asyncio
async def test_async_cypher_one_none_on_empty() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_empty_result())

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    result = await repo.cypher_one("MATCH (n) RETURN n", returns=RepoPerson)
    assert result is None


@pytest.mark.asyncio
async def test_async_cypher_raw() -> None:
    raw = _empty_result()
    session = MagicMock()
    session.execute = AsyncMock(return_value=raw)

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    result = await repo.cypher_raw("MATCH (n) RETURN n")
    assert result is raw


@pytest.mark.asyncio
async def test_async_find_all_decodes_nodes() -> None:
    decoded = RepoPerson(id="p1", name="Alice")
    result = _multi_node_result([(["RepoPerson"], {"id": "p1", "name": "Alice"})])

    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_find_all_query.return_value = ("MATCH...", {})
    session.mapper.decode_node.return_value = decoded
    session.rel_loader = MagicMock()
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=result)

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    items = await repo.find_all()

    assert len(items) == 1
    session.register_or_get.assert_called_once_with(decoded)


@pytest.mark.asyncio
async def test_async_find_all_by_ids_empty() -> None:
    session = MagicMock()
    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    assert await repo.find_all_by_ids([]) == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_async_find_all_by_ids_calls_query() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_find_all_by_ids_query.return_value = ("MATCH...", {})
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_empty_result())

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    await repo.find_all_by_ids(["p1", "p2"])

    session.mapper.build_find_all_by_ids_query.assert_called_once_with(
        RepoPerson, ["p1", "p2"]
    )


@pytest.mark.asyncio
async def test_async_exists_false_on_zero() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.mapper.build_exists_query.return_value = ("EXISTS...", {})
    session.execute = AsyncMock(return_value=_scalar_result(0))

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    assert await repo.exists("nope") is False


@pytest.mark.asyncio
async def test_async_cypher_scalar() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_scalar_result(42))

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    result = await repo.cypher("RETURN 42", returns=int)
    assert result == [42]


@pytest.mark.asyncio
async def test_async_cypher_write_flag_forwarded() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_empty_result())

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    await repo.cypher("SET ...", write=True, returns=None)
    session.execute.assert_called_once_with("SET ...", {}, write=True)


@pytest.mark.asyncio
async def test_async_find_all_with_fetch_uses_rel_loader() -> None:
    session = MagicMock()
    session.mapper = MagicMock()
    session.rel_loader = MagicMock()
    session.rel_loader.build_find_all_with_fetch_query.return_value = (
        "FETCH_Q",
        {},
        [],
    )
    session.rel_loader.decode_eager_columns.return_value = []
    session.register_or_get.side_effect = lambda e: e
    session.execute = AsyncMock(return_value=_empty_result())

    repo: AsyncRepository[RepoPerson] = AsyncRepository(session, RepoPerson)
    await repo.find_all(fetch=["company"])

    session.rel_loader.build_find_all_with_fetch_query.assert_called_once_with(
        RepoPerson, ["company"]
    )
