from unittest.mock import MagicMock, patch

import pytest

from runic.operations import (
    ConstraintFailedError,
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
        ops._poll_constraint("UNIQUE", "NODE", "Person", ["email"])


def test_drop_constraint(ops: GraphOperations, mock_db: MagicMock) -> None:
    ops.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in args
    assert "DROP" in args
