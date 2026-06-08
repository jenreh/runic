"""Unit tests for Neo4jAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.neo4j import Neo4jAdapter
from runic.ogm.driver.bolt import BoltDriver
from runic.ogm.schema.index_manager import IndexSpec
from tests.runic.ogm.unit.mock_helpers import empty_result as _empty_result
from tests.runic.ogm.unit.mock_helpers import row_result as _row_result


def _make_adapter(database: str = "neo4j") -> tuple[Neo4jAdapter, MagicMock]:
    mock_driver = MagicMock(spec=BoltDriver)
    mock_driver.execute.return_value = _empty_result()
    adapter = Neo4jAdapter(mock_driver, database)
    return adapter, mock_driver


# ---------------------------------------------------------------------------
# Protocol + basic properties
# ---------------------------------------------------------------------------


class TestNeo4jAdapterProtocol:
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

    def test_range_index_online_node_returned(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["RANGE", "NODE", ["User"], ["email"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="RANGE") in specs

    def test_fulltext_index_returned(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["FULLTEXT", "NODE", ["Post"], ["body"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="Post", property="body", index_type="FULLTEXT") in specs

    def test_vector_index_returned(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["VECTOR", "NODE", ["Article"], ["embedding"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert (
            IndexSpec(label="Article", property="embedding", index_type="VECTOR")
            in specs
        )

    def test_offline_index_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["RANGE", "NODE", ["User"], ["email"], "POPULATING"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_lookup_index_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["LOOKUP", "NODE", ["User"], ["id"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_relationship_index_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["RANGE", "RELATIONSHIP", ["KNOWS"], ["since"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_uniqueness_constraint_returned(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["UNIQUENESS", "NODE", ["User"], ["id"]]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="id", index_type="UNIQUE") in specs

    def test_non_uniqueness_constraint_excluded(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["NODE_KEY", "NODE", ["User"], ["id"]]
        mock_driver.execute.side_effect = [
            _empty_result(),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert specs == set()

    def test_indexes_query_failure_returns_partial_results(self) -> None:
        adapter, mock_driver = _make_adapter()
        con_row = ["UNIQUENESS", "NODE", ["User"], ["id"]]
        mock_driver.execute.side_effect = [
            RuntimeError("show indexes unavailable"),
            _row_result(con_row),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="id", index_type="UNIQUE") in specs

    def test_constraints_query_failure_returns_partial_results(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["RANGE", "NODE", ["User"], ["email"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            RuntimeError("show constraints unavailable"),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="RANGE") in specs

    def test_multi_prop_index_produces_multiple_specs(self) -> None:
        adapter, mock_driver = _make_adapter()
        indexes_row = ["FULLTEXT", "NODE", ["Post"], ["title", "body"], "ONLINE"]
        mock_driver.execute.side_effect = [
            _row_result(indexes_row),
            _empty_result(),
        ]
        specs = adapter.get_existing_specs()
        assert IndexSpec(label="Post", property="title", index_type="FULLTEXT") in specs
        assert IndexSpec(label="Post", property="body", index_type="FULLTEXT") in specs


# ---------------------------------------------------------------------------
# DDL — range index
# ---------------------------------------------------------------------------


class TestRangeIndex:
    def test_create_range_index_sends_correct_cypher(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_range_index("User", "email")
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE INDEX" in cypher
        assert "User_email" in cypher
        assert "IF NOT EXISTS" in cypher
        assert "(n:User)" in cypher
        assert "n.email" in cypher

    def test_create_range_index_rel(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_range_index("KNOWS", "weight", rel=True)
        cypher = mock_driver.execute.call_args[0][0]
        assert "()-[n:KNOWS]->()" in cypher

    def test_drop_range_index_sends_correct_cypher(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_range_index("User", "email")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP INDEX User_email IF EXISTS" in cypher

    def test_create_range_index_propagates_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("already exists")
        with pytest.raises(RuntimeError, match="already exists"):
            adapter.create_range_index("User", "email")


# ---------------------------------------------------------------------------
# DDL — fulltext index
# ---------------------------------------------------------------------------


class TestFulltextIndex:
    def test_create_fulltext_index_single_prop(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_fulltext_index("Post", "body")
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE FULLTEXT INDEX Post IF NOT EXISTS" in cypher
        assert "(n:Post)" in cypher
        assert "n.body" in cypher

    def test_create_fulltext_index_multi_prop(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_fulltext_index("Post", "title", "body")
        cypher = mock_driver.execute.call_args[0][0]
        assert "n.title" in cypher
        assert "n.body" in cypher
        assert "ON EACH [" in cypher

    def test_drop_fulltext_index(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_fulltext_index("Post")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP INDEX Post IF EXISTS" in cypher

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
        adapter.create_vector_index("Article", "embedding", 128, "cosine")
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE VECTOR INDEX Article_embedding" in cypher
        assert "IF NOT EXISTS" in cypher
        assert "(n:Article)" in cypher
        assert "128" in cypher
        assert "cosine" in cypher

    def test_drop_vector_index(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_vector_index("Article", "embedding")
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP INDEX Article_embedding IF EXISTS" in cypher


# ---------------------------------------------------------------------------
# DDL — constraints
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_create_unique_constraint(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.create_constraint("UNIQUE", "NODE", "User", ["id"])
        cypher = mock_driver.execute.call_args[0][0]
        assert "CREATE CONSTRAINT" in cypher
        assert "User_id_unique" in cypher
        assert "IF NOT EXISTS" in cypher
        assert "(n:User)" in cypher
        assert "n.id IS UNIQUE" in cypher

    def test_drop_unique_constraint(self) -> None:
        adapter, mock_driver = _make_adapter()
        adapter.drop_constraint("UNIQUE", "NODE", "User", ["id"])
        cypher = mock_driver.execute.call_args[0][0]
        assert "DROP CONSTRAINT User_id_unique IF EXISTS" in cypher

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

    def test_supports_snapshots_false(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.supports_snapshots() is False

    def test_introspect_schema_raises(self) -> None:
        adapter, _ = _make_adapter()
        with pytest.raises(NotImplementedError):
            adapter.introspect_schema()

    def test_snapshot_exists_returns_false(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.snapshot_exists("snap1") is False

    def test_fork_returns_new_adapter(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.uri = "bolt://localhost:7687"
        mock_driver.auth = ("neo4j", "pass")
        forked = adapter.fork("other_db")
        assert isinstance(forked, Neo4jAdapter)
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
    def test_create_adapter_neo4j_keyword(self) -> None:
        from unittest.mock import patch

        from runic.migrate.adapters import create_adapter

        with patch("runic.migrate.adapters.neo4j.BoltDriver.from_params") as mock_bp:
            mock_bp.return_value = MagicMock(spec=BoltDriver)
            adapter = create_adapter(
                "neo4j", database="testdb", password="secret", encrypted=False
            )
        assert isinstance(adapter, Neo4jAdapter)
        assert adapter.name == "testdb"
