"""Unit tests for Edge base class."""

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Edge

# ---------------------------------------------------------------------------
# Simple edge definitions
# ---------------------------------------------------------------------------


class WorksForEdge(Edge, type="WORKS_FOR"):
    since: str = Field()
    role: str | None = Field(default=None)


class AutoTypeEdge(Edge):
    weight: float = Field(default=1.0)


# ---------------------------------------------------------------------------
# Registration & class attributes
# ---------------------------------------------------------------------------


def test_edge_type_stored() -> None:
    assert WorksForEdge._edge_type == "WORKS_FOR"


def test_edge_auto_type_uses_class_name() -> None:
    assert AutoTypeEdge._edge_type == "AutoTypeEdge"


def test_edge_fields_list_populated() -> None:
    names = [fi.name for fi in WorksForEdge._fields]
    assert "since" in names
    assert "role" in names


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_edge_construction_required_field() -> None:
    e = WorksForEdge(since="2024-01-01")
    assert e.since == "2024-01-01"
    assert e.role is None


def test_edge_construction_override_default() -> None:
    e = WorksForEdge(since="2024-01-01", role="engineer")
    assert e.role == "engineer"


def test_edge_construction_missing_required_raises() -> None:
    with pytest.raises(TypeError, match="since"):
        WorksForEdge()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Object state flags
# ---------------------------------------------------------------------------


def test_edge_new_true_after_construction() -> None:
    e = WorksForEdge(since="2024-01-01")
    assert e._new is True


def test_edge_dirty_false_after_construction() -> None:
    e = WorksForEdge(since="2024-01-01")
    assert e._dirty is False


def test_edge_setting_field_marks_dirty() -> None:
    e = WorksForEdge(since="2024-01-01")
    e.since = "2025-01-01"
    assert e._dirty is True


def test_edge_setting_field_stores_value() -> None:
    e = WorksForEdge(since="2024-01-01")
    e.role = "lead"
    assert e.role == "lead"


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_edge_repr_includes_type() -> None:
    e = WorksForEdge(since="2024-01-01")
    r = repr(e)
    assert "WorksForEdge" in r
    assert "WORKS_FOR" in r
