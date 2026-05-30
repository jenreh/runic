from unittest.mock import MagicMock, patch

import pytest

from runic.operations import (
    ConstraintFailedError,
    ConstraintTimeoutError,
    GraphOperations,
    _bind_op,
    op,
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


def test_polling_raises_on_timeout(
    mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    ops = GraphOperations(mock_graph, mock_db)
    mock_graph.ro_query.return_value.result_set = []
    with patch("runic.operations._POLL_RETRIES", 1), patch(
        "runic.operations._POLL_INTERVAL", 0
    ), pytest.raises(ConstraintTimeoutError):
        ops._poll_constraint("Person", ["email"])


def test_run_cypher_no_params(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.run_cypher("MATCH (n) RETURN n")
    mock_graph.query.assert_called_once_with("MATCH (n) RETURN n")


def test_op_proxy_raises_when_unbound() -> None:
    import runic.operations as ops_module

    ops_module._op = None
    with pytest.raises(RuntimeError, match="not bound"):
        _ = op.run_cypher


def test_op_proxy_delegates_when_bound(
    mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    bound = GraphOperations(mock_graph, mock_db)
    _bind_op(bound)
    assert op.preview_log == []


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
