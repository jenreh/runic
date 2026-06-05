"""Tests for the baseline op-call renderer (script.render_op_body)."""

from __future__ import annotations

from runic.migrate.introspect import (
    ConstraintSpec,
    IndexSpec,
    OpCall,
    SchemaSnapshot,
    full_downgrade_ops,
    full_upgrade_ops,
)
from runic.migrate.script import ScriptDirectory, render_op_body

# ---------------------------------------------------------------------------
# _render_op_call indirectly via render_op_body
# ---------------------------------------------------------------------------


def test_render_empty_ops_is_pass() -> None:
    assert render_op_body([]).strip() == "pass"


def test_render_range_index_node() -> None:
    ops = [OpCall("create_range_index", ("Person", "email"), {})]
    body = render_op_body(ops)
    assert "op.create_range_index('Person', 'email')" in body


def test_render_range_index_rel() -> None:
    ops = [OpCall("create_range_index", ("PURCHASED", "purchased_at"), {"rel": True})]
    body = render_op_body(ops)
    assert "rel=True" in body
    assert "create_range_index" in body


def test_render_fulltext_multi_prop() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Article", ["title", "body"], "FULLTEXT", "NODE")],
        constraints=[],
    )
    body = render_op_body(full_upgrade_ops(snapshot))
    assert "create_fulltext_index" in body
    assert "title" in body
    assert "body" in body


def test_render_vector_is_commented() -> None:
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
    body = render_op_body(full_upgrade_ops(snapshot))
    lines = [ln.strip() for ln in body.splitlines()]
    assert any(ln.startswith("#") and "create_vector_index" in ln for ln in lines)
    assert any("verify options manually" in ln for ln in lines)


def test_render_unique_constraint() -> None:
    ops = [OpCall("create_constraint", ("UNIQUE", "NODE", "Person", ["email"]), {})]
    body = render_op_body(ops)
    assert "create_constraint" in body
    assert "'UNIQUE'" in body
    assert "'Person'" in body


def test_render_section_comments_in_upgrade() -> None:
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    body = render_op_body(full_upgrade_ops(snapshot))
    assert "# --- Indexes ---" in body
    assert "# --- Constraints ---" in body


def test_render_downgrade_order_constraints_before_indexes() -> None:
    """The rendered downgrade body must drop constraints before their backing indexes."""
    snapshot = SchemaSnapshot(
        indexes=[IndexSpec("Person", ["email"], "RANGE", "NODE")],
        constraints=[ConstraintSpec("UNIQUE", "Person", ["email"], "NODE")],
    )
    body = render_op_body(full_downgrade_ops(snapshot))
    lines = body.splitlines()
    drop_constraint_idx = next(
        (i for i, ln in enumerate(lines) if "drop_constraint" in ln), None
    )
    drop_index_idx = next(
        (i for i, ln in enumerate(lines) if "drop_range_index" in ln), None
    )
    assert drop_constraint_idx is not None
    assert drop_index_idx is not None
    assert drop_constraint_idx < drop_index_idx, (
        "drop_constraint must precede drop_range_index in downgrade body"
    )


def test_render_down_revision_none_in_generated_file(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    snapshot = SchemaSnapshot(indexes=[], constraints=[])
    sd = ScriptDirectory()
    path = sd.create(
        "baseline",
        None,
        tmp_path,
        upgrade_body=render_op_body(full_upgrade_ops(snapshot)),
        downgrade_body=render_op_body(full_downgrade_ops(snapshot)),
    )
    content = path.read_text()
    assert "down_revision = None" in content
