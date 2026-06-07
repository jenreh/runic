"""Unit tests for AGEAdapter (Apache AGE migration adapter)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.age import AGEAdapter, _encode_kv_list, _parse_kv_list
from runic.orm.driver.age import AGEDriver, AGEResult


def _make_adapter(graph_name: str = "testgraph") -> tuple[AGEAdapter, MagicMock]:
    mock_driver = MagicMock(spec=AGEDriver)
    adapter = AGEAdapter(mock_driver, graph_name)
    return adapter, mock_driver


class TestParseKvList:
    def test_basic(self) -> None:
        assert _parse_kv_list(["abc:123", "def:456"]) == {"abc": "123", "def": "456"}

    def test_empty_list(self) -> None:
        assert _parse_kv_list([]) == {}

    def test_none(self) -> None:
        assert _parse_kv_list(None) == {}

    def test_empty_item_skipped(self) -> None:
        assert _parse_kv_list(["", "a:1"]) == {"a": "1"}


class TestEncodeKvList:
    def test_basic(self) -> None:
        result = _encode_kv_list({"a": "1", "b": "2"})
        assert set(result) == {"a:1", "b:2"}

    def test_empty(self) -> None:
        assert _encode_kv_list({}) == []


class TestAGEAdapterName:
    def test_name(self) -> None:
        adapter, _ = _make_adapter("mygraph")
        assert adapter.name == "mygraph"


class TestAGEAdapterRunQuery:
    def test_run_query_calls_driver_execute(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], ["n"])
        adapter.run_query("MATCH (n) RETURN n", {"x": 1})
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})

    def test_run_query_defaults_empty_params(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        adapter.run_query("MATCH (n) RETURN n")
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {})

    def test_run_ro_query_calls_driver_execute(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        adapter.run_ro_query("MATCH (n) RETURN n")
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {})


class TestAGEAdapterVersionTracking:
    def test_get_version_returns_list(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([[["rev1", "rev2"]]], ["v"])
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_get_version_string_split(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([["rev1,rev2"]], ["v"])
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_get_version_empty_rows(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        assert adapter.get_version() == []

    def test_get_version_none_value(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([[None]], ["v"])
        assert adapter.get_version() == []

    def test_set_version_calls_execute(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        adapter.set_version(["rev1"])
        mock_driver.execute.assert_called_once()


class TestAGEAdapterSchema:
    def test_read_live_schema_returns_empty(self) -> None:
        adapter, _ = _make_adapter()
        schema = adapter.read_live_schema()
        assert schema.range_indexes == []
        assert schema.fulltext_indexes == []
        assert schema.vector_indexes == []
        assert schema.constraints == []

    def test_create_range_index_logs_warning(self) -> None:
        adapter, _ = _make_adapter()
        adapter.create_range_index("Label", "prop")  # should not raise

    def test_drop_range_index_logs_warning(self) -> None:
        adapter, _ = _make_adapter()
        adapter.drop_range_index("Label", "prop")  # should not raise

    def test_create_fulltext_index_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.create_fulltext_index("Label", "field")  # logs warning, no raise

    def test_drop_fulltext_index_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.drop_fulltext_index("Label", "field")  # logs warning, no raise

    def test_create_vector_index_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.create_vector_index(
            "Label", "embedding", 1536, "cosine"
        )  # logs warning, no raise

    def test_drop_vector_index_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.drop_vector_index("Label", "embedding")  # logs warning, no raise

    def test_create_constraint_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.create_constraint(
            "UNIQUE", "NODE", "Label", ["id"]
        )  # logs warning, no raise

    def test_drop_constraint_warns(self) -> None:
        adapter, _ = _make_adapter()
        adapter.drop_constraint(
            "UNIQUE", "NODE", "Label", ["id"]
        )  # logs warning, no raise


class TestAGEAdapterSnapshotting:
    def test_snapshot_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError):
            adapter.snapshot("snap_name")

    def test_restore_snapshot_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError):
            adapter.restore_snapshot("snap_name")

    def test_snapshot_exists_returns_false(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.snapshot_exists("snap_name") is False


class TestAGEAdapterDeleteGraph:
    def test_delete_graph_runs_detach_delete(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        adapter.delete_graph()
        mock_driver.execute.assert_called_once()
        cypher = mock_driver.execute.call_args[0][0]
        assert "DELETE" in cypher.upper()


class TestAGEAdapterFork:
    def test_fork_returns_new_adapter(self) -> None:
        mock_conn = MagicMock()
        mock_driver = AGEDriver(mock_conn, "original")
        adapter = AGEAdapter(mock_driver, "original")
        forked = adapter.fork("forked_graph")
        assert isinstance(forked, AGEAdapter)
        assert forked.name == "forked_graph"

    def test_fork_reuses_connection(self) -> None:
        mock_conn = MagicMock()
        mock_driver = AGEDriver(mock_conn, "original")
        adapter = AGEAdapter(mock_driver, "original")
        forked = adapter.fork("forked_graph")
        assert forked._driver._conn is mock_conn  # noqa: SLF001


class TestAGEAdapterChecksums:
    def test_get_checksums_parses_kv_list(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult(
            [[["rev1:abc123"], ["rev1:user"]]], ["v"]
        )
        result = adapter.get_checksums()
        assert result == {"rev1": "abc123"}

    def test_get_checksums_empty(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = AGEResult([], [])
        assert adapter.get_checksums() == {}

    def test_set_checksum_stores_value(self) -> None:
        adapter, mock_driver = _make_adapter()
        # First two calls: get_checksums + get_installed_by
        mock_driver.execute.return_value = AGEResult([], [])
        adapter.set_checksum("rev1", "deadbeef", installed_by="ci")
        assert mock_driver.execute.call_count >= 1
