from unittest.mock import MagicMock

import pytest

from runic.exceptions import MultipleHeadsError
from runic.version import VersionNode


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


def test_get_returns_empty_list_on_fresh_node(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = []
    vn = VersionNode(mock_graph)
    assert vn.get() == []


def test_set_multiple_stores_and_retrieves_two_revisions(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [[["rev1", "rev2"], None]]
    vn = VersionNode(mock_graph)
    # set_multiple is the write path
    vn.set_multiple(["rev1", "rev2"])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["rev1", "rev2"]
    # get() returns the two-element list from the mock
    assert vn.get() == ["rev1", "rev2"]


def test_get_single_raises_multiple_heads_error(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [[["rev1", "rev2"], None]]
    vn = VersionNode(mock_graph)
    with pytest.raises(MultipleHeadsError):
        vn.get_single()


def test_backward_compat_old_string_node(mock_graph: MagicMock) -> None:
    """A Phase-0 node has v.revisions=null and v.revision="oldrev"."""
    mock_graph.ro_query.return_value.result_set = [[None, "oldrev"]]
    vn = VersionNode(mock_graph)
    assert vn.get() == ["oldrev"]
    assert vn.get_single() == "oldrev"
