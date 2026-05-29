from unittest.mock import MagicMock

import pytest

from runic.version import VersionNode


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


def test_get_returns_none_when_empty(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = []
    vn = VersionNode(mock_graph)
    assert vn.get() is None


def test_get_returns_revision(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [["abc123def456"]]
    vn = VersionNode(mock_graph)
    assert vn.get() == "abc123def456"


def test_set_issues_parameterized_cypher(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.set("abc123def456")
    call_args = mock_graph.query.call_args
    query: str = call_args[0][0]
    params: dict = call_args[0][1]
    assert "MERGE" in query
    assert "_FalkorMigrateVersion" in query
    assert "singleton" in query
    assert params["rev"] == "abc123def456"


def test_clear_sets_revision_to_none(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.clear()
    call_args = mock_graph.query.call_args
    params: dict = call_args[0][1]
    assert params["rev"] is None
