"""Unit tests for runic.orm.operations.DataOperations."""

from unittest.mock import MagicMock

import pytest

from runic.orm.operations import DataOperations


def _make_executor(rows: list | None = None) -> MagicMock:
    """Return a mock _Executor whose execute() returns a result with .rows."""
    executor = MagicMock()
    result = MagicMock()
    result.rows = rows if rows is not None else []
    executor.execute.return_value = result
    return executor


# ---------------------------------------------------------------------------
# Preview mode
# ---------------------------------------------------------------------------


def test_preview_run_cypher_no_execute() -> None:
    executor = _make_executor()
    ops = DataOperations(executor, preview=True)
    ops.run_cypher("MATCH (n) RETURN n")
    executor.execute.assert_not_called()
    assert len(ops.preview_log) == 1


def test_preview_rename_property_no_execute() -> None:
    executor = _make_executor()
    ops = DataOperations(executor, preview=True)
    ops.rename_property("Person", "fname", "first_name")
    executor.execute.assert_not_called()
    assert len(ops.preview_log) == 1


def test_preview_relabel_nodes_no_execute() -> None:
    executor = _make_executor()
    ops = DataOperations(executor, preview=True)
    ops.relabel_nodes("OldLabel", "NewLabel")
    executor.execute.assert_not_called()
    assert len(ops.preview_log) == 1


def test_preview_seed_no_execute() -> None:
    executor = _make_executor()
    ops = DataOperations(executor, preview=True)
    ops.seed("MERGE (n:Tag {id: row.id})", [{"id": 1}])
    executor.execute.assert_not_called()
    assert len(ops.preview_log) == 1


# ---------------------------------------------------------------------------
# run_cypher
# ---------------------------------------------------------------------------


def test_run_cypher_with_params() -> None:
    executor = _make_executor()
    ops = DataOperations(executor)
    ops.run_cypher("MATCH (n) RETURN n", {"x": 1})
    executor.execute.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})


def test_run_cypher_no_params_defaults_to_empty_dict() -> None:
    executor = _make_executor()
    ops = DataOperations(executor)
    ops.run_cypher("MATCH (n) RETURN n")
    executor.execute.assert_called_once_with("MATCH (n) RETURN n", {})


# ---------------------------------------------------------------------------
# rename_property — reads result.rows[0][0] to decide when to stop
# ---------------------------------------------------------------------------


def test_rename_property_terminates_on_zero() -> None:
    executor = MagicMock()
    result = MagicMock()
    result.rows = [[0]]
    executor.execute.return_value = result

    ops = DataOperations(executor)
    ops.rename_property("Person", "fname", "first_name")

    assert executor.execute.call_count == 1
    cypher = executor.execute.call_args[0][0]
    assert "fname" in cypher
    assert "first_name" in cypher


def test_rename_property_loops_until_done() -> None:
    executor = MagicMock()
    executor.execute.side_effect = [
        MagicMock(rows=[[500]]),
        MagicMock(rows=[[500]]),
        MagicMock(rows=[[0]]),
    ]
    ops = DataOperations(executor)
    ops.rename_property("Person", "fname", "first_name", batch=500)
    assert executor.execute.call_count == 3


def test_rename_property_passes_batch_param() -> None:
    executor = MagicMock()
    executor.execute.return_value = MagicMock(rows=[[0]])
    ops = DataOperations(executor)
    ops.rename_property("Person", "fname", "first_name", batch=999)
    _, params = executor.execute.call_args[0]
    assert params["batch"] == 999


def test_rename_property_empty_rows_terminates() -> None:
    executor = _make_executor(rows=[])
    ops = DataOperations(executor)
    ops.rename_property("Person", "fname", "first_name")
    assert executor.execute.call_count == 1


# ---------------------------------------------------------------------------
# relabel_nodes
# ---------------------------------------------------------------------------


def test_relabel_nodes_terminates_on_zero() -> None:
    executor = MagicMock()
    executor.execute.return_value = MagicMock(rows=[[0]])
    ops = DataOperations(executor)
    ops.relabel_nodes("OldLabel", "NewLabel")
    assert executor.execute.call_count == 1
    cypher = executor.execute.call_args[0][0]
    assert "OldLabel" in cypher
    assert "NewLabel" in cypher


def test_relabel_nodes_loops_until_done() -> None:
    executor = MagicMock()
    executor.execute.side_effect = [
        MagicMock(rows=[[200]]),
        MagicMock(rows=[[0]]),
    ]
    ops = DataOperations(executor)
    ops.relabel_nodes("OldLabel", "NewLabel")
    assert executor.execute.call_count == 2


def test_relabel_nodes_raises_for_single_label_backends() -> None:
    executor = MagicMock()
    executor.supports_multi_label = False
    ops = DataOperations(executor)
    with pytest.raises(NotImplementedError, match="multi-label"):
        ops.relabel_nodes("OldLabel", "NewLabel")
    executor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


def test_seed_unwind_merge() -> None:
    executor = _make_executor()
    ops = DataOperations(executor)
    rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    ops.seed("MERGE (n:Person {id: row.id}) SET n.name = row.name", rows)
    cypher, params = executor.execute.call_args[0]
    assert "UNWIND" in cypher
    assert "rows" in cypher
    assert params["rows"] == rows


def test_seed_wraps_query_with_unwind() -> None:
    executor = _make_executor()
    ops = DataOperations(executor)
    ops.seed("MERGE (n:Tag {id: row.id})", [{"id": 1}])
    cypher, _ = executor.execute.call_args[0]
    assert cypher.startswith("UNWIND $rows AS row")
