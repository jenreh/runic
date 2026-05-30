from unittest.mock import MagicMock

import pytest

from runic.exceptions import MultipleHeadsError
from runic.version import VersionNode


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


def test_get_returns_empty_list_when_no_node(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = []
    vn = VersionNode(mock_graph)
    assert vn.get() == []


def test_get_returns_single_revision_list(mock_graph: MagicMock) -> None:
    # Single-column mock (Phase-0 style) — backward compat path.
    mock_graph.ro_query.return_value.result_set = [["abc123def456"]]
    vn = VersionNode(mock_graph)
    assert vn.get() == ["abc123def456"]


def test_get_returns_list_property(mock_graph: MagicMock) -> None:
    # Two-column result: col0 is the new list property.
    mock_graph.ro_query.return_value.result_set = [[["aaa", "bbb"], None]]
    vn = VersionNode(mock_graph)
    assert vn.get() == ["aaa", "bbb"]


def test_get_single_returns_none_when_empty(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = []
    vn = VersionNode(mock_graph)
    assert vn.get_single() is None


def test_get_single_returns_revision(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [["abc123def456"]]
    vn = VersionNode(mock_graph)
    assert vn.get_single() == "abc123def456"


def test_get_single_raises_on_multiple(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [[["aaa", "bbb"], None]]
    vn = VersionNode(mock_graph)
    with pytest.raises(MultipleHeadsError):
        vn.get_single()


def test_set_issues_parameterized_cypher(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.set("abc123def456")
    call_args = mock_graph.query.call_args
    query: str = call_args[0][0]
    params: dict = call_args[0][1]
    assert "MERGE" in query
    assert "_FalkorMigrateVersion" in query
    assert "singleton" in query
    assert params["revisions"] == ["abc123def456"]


def test_set_multiple_stores_list(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.set_multiple(["aaa", "bbb"])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["aaa", "bbb"]


def test_clear_sets_empty_list(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.clear()
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == []
