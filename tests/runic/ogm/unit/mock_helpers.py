"""Shared mock result builders for driver-level (GraphResult) tests.

These helpers produce MagicMocks with the `.rows` / `.columns` shape returned
by all GraphDriver implementations.  They are intentionally NOT the raw
FalkorDB graph-level mocks (which expose `.result_set`); those belong in the
FalkorDB-specific driver tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def empty_result() -> MagicMock:
    r = MagicMock()
    r.rows = []
    r.columns = []
    return r


def scalar_result(value: Any) -> MagicMock:
    r = MagicMock()
    r.rows = [[value]]
    r.columns = ["value"]
    return r


def node_result(labels: list[str], props: dict[str, Any]) -> MagicMock:
    node = MagicMock()
    node.id = props.get("id", 1)
    node.labels = labels
    node.properties = props
    r = MagicMock()
    r.rows = [[node]]
    r.columns = ["n"]
    return r


def multi_node_result(rows: list[tuple[list[str], dict[str, Any]]]) -> MagicMock:
    result_rows = []
    for labels, props in rows:
        node = MagicMock()
        node.id = props.get("id", 1)
        node.labels = labels
        node.properties = props
        result_rows.append([node])
    r = MagicMock()
    r.rows = result_rows
    r.columns = ["n"]
    return r


def row_result(*rows: list[Any]) -> MagicMock:
    r = MagicMock()
    r.rows = list(rows)
    return r
