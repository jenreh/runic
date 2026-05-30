"""Unit tests for runic.introspect with mocked graph."""

from __future__ import annotations

from collections import OrderedDict
from unittest.mock import MagicMock

import pytest

from runic.introspect import read_live_schema


def _make_graph(index_rows: list, constraint_rows: list) -> MagicMock:
    graph = MagicMock()
    idx_result = MagicMock()
    idx_result.result_set = index_rows
    con_result = MagicMock()
    con_result.result_set = constraint_rows
    graph.ro_query.side_effect = lambda q: idx_result if "indexes" in q else con_result
    return graph


def _range_row(label: str, prop: str, entity: str = "NODE") -> list:
    return [
        label,
        [prop],
        OrderedDict({prop: ["RANGE"]}),
        OrderedDict({prop: OrderedDict()}),
        "english",
        [],
        entity,
        "OPERATIONAL",
        OrderedDict(),
    ]


def _fulltext_row(label: str, prop: str) -> list:
    return [
        label,
        [prop],
        OrderedDict({prop: ["FULLTEXT"]}),
        OrderedDict({prop: OrderedDict()}),
        "english",
        [],
        "NODE",
        "OPERATIONAL",
        OrderedDict(),
    ]


def _vector_row(label: str, prop: str, dim: int = 128, sim: str = "cosine") -> list:
    opts = OrderedDict(
        {
            prop: OrderedDict(
                {
                    "dimension": dim,
                    "similarityFunction": sim,
                    "M": 16,
                    "efConstruction": 200,
                    "efRuntime": 10,
                }
            )
        }
    )
    return [
        label,
        [prop],
        OrderedDict({prop: ["VECTOR"]}),
        opts,
        "english",
        [],
        "NODE",
        "OPERATIONAL",
        OrderedDict(),
    ]


def _constraint_row(
    con_type: str,
    label: str,
    props: list[str],
    entity: str = "NODE",
    status: str = "OPERATIONAL",
) -> list:
    return [con_type, label, props, entity, status]


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


def test_read_empty_graph() -> None:
    graph = _make_graph([], [])
    live = read_live_schema(graph)
    assert live.range_indexes == []
    assert live.fulltext_indexes == []
    assert live.vector_indexes == []
    assert live.constraints == []


def test_read_range_index() -> None:
    graph = _make_graph([_range_row("Person", "email")], [])
    live = read_live_schema(graph)
    assert len(live.range_indexes) == 1
    assert live.range_indexes[0].label == "Person"
    assert live.range_indexes[0].prop == "email"
    assert not live.range_indexes[0].rel


def test_read_relationship_range_index() -> None:
    graph = _make_graph([_range_row("KNOWS", "since", "RELATIONSHIP")], [])
    live = read_live_schema(graph)
    assert len(live.range_indexes) == 1
    assert live.range_indexes[0].rel is True


def test_read_fulltext_index() -> None:
    graph = _make_graph([_fulltext_row("Movie", "title")], [])
    live = read_live_schema(graph)
    assert len(live.fulltext_indexes) == 1
    assert live.fulltext_indexes[0].label == "Movie"
    assert "title" in live.fulltext_indexes[0].props


def test_read_vector_index() -> None:
    graph = _make_graph([_vector_row("Doc", "embedding", 128, "cosine")], [])
    live = read_live_schema(graph)
    assert len(live.vector_indexes) == 1
    v = live.vector_indexes[0]
    assert v.label == "Doc"
    assert v.prop == "embedding"
    assert v.dimension == 128
    assert v.similarity == "cosine"
    assert v.m == 16


def test_read_unique_constraint() -> None:
    graph = _make_graph([], [_constraint_row("UNIQUE", "User", ["id"])])
    live = read_live_schema(graph)
    assert len(live.constraints) == 1
    from runic.manifest import UniqueConstraint

    assert isinstance(live.constraints[0], UniqueConstraint)
    assert live.constraints[0].label == "User"


def test_read_mandatory_constraint() -> None:
    graph = _make_graph([], [_constraint_row("MANDATORY", "Person", ["name"])])
    live = read_live_schema(graph)
    from runic.manifest import MandatoryConstraint

    assert isinstance(live.constraints[0], MandatoryConstraint)


def test_skips_pending_constraint() -> None:
    row = _constraint_row("UNIQUE", "User", ["id"], status="PENDING")
    graph = _make_graph([], [row])
    live = read_live_schema(graph)
    assert live.constraints == []


def test_skips_migration_version_label() -> None:
    graph = _make_graph([_range_row("_FalkorMigrateVersion", "revision")], [])
    live = read_live_schema(graph)
    assert live.range_indexes == []


def test_asserts_on_too_few_index_columns() -> None:
    graph = _make_graph([["Person", ["email"]]], [])
    with pytest.raises(AssertionError, match=r"db\.indexes\(\)"):
        read_live_schema(graph)


def test_asserts_on_too_few_constraint_columns() -> None:
    graph = _make_graph([], [["UNIQUE", "User"]])
    with pytest.raises(AssertionError, match=r"db\.constraints\(\)"):
        read_live_schema(graph)


def test_multiple_indexes() -> None:
    graph = _make_graph(
        [
            _range_row("Person", "email"),
            _fulltext_row("Movie", "title"),
            _vector_row("Doc", "embedding"),
        ],
        [],
    )
    live = read_live_schema(graph)
    assert len(live.range_indexes) == 1
    assert len(live.fulltext_indexes) == 1
    assert len(live.vector_indexes) == 1
