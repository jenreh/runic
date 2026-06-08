"""Unit tests for MemgraphAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.memgraph import MemgraphAdapter
from runic.ogm.driver.bolt import BoltDriver
from runic.ogm.schema.index_manager import IndexSpec
from tests.runic.ogm.unit.mock_helpers import empty_result as _empty_result
from tests.runic.ogm.unit.mock_helpers import row_result as _row_result


def _make_adapter(database: str = "memgraph") -> tuple[MemgraphAdapter, MagicMock]:
    mock_driver = MagicMock(spec=BoltDriver)
    mock_driver.execute.return_value = _empty_result()
    adapter = MemgraphAdapter(mock_driver, database)
    return adapter, mock_driver


# ---------------------------------------------------------------------------
# Protocol + basic properties
# ---------------------------------------------------------------------------


class TestMemgraphAdapterProtocol:
    def test_satisfies_graph_adapter_protocol(self) -> None:
        from runic.migrate.adapters import GraphAdapter

        adapter, _ = _make_adapter()
        assert isinstance(adapter, GraphAdapter)

    def test_name(self) -> None:
        adapter, _ = _make_adapter("mydb")
        assert adapter.name == "mydb"


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------


class TestVersionTracking:
    def test_get_version_list(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _row_result([["rev1", "rev2"]])
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_get_version_string_split(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _row_result(["rev1,rev2"])
        assert adapter.get_version() == ["rev1", "rev2"]

    def test_get_version_empty(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _empty_result()
        assert adapter.get_version() == []

    def test_set_version_executes_query(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.set_version(["rev1"])
        mock_driver.execute.assert_called()


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------


class TestReadLiveSchema:
    def test_returns_empty_live_schema(self) -> None:
        adapter, _ = _make_adapter()
        schema = adapter.read_live_schema()
        assert schema.range_indexes == []
        assert schema.fulltext_indexes == []


class TestGetExistingSpecs:
    def test_empty_results_return_empty_set(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.get_existing_specs() == set()

    def test_label_property_index_returned_as_range(self) -> None:
        adapter, mock_driver = _make_adapter()
        index_row = ["label+property", "User", "email", 42]
        mock_driver.execute.side_effect = [
            _row_result(index_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="RANGE") in specs

    def test_label_only_index_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        index_row = ["label", "User", None, 5]
        mock_driver.execute.side_effect = [
            _row_result(index_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_unique_constraint_returned(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["unique", "User", ["id"]]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="id", index_type="UNIQUE") in specs

    def test_exists_constraint_returned_as_mandatory(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["exists", "Post", ["title"]]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert (
            IndexSpec(label="Post", property="title", index_type="MANDATORY") in specs
        )

    def test_unknown_constraint_type_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["other", "User", ["id"]]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_constraint_props_as_string_handled(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["unique", "User", "email"]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="UNIQUE") in specs

    def test_index_query_failure_returns_partial_results(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["unique", "User", ["id"]]
        mock_driver.execute.side_effect = [
            RuntimeError("show index info unavailable"),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="id", index_type="UNIQUE") in specs

    def test_constraint_query_failure_returns_partial_results(self) -> None:
        adapter, mock_driver = _make_adapter()
        index_row = ["label+property", "User", "email", 42]
        mock_driver.execute.side_effect = [
            _row_result(index_row),
            RuntimeError("show constraint info unavailable"),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="RANGE") in specs


# ---------------------------------------------------------------------------
# DDL — range index
# ---------------------------------------------------------------------------


class TestRangeIndex:
    def test_create_range_index_sends_correct_cypher(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_range_index("User", "email")
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE INDEX ON :User(email)" == cypher

    def test_drop_range_index_sends_correct_cypher(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_range_index("User", "email")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP INDEX ON :User(email)" == cypher

    def test_create_range_index_propagates_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            adapter.create_range_index("User", "email")


# ---------------------------------------------------------------------------
# DDL — fulltext / text index
# ---------------------------------------------------------------------------


class TestFulltextIndex:
    def test_create_fulltext_index_whole_label(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_fulltext_index("Post", "body")
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE TEXT INDEX Post ON :Post" == cypher

    def test_create_fulltext_index_multi_prop_still_creates_one_index(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_fulltext_index("Post", "title", "body")
        # Memgraph: one whole-label text index regardless of how many props
        assert mock_driver.execute.call_count == 1
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE TEXT INDEX Post ON :Post" == cypher

    def test_drop_fulltext_index(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_fulltext_index("Post")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP TEXT INDEX Post" == cypher

    def test_create_fulltext_propagates_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            adapter.create_fulltext_index("Post", "body")


# ---------------------------------------------------------------------------
# DDL — vector index
# ---------------------------------------------------------------------------


class TestVectorIndex:
    def test_create_vector_index_skips_when_dimension_zero(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_vector_index("Article", "embedding", 0, "cosine")
        mock_driver.execute.assert_not_called()

    def test_create_vector_index_sends_correct_cypher(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_vector_index(
            "Article", "embedding", 128, "cosine", m=8, ef_construction=100
        )
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE VECTOR INDEX Article_embedding ON :Article(embedding)" in cypher
        assert '"dimension": 128' in cypher
        assert '"metric": "cosine"' in cypher
        assert '"m": 8' in cypher
        assert '"ef_construction": 100' in cypher

    def test_drop_vector_index(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_vector_index("Article", "embedding")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP VECTOR INDEX Article_embedding" == cypher


# ---------------------------------------------------------------------------
# DDL — constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_create_unique_constraint(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_constraint("UNIQUE", "NODE", "User", ["id"])
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE CONSTRAINT ON (n:User) ASSERT n.id IS UNIQUE" == cypher

    def test_drop_unique_constraint(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_constraint("UNIQUE", "NODE", "User", ["id"])
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP CONSTRAINT ON (n:User) ASSERT n.id IS UNIQUE" == cypher

    def test_unsupported_constraint_does_not_execute(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_constraint("EXISTS", "NODE", "User", ["id"])
        mock_driver.execute.assert_not_called()

    def test_create_constraint_propagates_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            adapter.create_constraint("UNIQUE", "NODE", "User", ["id"])


# ---------------------------------------------------------------------------
# Graph lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_delete_graph(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.delete_graph()
        cypher = mock_driver.execute.call_args[0][0]
        assert "DETACH DELETE" in cypher

    def test_snapshot_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError):
            adapter.snapshot("snap1")

    def test_restore_snapshot_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError):
            adapter.restore_snapshot("snap1")

    def test_snapshot_exists_returns_false(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.snapshot_exists("snap1") is False

    def test_fork_returns_new_adapter(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.uri = "bolt://localhost:7687"
        mock_driver.auth = ("", "")
        forked = adapter.fork("other_db")
        assert isinstance(forked, MemgraphAdapter)
        assert forked.name == "other_db"


# ---------------------------------------------------------------------------
# Checksum tracking
# ---------------------------------------------------------------------------


class TestChecksumTracking:
    def test_get_checksums_parses_rows(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _row_result([["rev1:abc123"]])
        result = adapter.get_checksums()
        assert result == {"rev1": "abc123"}

    def test_get_checksums_empty(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _empty_result()
        assert adapter.get_checksums() == {}

    def test_get_installed_by_parses_second_column(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.return_value = _row_result([["rev1:hash"], ["rev1:alice"]])
        result = adapter.get_installed_by()
        assert result == {"rev1": "alice"}


# ---------------------------------------------------------------------------
# create_adapter factory
# ---------------------------------------------------------------------------


class TestCreateAdapterFactory:
    def test_create_adapter_memgraph_keyword(self) -> None:
        from unittest.mock import patch

        from runic.migrate.adapters import create_adapter

        with patch("runic.migrate.adapters.memgraph.BoltDriver.from_params") as mock_bp:
            mock_bp.return_value = MagicMock(spec=BoltDriver)
            adapter = create_adapter(
                "memgraph", database="mydb", password="secret", encrypted=False
            )
        assert isinstance(adapter, MemgraphAdapter)
        assert adapter.name == "mydb"
