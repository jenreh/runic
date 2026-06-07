"""Unit tests for ArcadeDBAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from runic.migrate.adapters.arcadedb import ArcadeDBAdapter
from runic.orm.driver.bolt import BoltDriver
from tests.runic.orm.unit.mock_helpers import empty_result as _empty_result
from tests.runic.orm.unit.mock_helpers import row_result as _row_result


def _make_adapter(database: str = "testdb") -> tuple[ArcadeDBAdapter, MagicMock]:
    mock_driver = MagicMock(spec=BoltDriver)
    mock_driver.execute.return_value = _empty_result()
    mock_driver.uri = "bolt://localhost:2424"
    mock_driver.auth = ("root", "pw")
    adapter = ArcadeDBAdapter(mock_driver, database)
    return adapter, mock_driver


# ---------------------------------------------------------------------------
# Protocol + basic properties
# ---------------------------------------------------------------------------


class TestArcadeDBAdapterProtocol:
    def test_satisfies_graph_adapter_protocol(self) -> None:
        from runic.migrate.adapters import GraphAdapter

        adapter, _ = _make_adapter()
        assert isinstance(adapter, GraphAdapter)

    def test_name(self) -> None:
        adapter, _ = _make_adapter("mydb")
        assert adapter.name == "mydb"

    def test_supports_multi_label_false(self) -> None:
        assert ArcadeDBAdapter.supports_multi_label is False


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------


class TestVersionTracking:
    def test_get_version_empty(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _empty_result()
        assert adapter.get_version() == []

    def test_get_version_list(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _row_result([["rev1", "rev2"]])
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_set_version_executes_query(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.set_version(["rev1"])
        mock_driver.execute.assert_called()


# ---------------------------------------------------------------------------
# Execute / run_query
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_delegates_to_driver(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.execute("MATCH (n) RETURN n", {})
        mock_driver.execute.assert_called_with("MATCH (n) RETURN n", {})

    def test_run_query_delegates(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.run_query("MATCH (n) RETURN n", {"x": 1})
        mock_driver.execute.assert_called_with("MATCH (n) RETURN n", {"x": 1})

    def test_run_ro_query_delegates(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.run_ro_query("MATCH (n) RETURN n")
        mock_driver.execute.assert_called_with("MATCH (n) RETURN n", {})


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


class TestDDL:
    def test_create_vertex_type_executes(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_vertex_type("Person")
        mock_driver.execute.assert_called()
        cypher = mock_driver.execute.call_args[0][0]
        assert "Person" in cypher

    def test_create_vertex_type_swallows_error(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = Exception("DDL error")
        adapter.create_vertex_type("Person")  # should not raise

    def test_create_edge_type_executes(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_edge_type("KNOWS")
        mock_driver.execute.assert_called()

    def test_create_range_index_executes(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_range_index("Person", "name")
        mock_driver.execute.assert_called()

    def test_drop_range_index_executes(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_range_index("Person", "name")
        mock_driver.execute.assert_called()

    def test_get_existing_specs_returns_empty(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.get_existing_specs() == set()


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------


class TestFork:
    def test_fork_returns_new_adapter(self) -> None:
        adapter, mock_driver = _make_adapter("db1")
        with MagicMock():
            import unittest.mock

            with unittest.mock.patch("neo4j.GraphDatabase.driver"):
                new_adapter = adapter.fork("db2")
        assert isinstance(new_adapter, ArcadeDBAdapter)
        assert new_adapter.name == "db2"
