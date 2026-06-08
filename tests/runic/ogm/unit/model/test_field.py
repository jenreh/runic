"""Unit tests for the Field and Relation descriptors."""

import pytest

from runic.ogm.core.descriptors import (
    MISSING,
    Field,
    FieldDescriptor,
    FieldInfo,
    Relation,
)
from runic.ogm.core.models import Node


class _Holder(Node, labels=["_Holder"]):
    """Minimal Node to host Field descriptors for testing."""

    value: int = Field(default=0)
    name: str = Field()
    optional: str | None = Field(default=None)


# --------------------------------------------------------------------------
# Field construction
# --------------------------------------------------------------------------


def test_field_default_stored() -> None:
    f = Field(default=42)
    assert f.default == 42
    assert f.has_default is True


def test_field_no_default_is_missing() -> None:
    f = Field()
    assert f.default is MISSING
    assert f.has_default is False


def test_field_default_factory() -> None:
    f = Field(default_factory=list)
    assert f.has_default is True
    assert f.get_default() == []
    assert f.get_default() is not f.get_default()


def test_field_cannot_set_both_default_and_factory() -> None:
    with pytest.raises(ValueError, match="both"):
        Field(default=1, default_factory=list)


def test_field_generated_auto_defaults_none() -> None:
    f = Field(generated=True)
    assert f.default is None
    assert f.has_default is True


def test_field_index_params() -> None:
    f = Field(index=True, unique=True)
    assert f.index is True
    assert f.unique is True


def test_field_interned_flag() -> None:
    f = Field(interned=True)
    assert f.interned is True


def test_field_interned_defaults_false() -> None:
    f = Field()
    assert f.interned is False


def test_field_primary_key_flag() -> None:
    f = Field(primary_key=True)
    assert f.primary_key is True


def test_field_returns_field_descriptor() -> None:
    f = Field(default=0)
    assert isinstance(f, FieldDescriptor)


# --------------------------------------------------------------------------
# Relation construction
# --------------------------------------------------------------------------


def test_relation_auto_defaults_none() -> None:
    r = Relation(relationship="KNOWS", direction="OUTGOING", target="Person")
    assert r.default is None


def test_relation_stores_relationship_params() -> None:
    r = Relation(
        relationship="KNOWS",
        direction="OUTGOING",
        target="Person",
        edge_model=None,
        cascade=False,
        lazy=True,
    )
    assert r.relationship == "KNOWS"
    assert r.direction == "OUTGOING"
    assert r.target == "Person"
    assert r.lazy is True
    assert r.cascade is False


def test_relation_requires_relationship() -> None:
    with pytest.raises(TypeError):
        Relation(direction="OUTGOING", target="Person")  # type: ignore


def test_relation_requires_direction() -> None:
    with pytest.raises(TypeError):
        Relation(relationship="KNOWS", target="Person")  # type: ignore


def test_relation_requires_target() -> None:
    with pytest.raises(TypeError):
        Relation(relationship="KNOWS", direction="OUTGOING")  # type: ignore


def test_relation_rejects_index() -> None:
    with pytest.raises(ValueError, match="index"):
        FieldDescriptor(
            relationship="KNOWS", direction="OUTGOING", target="X", index=True
        )


def test_relation_rejects_unique() -> None:
    with pytest.raises(ValueError, match="index"):
        FieldDescriptor(
            relationship="KNOWS", direction="OUTGOING", target="X", unique=True
        )


def test_relation_returns_field_descriptor() -> None:
    r = Relation(relationship="KNOWS", direction="OUTGOING", target="Person")
    assert isinstance(r, FieldDescriptor)


def test_relation_custom_default() -> None:
    r = Relation(
        relationship="KNOWS", direction="OUTGOING", target="Person", default=[]
    )
    assert r.default == []


# --------------------------------------------------------------------------
# __set_name__
# --------------------------------------------------------------------------


def test_set_name_captures_attribute_name() -> None:
    f = Field(default=0)
    f.__set_name__(_Holder, "my_field")
    assert f._name == "my_field"


# --------------------------------------------------------------------------
# Descriptor protocol on instances
# --------------------------------------------------------------------------


def test_get_returns_default_when_unset() -> None:
    obj = object.__new__(_Holder)
    obj.__dict__["_dirty"] = False
    obj.__dict__["_new"] = True
    assert _Holder.__dict__["value"].__get__(obj, _Holder) == 0


def test_get_returns_stored_value() -> None:
    obj = object.__new__(_Holder)
    obj.__dict__["_dirty"] = False
    obj.__dict__["_new"] = True
    obj.__dict__["value"] = 99
    assert obj.value == 99


def test_set_stores_value_and_marks_dirty() -> None:
    obj = object.__new__(_Holder)
    obj.__dict__["_dirty"] = False
    obj.__dict__["_new"] = True
    obj.value = 7
    assert obj.__dict__["value"] == 7
    assert obj._dirty is True


def test_get_on_class_returns_descriptor() -> None:
    assert isinstance(_Holder.__dict__["value"], FieldDescriptor)


def test_get_raises_when_no_default_and_no_value() -> None:
    obj = object.__new__(_Holder)
    obj.__dict__["_dirty"] = False
    with pytest.raises(AttributeError, match="name"):
        _ = obj.name


# --------------------------------------------------------------------------
# FieldInfo
# --------------------------------------------------------------------------


def test_field_info_stores_name_and_field() -> None:
    f = Field(default=1)
    fi = FieldInfo(name="count", field=f)
    assert fi.name == "count"
    assert fi.field is f


def test_field_info_repr() -> None:
    f = Field(default=0)
    fi = FieldInfo(name="x", field=f)
    assert "x" in repr(fi)


# --------------------------------------------------------------------------
# Optional bare annotations auto-infer default=None
# --------------------------------------------------------------------------


class _OptionalHolder(Node, labels=["_OptionalHolder"]):
    """Node with X | None = None annotations — omittable in __init__."""

    id: str
    tag: str | None = None
    score: int | None = None


def test_optional_bare_annotation_has_default_none() -> None:
    fi = next(f for f in _OptionalHolder._fields if f.name == "tag")
    assert fi.field.has_default is True
    assert fi.field.get_default() is None


def test_optional_bare_annotation_omittable_in_init() -> None:
    obj = _OptionalHolder(id="x")
    assert obj.tag is None
    assert obj.score is None


def test_required_bare_annotation_still_required() -> None:
    with pytest.raises(TypeError, match="missing required"):
        _OptionalHolder(tag="t")  # type: ignore  # id is required and non-optional
