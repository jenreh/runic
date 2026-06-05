from unittest.mock import MagicMock

import pytest

from runic.migrate.adapters.falkordb import FalkorDBAdapter
from runic.migrate.operations import GraphOperations


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


@pytest.fixture
def ops(adapter: FalkorDBAdapter) -> GraphOperations:
    return GraphOperations(adapter)


@pytest.fixture
def preview_ops(adapter: FalkorDBAdapter) -> GraphOperations:
    return GraphOperations(adapter, preview=True)


def test_preview_run_cypher_no_calls(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.run_cypher("MATCH (n) RETURN n")
    mock_graph.query.assert_not_called()
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
# fulltext index
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
# vector index
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
# rename_property
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
    params = mock_graph.query.call_args[0][1]
    assert params["batch"] == 999


def test_rename_property_preview(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.rename_property("Person", "fname", "first_name")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


# ---------------------------------------------------------------------------
# relabel_nodes
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
# seed
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
