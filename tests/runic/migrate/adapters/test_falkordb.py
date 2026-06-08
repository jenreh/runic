"""Tests for FalkorDB-specific adapter behaviour.

Covers constraint creation/polling and version tracking Cypher queries —
logic that lives exclusively in FalkorDBAdapter and cannot be expressed
through the generic GraphAdapter protocol.
"""

from unittest.mock import MagicMock, patch

import pytest

from runic.migrate.adapters.falkordb import FalkorDBAdapter
from runic.migrate.exceptions import ConstraintFailedError, ConstraintTimeoutError
from runic.migrate.introspect import LiveSchema
from runic.migrate.manifest import MandatoryConstraint, RangeIndex, UniqueConstraint
from runic.ogm.schema.index_manager import IndexSpec


@pytest.fixture
def mock_graph() -> MagicMock:
    graph = MagicMock()
    graph.name = "test_graph"
    return graph


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter(mock_graph: MagicMock, mock_db: MagicMock) -> FalkorDBAdapter:
    return FalkorDBAdapter(mock_db, mock_graph)


# ---------------------------------------------------------------------------
# Constraint creation and polling
# ---------------------------------------------------------------------------


def test_create_unique_constraint_also_creates_index(
    adapter: FalkorDBAdapter, mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    mock_db.execute_command.return_value = "PENDING"
    with patch.object(adapter, "_poll_constraint", return_value=None):
        adapter.create_constraint("UNIQUE", "NODE", "Person", ["email"])
    index_call = mock_graph.query.call_args_list[0][0][0]
    assert "CREATE INDEX" in index_call
    mock_db.execute_command.assert_called_once()
    constraint_args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in constraint_args
    assert "CREATE" in constraint_args
    assert "UNIQUE" in constraint_args


def test_polling_raises_on_failed_status(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    failed_row = ["type", "entity", "label", "props", "FAILED"]
    mock_graph.query.return_value.result_set = [[failed_row]]
    with pytest.raises(ConstraintFailedError):
        adapter._poll_constraint("Person", ["email"])


def test_polling_raises_on_timeout(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = []
    with (
        patch("runic.migrate.adapters.falkordb._POLL_RETRIES", 1),
        patch("runic.migrate.adapters.falkordb._POLL_INTERVAL", 0),
        pytest.raises(ConstraintTimeoutError),
    ):
        adapter._poll_constraint("Person", ["email"])


def test_drop_constraint_issues_redis_command(
    adapter: FalkorDBAdapter, mock_db: MagicMock
) -> None:
    adapter.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in args
    assert "DROP" in args


# ---------------------------------------------------------------------------
# Version tracking — FalkorDB Cypher specifics
# ---------------------------------------------------------------------------


def test_get_version_returns_empty_when_no_node(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = []
    assert adapter.get_version() == []


def test_get_version_returns_list_property(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = [[["aaa", "bbb"], None]]
    assert adapter.get_version() == ["aaa", "bbb"]


def test_get_version_backward_compat_string_node(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    """Phase-0 nodes have v.revisions=null and v.revision='oldrev'."""
    mock_graph.query.return_value.result_set = [[None, "oldrev"]]
    assert adapter.get_version() == ["oldrev"]


def test_set_version_issues_merge_cypher(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version(["abc123def456"])
    call_args = mock_graph.query.call_args
    query: str = call_args[0][0]
    params: dict = call_args[0][1]
    assert "MERGE" in query
    assert "_FalkorMigrateVersion" in query
    assert "singleton" in query
    assert params["revisions"] == ["abc123def456"]


def test_set_version_stores_multiple_heads(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version(["aaa", "bbb"])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == ["aaa", "bbb"]


def test_set_version_empty_clears(
    adapter: FalkorDBAdapter, mock_graph: MagicMock
) -> None:
    adapter.set_version([])
    params: dict = mock_graph.query.call_args[0][1]
    assert params["revisions"] == []


# ---------------------------------------------------------------------------
# get_existing_specs
# ---------------------------------------------------------------------------


def _make_live_schema(
    range_indexes: list | None = None,
    fulltext_indexes: list | None = None,
    vector_indexes: list | None = None,
    constraints: list | None = None,
) -> LiveSchema:

    return LiveSchema(
        range_indexes=range_indexes or [],
        fulltext_indexes=fulltext_indexes or [],
        vector_indexes=vector_indexes or [],
        constraints=constraints or [],
    )


class TestGetExistingSpecs:
    def test_empty_schema_returns_empty_set(self, adapter: FalkorDBAdapter) -> None:
        with patch.object(
            adapter, "read_live_schema", return_value=_make_live_schema()
        ):
            assert adapter.get_existing_specs() == set()

    def test_range_index_returned(self, adapter: FalkorDBAdapter) -> None:
        schema = _make_live_schema(
            range_indexes=[RangeIndex(label="User", prop="email")]
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="email", index_type="RANGE") in specs

    def test_unique_constraint_returned(self, adapter: FalkorDBAdapter) -> None:
        schema = _make_live_schema(
            constraints=[UniqueConstraint(entity="NODE", label="User", props=["id"])]
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="id", index_type="UNIQUE") in specs

    def test_mandatory_constraint_returned(self, adapter: FalkorDBAdapter) -> None:
        schema = _make_live_schema(
            constraints=[
                MandatoryConstraint(entity="NODE", label="Post", props=["title"])
            ]
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert (
            IndexSpec(label="Post", property="title", index_type="MANDATORY") in specs
        )

    def test_backing_range_index_for_unique_excluded(
        self, adapter: FalkorDBAdapter
    ) -> None:
        schema = _make_live_schema(
            range_indexes=[RangeIndex(label="User", prop="email")],
            constraints=[
                UniqueConstraint(entity="NODE", label="User", props=["email"])
            ],
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert (
            IndexSpec(label="User", property="email", index_type="RANGE") not in specs
        )
        assert IndexSpec(label="User", property="email", index_type="UNIQUE") in specs

    def test_non_backing_range_index_kept(self, adapter: FalkorDBAdapter) -> None:
        schema = _make_live_schema(
            range_indexes=[
                RangeIndex(label="User", prop="email"),
                RangeIndex(label="User", prop="name"),
            ],
            constraints=[
                UniqueConstraint(entity="NODE", label="User", props=["email"])
            ],
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert IndexSpec(label="User", property="name", index_type="RANGE") in specs
        assert (
            IndexSpec(label="User", property="email", index_type="RANGE") not in specs
        )

    def test_fulltext_index_each_prop_is_a_spec(self, adapter: FalkorDBAdapter) -> None:
        from runic.migrate.manifest import FulltextIndex

        schema = _make_live_schema(
            fulltext_indexes=[FulltextIndex(label="Post", props=["title", "body"])]
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert IndexSpec(label="Post", property="title", index_type="FULLTEXT") in specs
        assert IndexSpec(label="Post", property="body", index_type="FULLTEXT") in specs

    def test_vector_index_returned(self, adapter: FalkorDBAdapter) -> None:
        from runic.migrate.manifest import VectorIndex

        schema = _make_live_schema(
            vector_indexes=[
                VectorIndex(
                    label="Article",
                    prop="embedding",
                    dimension=128,
                    similarity="cosine",
                )
            ]
        )
        with patch.object(adapter, "read_live_schema", return_value=schema):
            specs = adapter.get_existing_specs()
        assert (
            IndexSpec(label="Article", property="embedding", index_type="VECTOR")
            in specs
        )
