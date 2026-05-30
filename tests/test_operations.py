from unittest.mock import MagicMock, patch

import pytest

from runic.operations import (
    ConstraintFailedError,
    ConstraintTimeoutError,
    GraphOperations,
)


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ops(mock_graph: MagicMock, mock_db: MagicMock) -> GraphOperations:
    return GraphOperations(mock_graph, mock_db)


@pytest.fixture
def preview_ops(mock_graph: MagicMock, mock_db: MagicMock) -> GraphOperations:
    return GraphOperations(mock_graph, mock_db, preview=True)


def test_preview_run_cypher_no_calls(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.run_cypher("MATCH (n) RETURN n")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_preview_run_command_no_calls(
    preview_ops: GraphOperations, mock_db: MagicMock
) -> None:
    preview_ops.run_command("GRAPH.CONSTRAINT", "CREATE")
    mock_db.execute_command.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_run_cypher_calls_graph(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.run_cypher("MATCH (n) RETURN n", {"x": 1})
    mock_graph.query.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})


def test_create_range_index_node(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.create_range_index("Person", "email")
    call_args = mock_graph.query.call_args[0][0]
    assert "CREATE INDEX" in call_args
    assert "Person" in call_args
    assert "email" in call_args


def test_create_range_index_rel(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.create_range_index("FOLLOWS", "since", rel=True)
    call_args = mock_graph.query.call_args[0][0]
    assert "CREATE INDEX" in call_args
    assert "FOLLOWS" in call_args


def test_drop_range_index_node(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.drop_range_index("Person", "email")
    call_args = mock_graph.query.call_args[0][0]
    assert "DROP INDEX" in call_args
    assert "Person" in call_args


def test_create_unique_constraint_also_creates_index(
    ops: GraphOperations, mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    mock_db.execute_command.return_value = "PENDING"
    with patch.object(ops, "_poll_constraint", return_value=None):
        ops.create_constraint("UNIQUE", "NODE", "Person", ["email"])
    index_call = mock_graph.query.call_args_list[0][0][0]
    assert "CREATE INDEX" in index_call
    mock_db.execute_command.assert_called_once()
    constraint_args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in constraint_args
    assert "CREATE" in constraint_args
    assert "UNIQUE" in constraint_args


def test_polling_raises_on_failed_status(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    failed_row = ["type", "entity", "label", "props", "FAILED"]
    mock_graph.ro_query.return_value.result_set = [[failed_row]]
    with pytest.raises(ConstraintFailedError):
        ops._poll_constraint("Person", ["email"])


def test_drop_constraint(ops: GraphOperations, mock_db: MagicMock) -> None:
    ops.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in args
    assert "DROP" in args


def test_preview_drop_constraint_no_calls(
    preview_ops: GraphOperations, mock_db: MagicMock
) -> None:
    preview_ops.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    mock_db.execute_command.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_polling_raises_on_timeout(mock_graph: MagicMock, mock_db: MagicMock) -> None:
    ops = GraphOperations(mock_graph, mock_db)
    mock_graph.ro_query.return_value.result_set = []
    with (
        patch("runic.operations._POLL_RETRIES", 1),
        patch("runic.operations._POLL_INTERVAL", 0),
        pytest.raises(ConstraintTimeoutError),
    ):
        ops._poll_constraint("Person", ["email"])


def test_run_cypher_no_params(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.run_cypher("MATCH (n) RETURN n")
    mock_graph.query.assert_called_once_with("MATCH (n) RETURN n")


def test_preview_create_range_index_rel(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.create_range_index("FOLLOWS", "since", rel=True)
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_preview_drop_range_index(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.drop_range_index("Person", "email")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_preview_create_constraint(
    preview_ops: GraphOperations, mock_db: MagicMock
) -> None:
    preview_ops.create_constraint("MANDATORY", "NODE", "Person", ["name"])
    mock_db.execute_command.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# Phase 2 — fulltext index
# ---------------------------------------------------------------------------


def test_create_fulltext_index_simple(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    ops.create_fulltext_index("Movie", "title")
    query = mock_graph.query.call_args[0][0]
    assert "db.idx.fulltext.createNodeIndex" in query
    assert "'Movie'" in query
    assert "'title'" in query


def test_create_fulltext_index_with_language(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    ops.create_fulltext_index("Movie", "title", language="german")
    query = mock_graph.query.call_args[0][0]
    assert "language" in query
    assert "german" in query


def test_create_fulltext_index_with_stopwords(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    ops.create_fulltext_index("Movie", "title", stopwords=["le", "la"])
    query = mock_graph.query.call_args[0][0]
    assert "stopwords" in query
    assert "le" in query


def test_create_fulltext_index_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.create_fulltext_index("Movie", "title")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_drop_fulltext_index(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.drop_fulltext_index("Movie", "title")
    query = mock_graph.query.call_args[0][0]
    assert "DROP FULLTEXT INDEX" in query
    assert "Movie" in query
    assert "title" in query


def test_drop_fulltext_index_multiple_props(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    ops.drop_fulltext_index("Movie", "title", "synopsis")
    assert mock_graph.query.call_count == 2


def test_drop_fulltext_index_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.drop_fulltext_index("Movie", "title", "synopsis")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# Phase 2 — vector index
# ---------------------------------------------------------------------------


def test_create_vector_index(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.create_vector_index("Product", "embedding", 128, "cosine")
    query = mock_graph.query.call_args[0][0]
    assert "CREATE VECTOR INDEX" in query
    assert "Product" in query
    assert "embedding" in query
    assert "128" in query
    assert "cosine" in query


def test_create_vector_index_options(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    ops.create_vector_index("Product", "emb", 64, "euclidean", m=8, ef_construction=100)
    query = mock_graph.query.call_args[0][0]
    assert "8" in query
    assert "100" in query


def test_create_vector_index_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.create_vector_index("Product", "emb", 64, "cosine")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_drop_vector_index(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.drop_vector_index("Product", "embedding")
    query = mock_graph.query.call_args[0][0]
    assert "DROP VECTOR INDEX" in query
    assert "Product" in query
    assert "embedding" in query


def test_drop_vector_index_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.drop_vector_index("Product", "embedding")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# Phase 2 — rename_property
# ---------------------------------------------------------------------------


def test_rename_property_terminates_on_zero(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = [[0]]
    ops.rename_property("Person", "fname", "first_name")
    assert mock_graph.query.call_count == 1
    query = mock_graph.query.call_args[0][0]
    assert "fname" in query
    assert "first_name" in query


def test_rename_property_loops_until_done(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    mock_graph.query.side_effect = [
        MagicMock(result_set=[[500]]),
        MagicMock(result_set=[[500]]),
        MagicMock(result_set=[[0]]),
    ]
    ops.rename_property("Person", "fname", "first_name", batch=500)
    assert mock_graph.query.call_count == 3


def test_rename_property_passes_batch_param(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = [[0]]
    ops.rename_property("Person", "fname", "first_name", batch=999)
    _, kwargs = mock_graph.query.call_args
    params = mock_graph.query.call_args[0][1]
    assert params["batch"] == 999


def test_rename_property_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.rename_property("Person", "fname", "first_name")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# Phase 2 — relabel_nodes
# ---------------------------------------------------------------------------


def test_relabel_nodes_terminates_on_zero(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    mock_graph.query.return_value.result_set = [[0]]
    ops.relabel_nodes("OldLabel", "NewLabel")
    assert mock_graph.query.call_count == 1
    query = mock_graph.query.call_args[0][0]
    assert "OldLabel" in query
    assert "NewLabel" in query


def test_relabel_nodes_loops_until_done(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    mock_graph.query.side_effect = [
        MagicMock(result_set=[[200]]),
        MagicMock(result_set=[[0]]),
    ]
    ops.relabel_nodes("OldLabel", "NewLabel")
    assert mock_graph.query.call_count == 2


def test_relabel_nodes_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.relabel_nodes("OldLabel", "NewLabel")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# Phase 2 — seed
# ---------------------------------------------------------------------------


def test_seed_calls_unwind_merge(ops: GraphOperations, mock_graph: MagicMock) -> None:
    rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    ops.seed("MERGE (n:Person {id: row.id}) SET n.name = row.name", rows)
    query, params = mock_graph.query.call_args[0]
    assert "UNWIND" in query
    assert "rows" in query
    assert params["rows"] == rows


def test_seed_preview(preview_ops: GraphOperations, mock_graph: MagicMock) -> None:
    preview_ops.seed("MERGE (n:Tag {id: row.id})", [{"id": 1}])
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1
