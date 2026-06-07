from unittest.mock import MagicMock

import pytest

from runic.migrate.exceptions import MultipleHeadsError
from runic.migrate.version import VersionNode


@pytest.fixture
def mock_adapter() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Single-head operations
# ---------------------------------------------------------------------------


def test_get_returns_empty_list_when_no_revisions(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = []
    vn = VersionNode(mock_adapter)
    assert vn.get() == []


def test_get_returns_single_revision(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["abc123def456"]
    vn = VersionNode(mock_adapter)
    assert vn.get() == ["abc123def456"]


def test_get_returns_multiple_revisions(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["aaa", "bbb"]
    vn = VersionNode(mock_adapter)
    assert vn.get() == ["aaa", "bbb"]


def test_get_single_returns_none_when_empty(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = []
    vn = VersionNode(mock_adapter)
    assert vn.get_single() is None


def test_get_single_returns_revision(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["abc123def456"]
    vn = VersionNode(mock_adapter)
    assert vn.get_single() == "abc123def456"


def test_get_single_raises_on_multiple(mock_adapter: MagicMock) -> None:
    mock_adapter.get_version.return_value = ["aaa", "bbb"]
    vn = VersionNode(mock_adapter)
    with pytest.raises(MultipleHeadsError):
        vn.get_single()


def test_set_calls_set_version_with_list(mock_adapter: MagicMock) -> None:
    vn = VersionNode(mock_adapter)
    vn.set("abc123def456")
    mock_adapter.set_version.assert_called_once_with(["abc123def456"])


def test_set_multiple_calls_set_version(mock_adapter: MagicMock) -> None:
    vn = VersionNode(mock_adapter)
    vn.set_multiple(["aaa", "bbb"])
    mock_adapter.set_version.assert_called_once_with(["aaa", "bbb"])


def test_clear_calls_set_version_with_empty(mock_adapter: MagicMock) -> None:
    vn = VersionNode(mock_adapter)
    vn.clear()
    mock_adapter.set_version.assert_called_once_with([])


# ---------------------------------------------------------------------------
# Multi-head behaviour
# ---------------------------------------------------------------------------


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
