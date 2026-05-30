"""Tests for FalkorDB-specific adapter behaviour.

Covers constraint creation/polling and version tracking Cypher queries —
logic that lives exclusively in FalkorDBAdapter and cannot be expressed
through the generic GraphAdapter protocol.
"""

from unittest.mock import MagicMock, patch

import pytest

from runic.adapters.falkordb import FalkorDBAdapter
from runic.exceptions import ConstraintFailedError, ConstraintTimeoutError


@pytest.fixture
def mock_graph() -> MagicMock:
    graph = MagicMock()
    graph.name = "test_graph"
    return graph


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter(mock_graph: MagicMock, mock_db: MagicMock) -> FalkorDBAdapter:
    return FalkorDBAdapter(mock_db, mock_graph)


# ---------------------------------------------------------------------------
# Constraint creation and polling
# ---------------------------------------------------------------------------


def test_create_unique_constraint_also_creates_index(
    adapter: FalkorDBAdapter, mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    mock_db.execute_command.return_value = "PENDING"
    with patch.object(adapter, "_poll_constraint", return_value=None):
        adapter.create_constraint("UNIQUE", "NODE", "Person", ["email"])
    index_call = mock_graph.query.call_args_list[0][0][0]
    assert "CREATE INDEX" in index_call
    mock_db.execute_command.assert_called_once()
    constraint_args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in constraint_args
    assert "CREATE" in constraint_args
    assert "UNIQUE" in constraint_args


def test_polling_raises_on_failed_status(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    failed_row = ["type", "entity", "label", "props", "FAILED"]
    mock_graph.ro_query.return_value.result_set = [[failed_row]]
    with pytest.raises(ConstraintFailedError):
        adapter._poll_constraint("Person", ["email"])


def test_polling_raises_on_timeout(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    with (
        patch("runic.adapters.falkordb._POLL_RETRIES", 1),
        patch("runic.adapters.falkordb._POLL_INTERVAL", 0),
        pytest.raises(ConstraintTimeoutError),
    ):
        adapter._poll_constraint("Person", ["email"])


def test_drop_constraint_issues_redis_command(
    adapter: FalkorDBAdapter, mock_db: MagicMock
) -> None:
    adapter.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in args
    assert "DROP" in args


# ---------------------------------------------------------------------------
# Version tracking — FalkorDB Cypher specifics
# ---------------------------------------------------------------------------


def test_get_version_returns_empty_when_no_node(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    assert adapter.get_version() == []


def test_get_version_returns_list_property(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.ro_query.return_value.result_set = [[["aaa", "bbb"], None]]
    assert adapter.get_version() == ["aaa", "bbb"]


def test_get_version_backward_compat_string_node(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    """Phase-0 nodes have v.revisions=null and v.revision='oldrev'."""
    mock_graph.ro_query.return_value.result_set = [[None, "oldrev"]]
    assert adapter.get_version() == ["oldrev"]


def test_set_version_issues_merge_cypher(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version(["abc123def456"])
    call_args = mock_graph.query.call_args
    query: str = call_args[0][0]
    params: dict = call_args[0][1]
    assert "MERGE" in query
    assert "_FalkorMigrateVersion" in query
    assert "singleton" in query
    assert params["revisions"] == ["abc123def456"]


def test_set_version_stores_multiple_heads(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version(["aaa", "bbb"])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["aaa", "bbb"]


def test_set_version_empty_clears(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version([])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == []
