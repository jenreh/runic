from unittest.mock import MagicMock

import pytest

from runic.exceptions import MultipleHeadsError
from runic.version import VersionNode


@pytest.fixture
def mock_adapter() -> MagicMock:
    return MagicMock()


def test_get_returns_empty_list_on_fresh_node(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = []
    vn = VersionNode(mock_adapter)
    assert vn.get() == []


def test_set_multiple_stores_two_revisions(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["rev1", "rev2"]
    vn = VersionNode(mock_adapter)
    vn.set_multiple(["rev1", "rev2"])
    mock_adapter.set_version.assert_called_once_with(["rev1", "rev2"])
    assert vn.get() == ["rev1", "rev2"]


def test_get_single_raises_multiple_heads_error(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["rev1", "rev2"]
    vn = VersionNode(mock_adapter)
    with pytest.raises(MultipleHeadsError):
        vn.get_single()
