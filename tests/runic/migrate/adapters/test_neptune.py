"""Unit tests for NeptuneAdapter (Amazon Neptune migration adapter)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runic.migrate.adapters import GraphAdapter, create_adapter
from runic.migrate.adapters.neptune import NeptuneAdapter
from runic.ogm.driver.neptune_analytics import (
    NeptuneAnalyticsDriver,
    NeptuneAnalyticsResult,
)


def _make_adapter(graph_name: str = "neptune") -> tuple[NeptuneAdapter, MagicMock]:
    mock_driver = MagicMock(spec=NeptuneAnalyticsDriver)
    adapter = NeptuneAdapter(mock_driver, graph_name)
    return adapter, mock_driver


class TestNeptuneAdapterProtocol:
    def test_satisfies_graph_adapter(self) -> None:
        adapter, _ = _make_adapter()
        assert isinstance(adapter, GraphAdapter)


class TestNeptuneAdapterName:
    def test_name(self) -> None:
        adapter, _ = _make_adapter("mygraph")
        assert adapter.name == "mygraph"


class TestNeptuneAdapterQueries:
    def test_execute_delegates(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.execute("MATCH (n) RETURN n", {"x": 1})
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})

    def test_run_query_defaults_empty_params(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.run_query("MATCH (n) RETURN n")
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {})

    def test_run_ro_query_delegates(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.run_ro_query("MATCH (n) RETURN n")
        mock_driver.execute.assert_called_once_with("MATCH (n) RETURN n", {})


class TestNeptuneAdapterVersionTracking:
    def test_get_version_returns_list(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = NeptuneAnalyticsResult(
            [[["rev1", "rev2"]]], ["v"]
        )
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_get_version_empty(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = NeptuneAnalyticsResult([], [])
        assert adapter.get_version() == []

    def test_set_version_calls_execute(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.set_version(["rev1"])
        mock_driver.execute.assert_called_once()


class TestNeptuneAdapterSchema:
    def test_read_live_schema_returns_empty(self) -> None:
        adapter, _ = _make_adapter()
        schema = adapter.read_live_schema()
        assert schema.range_indexes == []
        assert schema.constraints == []

    def test_introspect_schema_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError, match="Neptune"):
            adapter.introspect_schema()

    def test_get_existing_specs_empty(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.get_existing_specs() == set()

    def test_ddl_methods_warn_and_do_not_execute(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        adapter, mock_driver = _make_adapter()
        with caplog.at_level("WARNING"):
            adapter.create_range_index("Label", "prop")
            adapter.drop_range_index("Label", "prop")
            adapter.create_fulltext_index("Label", "field")
            adapter.drop_fulltext_index("Label", "field")
            adapter.create_vector_index("Label", "embedding", 1536, "cosine")
            adapter.drop_vector_index("Label", "embedding")
            adapter.create_constraint("UNIQUE", "NODE", "Label", ["id"])
            adapter.drop_constraint("UNIQUE", "NODE", "Label", ["id"])
        assert mock_driver.execute.call_count == 0
        assert len(caplog.records) == 8

    def test_entity_type_creation_is_noop(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_vertex_type("Label")
        adapter.create_edge_type("REL")
        assert mock_driver.execute.call_count == 0


class TestNeptuneAdapterSnapshotting:
    def test_snapshots_unsupported(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.supports_snapshots() is False
        assert adapter.snapshot_exists("snap") is False
        with pytest.raises(NotImplementedError):
            adapter.snapshot("snap")
        with pytest.raises(NotImplementedError):
            adapter.restore_snapshot("snap")


class TestNeptuneAdapterDeleteGraph:
    def test_delete_graph_runs_detach_delete(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.delete_graph()
        cypher = mock_driver.execute.call_args[0][0]
        assert "DETACH DELETE" in cypher


class TestNeptuneAdapterFork:
    def test_fork_shares_driver(self) -> None:
        adapter, mock_driver = _make_adapter("original")
        forked = adapter.fork("other")
        assert isinstance(forked, NeptuneAdapter)
        assert forked.name == "other"
        assert forked._driver is mock_driver  # noqa: SLF001


class TestNeptuneAdapterFactories:
    def test_from_analytics_params(self) -> None:
        with patch("boto3.client") as mock_client:
            adapter = NeptuneAdapter.from_analytics_params(
                "g-123", region="eu-central-1"
            )
        assert adapter.name == "g-123"
        mock_client.assert_called_once_with("neptune-graph", region_name="eu-central-1")

    def test_from_bolt_params_without_iam(self) -> None:
        with patch("neo4j.GraphDatabase.driver"):
            adapter = NeptuneAdapter.from_bolt_params(
                "cluster.example.neptune.amazonaws.com",
                use_iam_auth=False,
                graph_name="prod",
            )
        assert adapter.name == "prod"

    def test_create_adapter_dispatch_neptune(self) -> None:
        with patch("neo4j.GraphDatabase.driver"):
            adapter = create_adapter(
                "neptune",
                endpoint="cluster.example.neptune.amazonaws.com",
                use_iam_auth=False,
            )
        assert isinstance(adapter, NeptuneAdapter)

    def test_create_adapter_dispatch_neptune_analytics(self) -> None:
        with patch("boto3.client"):
            adapter = create_adapter("neptune_analytics", graph_id="g-123")
        assert isinstance(adapter, NeptuneAdapter)
        assert adapter.name == "g-123"
