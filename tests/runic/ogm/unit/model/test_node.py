"""Unit tests for Node base class."""

import pytest

from runic.ogm.core.descriptors import Field
from runic.ogm.core.models import Node

# ---------------------------------------------------------------------------
# Simple node definitions (module-level, registered once on import)
# ---------------------------------------------------------------------------


class SimplePerson(Node, labels=["SimplePerson"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    email: str = Field(index=True, unique=True)
    age: int | None = Field(default=None)


class BaseLocation(Node, labels=["BaseLocation"], primary_label="BaseLocation"):
    id: str = Field(primary_key=True)
    title: str = Field()
    latitude: float = Field()
    longitude: float = Field()


class ChildCountry(
    BaseLocation,
    labels=["BaseLocation", "ChildCountry"],
    primary_label="BaseLocation",
):
    iso_code: str = Field(unique=True)
    population: int | None = Field(default=None)


class AutoLabelNode(Node):
    id: str = Field()


# ---------------------------------------------------------------------------
# Registration & class attributes
# ---------------------------------------------------------------------------


def test_labels_stored_on_class() -> None:
    assert SimplePerson._labels == ["SimplePerson"]


def test_primary_label_defaults_to_first_label() -> None:
    assert SimplePerson._primary_label == "SimplePerson"


def test_explicit_primary_label() -> None:
    assert BaseLocation._primary_label == "BaseLocation"


def test_auto_label_uses_class_name() -> None:
    assert AutoLabelNode._labels == ["AutoLabelNode"]


def test_fields_list_populated() -> None:
    names = [fi.name for fi in SimplePerson._fields]
    assert "id" in names
    assert "name" in names
    assert "email" in names
    assert "age" in names


# ---------------------------------------------------------------------------
# Inheritance: child collects parent fields
# ---------------------------------------------------------------------------


def test_child_inherits_parent_fields() -> None:
    names = {fi.name for fi in ChildCountry._fields}
    # Parent fields
    assert "id" in names
    assert "title" in names
    assert "latitude" in names
    assert "longitude" in names
    # Own fields
    assert "iso_code" in names
    assert "population" in names


def test_child_labels_stored() -> None:
    assert ChildCountry._labels == ["BaseLocation", "ChildCountry"]


# ---------------------------------------------------------------------------
# Construction: __init__ generated correctly
# ---------------------------------------------------------------------------


def test_construction_sets_required_fields() -> None:
    p = SimplePerson(id="1", name="Alice", email="alice@example.com")
    assert p.id == "1"
    assert p.name == "Alice"
    assert p.email == "alice@example.com"


def test_construction_applies_default() -> None:
    p = SimplePerson(id="1", name="Alice", email="alice@example.com")
    assert p.age is None


def test_construction_kwarg_overrides_default() -> None:
    p = SimplePerson(id="1", name="Alice", email="alice@example.com", age=30)
    assert p.age == 30


def test_construction_missing_required_raises() -> None:
    with pytest.raises(TypeError, match="name"):
        SimplePerson(id="1", email="x@x.com")  # type: ignore


def test_construction_unknown_kwarg_raises() -> None:
    with pytest.raises(TypeError, match="unknown"):
        SimplePerson(id="1", name="A", email="a@a.com", unknown=True)  # type: ignore


# ---------------------------------------------------------------------------
# Object state flags
# ---------------------------------------------------------------------------


def test_new_is_true_after_construction() -> None:
    p = SimplePerson(id="1", name="A", email="a@a.com")
    assert p._new is True


def test_dirty_is_false_after_construction() -> None:
    p = SimplePerson(id="1", name="A", email="a@a.com")
    assert p._dirty is False


def test_setting_field_marks_dirty() -> None:
    p = SimplePerson(id="1", name="A", email="a@a.com")
    p.name = "B"
    assert p._dirty is True


def test_setting_field_stores_value() -> None:
    p = SimplePerson(id="1", name="A", email="a@a.com")
    p.name = "Alice Smith"
    assert p.name == "Alice Smith"


def test_dirty_flag_is_per_instance() -> None:
    p1 = SimplePerson(id="1", name="A", email="a@a.com")
    p2 = SimplePerson(id="2", name="B", email="b@b.com")
    p1.name = "Changed"
    assert p1._dirty is True
    assert p2._dirty is False


# ---------------------------------------------------------------------------
# Construction does NOT trigger _dirty
# ---------------------------------------------------------------------------


def test_construction_with_factory_default_not_dirty() -> None:
    class HasFactory(Node, labels=["HasFactory"]):
        items: list[str] = Field(default_factory=list)

    obj = HasFactory()
    assert obj._dirty is False
    assert obj.items == []


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_includes_pk() -> None:
    p = SimplePerson(id="abc", name="A", email="a@a.com")
    assert "abc" in repr(p)
    assert "SimplePerson" in repr(p)
