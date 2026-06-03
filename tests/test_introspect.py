"""Unit tests for runic.introspect with mocked graph."""

from __future__ import annotations

import logging
from collections import OrderedDict
from unittest.mock import MagicMock

import pytest

from runic.introspect import (
    ConstraintSpec,
    IndexSpec,
    SchemaSnapshot,
    full_downgrade_ops,
    full_upgrade_ops,
    introspect_graph,
    read_live_schema,
)


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


# ---------------------------------------------------------------------------
# introspect_graph — SchemaSnapshot (Phase 2.5)
# ---------------------------------------------------------------------------


def _multi_fulltext_row(label: str, props: list[str]) -> list:
    types_dict = OrderedDict({p: ["FULLTEXT"] for p in props})
    opts_dict = OrderedDict({p: OrderedDict() for p in props})
    return [
        label,
        props,
        types_dict,
        opts_dict,
        "english",
        [],
        "NODE",
        "OPERATIONAL",
        OrderedDict(),
    ]


def test_introspect_graph_range_node() -> None:
    graph = _make_graph([_range_row("Person", "email")], [])
    snapshot = introspect_graph(graph)
    assert len(snapshot.indexes) == 1
    idx = snapshot.indexes[0]
    assert idx.label == "Person"
    assert idx.properties == ["email"]
    assert idx.index_type == "RANGE"
    assert idx.entity_type == "NODE"


def test_introspect_graph_range_rel() -> None:
    graph = _make_graph([_range_row("KNOWS", "since", "RELATIONSHIP")], [])
    snapshot = introspect_graph(graph)
    assert snapshot.indexes[0].entity_type == "RELATIONSHIP"
    assert snapshot.indexes[0].index_type == "RANGE"


def test_introspect_graph_fulltext_multi_prop() -> None:
    graph = _make_graph([_multi_fulltext_row("Article", ["title", "body"])], [])
    snapshot = introspect_graph(graph)
    assert len(snapshot.indexes) == 1
    idx = snapshot.indexes[0]
    assert idx.index_type == "FULLTEXT"
    assert sorted(idx.properties) == ["body", "title"]


def test_introspect_graph_vector_with_options() -> None:
    graph = _make_graph([_vector_row("Product", "embedding", 128, "cosine")], [])
    snapshot = introspect_graph(graph)
    assert len(snapshot.indexes) == 1
    idx = snapshot.indexes[0]
    assert idx.index_type == "VECTOR"
    assert idx.options is not None
    assert idx.options["dimension"] == 128
    assert idx.options["similarityFunction"] == "cosine"


def test_introspect_graph_unique_constraint() -> None:
    graph = _make_graph([], [_constraint_row("UNIQUE", "Person", ["email"])])
    snapshot = introspect_graph(graph)
    assert len(snapshot.constraints) == 1
    c = snapshot.constraints[0]
    assert c.kind == "UNIQUE"
    assert c.label == "Person"
    assert c.properties == ["email"]
    assert c.entity_type == "NODE"


def test_introspect_graph_mandatory_constraint() -> None:
    graph = _make_graph([], [_constraint_row("MANDATORY", "Order", ["id"])])
    snapshot = introspect_graph(graph)
    assert snapshot.constraints[0].kind == "MANDATORY"


def test_introspect_graph_excludes_migration_label() -> None:
    graph = _make_graph([_range_row("_FalkorMigrateVersion", "revision")], [])
    snapshot = introspect_graph(graph)
    assert snapshot.indexes == []


def test_introspect_graph_excludes_migration_constraint() -> None:
    graph = _make_graph(
        [], [_constraint_row("UNIQUE", "_FalkorMigrateVersion", ["id"])]
    )
    snapshot = introspect_graph(graph)
    assert snapshot.constraints == []


def test_introspect_graph_malformed_index_row_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    graph = _make_graph([["Person"]], [])
    with caplog.at_level(logging.WARNING):
        snapshot = introspect_graph(graph)
    assert snapshot.indexes == []
    assert "skipping" in caplog.text.lower()


def test_introspect_graph_malformed_constraint_row_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    graph = _make_graph([], [["UNIQUE"]])
    with caplog.at_level(logging.WARNING):
        snapshot = introspect_graph(graph)
    assert snapshot.constraints == []
    assert "skipping" in caplog.text.lower()


def test_introspect_graph_empty() -> None:
    graph = _make_graph([], [])
    snapshot = introspect_graph(graph)
    assert snapshot.indexes == []
    assert snapshot.constraints == []


# ---------------------------------------------------------------------------
# full_upgrade_ops / full_downgrade_ops (Phase 2.5)
# ---------------------------------------------------------------------------


def test_full_upgrade_ops_range_node() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[],
    )
    ops = full_upgrade_ops(snapshot)
    assert len(ops) == 1
    op = ops[0]
    assert op.method == "create_range_index"
    assert op.args == ("Person", "email")
    assert op.kwargs == {}
    assert op.comment is None


def test_full_upgrade_ops_range_rel() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("PURCHASED", ["purchased_at"], "RANGE", "RELATIONSHIP")],
        constraints=[],
    )
    ops = full_upgrade_ops(snapshot)
    assert ops[0].kwargs == {"rel": True}


def test_full_upgrade_ops_fulltext_multi_prop() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Article", ["title", "body"], "FULLTEXT", "NODE")],
        constraints=[],
    )
    ops = full_upgrade_ops(snapshot)
    assert len(ops) == 1
    op = ops[0]
    assert op.method == "create_fulltext_index"
    assert op.args == ("Article", "title", "body")


def test_full_upgrade_ops_vector_is_stub() -> None:
    snapshot = SchemaSnapshot(
        indexes=[
            IndexSpec(
                "Product",
                ["embedding"],
                "VECTOR",
                "NODE",
                options={"dimension": 128, "similarityFunction": "cosine"},
            )
        ],
        constraints=[],
    )
    ops = full_upgrade_ops(snapshot)
    assert ops[0].method == "create_vector_index"
    assert ops[0].comment == "verify options manually"


def test_full_upgrade_ops_unique_constraint() -> None:
    snapshot = SchemaSnapshot(
        indexes=[],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    ops = full_upgrade_ops(snapshot)
    assert ops[0].method == "create_constraint"
    assert ops[0].args == ("UNIQUE", "NODE", "Person", ["email"])


def test_full_downgrade_constraints_before_indexes() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    upgrade_ops = full_upgrade_ops(snapshot)
    downgrade_ops = full_downgrade_ops(snapshot)

    assert upgrade_ops[0].method == "create_range_index"
    assert upgrade_ops[1].method == "create_constraint"
    assert downgrade_ops[0].method == "drop_constraint"
    assert downgrade_ops[1].method == "drop_range_index"


def test_full_downgrade_vector_is_stub() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Product", ["embedding"], "VECTOR", "NODE")],
        constraints=[],
    )
    ops = full_downgrade_ops(snapshot)
    assert ops[0].method == "drop_vector_index"
    assert ops[0].comment == "verify before enabling"
