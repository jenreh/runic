"""Unit tests for Neo4jAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters._base import _encode_kv_list, _parse_kv_list
from runic.migrate.adapters.neo4j import Neo4jAdapter
from runic.orm.driver.bolt import BoltDriver


def _empty_result() -> MagicMock:
    r = MagicMock()
    r.rows = []
    r.columns = []
    return r


def _row_result(*rows: list) -> MagicMock:
    r = MagicMock()
    r.rows = list(rows)
    return r


def _make_adapter(database: str = "neo4j") -> tuple[Neo4jAdapter, MagicMock]:
    mock_driver = MagicMock(spec=BoltDriver)
    mock_driver.execute.return_value = _empty_result()
    adapter = Neo4jAdapter(mock_driver, database)
    return adapter, mock_driver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestParseKvList:
    def test_basic(self) -> None:
        assert _parse_kv_list(["a:1", "b:2"]) == {"a": "1", "b": "2"}

    def test_empty_list(self) -> None:
        assert _parse_kv_list([]) == {}

    def test_none(self) -> None:
        assert _parse_kv_list(None) == {}

    def test_empty_item_skipped(self) -> None:
        assert _parse_kv_list(["", "x:9"]) == {"x": "9"}


class TestEncodeKvList:
    def test_basic(self) -> None:
        assert set(_encode_kv_list({"a": "1"})) == {"a:1"}

    def test_empty(self) -> None:
        assert _encode_kv_list({}) == []


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

    def test_get_existing_specs_empty(self) -> None:
        adapter, _ = _make_adapter()
        assert adapter.get_existing_specs() == set()


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

    def test_create_range_index_swallows_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("already exists")
        adapter.create_range_index("User", "email")  # must not raise


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

    def test_create_fulltext_swallows_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("fail")
        adapter.create_fulltext_index("Post", "body")  # must not raise


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

    def test_create_constraint_swallows_exception(self) -> None:
        adapter, mock_driver = _make_adapter()
        mock_driver.execute.side_effect = RuntimeError("fail")
        adapter.create_constraint("UNIQUE", "NODE", "User", ["id"])  # must not raise


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
