"""Unit tests for automatic type converter assignment (feature 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum, StrEnum

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.core.types import (
    DatetimeConverter,
    EnumConverter,
    GeoLocation,
    GeoLocationConverter,
    Vector,
    VectorConverter,
)

# ---------------------------------------------------------------------------
# Auto-converter: datetime
# ---------------------------------------------------------------------------


class AutoDateNode(Node, labels=["AutoDateNode"]):
    id: str = Field()
    created_at: datetime = Field()
    updated_at: datetime | None = Field(default=None)


def test_datetime_field_gets_datetime_converter() -> None:
    fi = next(f for f in AutoDateNode._fields if f.name == "created_at")
    assert isinstance(fi.field.converter, DatetimeConverter)


def test_optional_datetime_field_gets_datetime_converter() -> None:
    fi = next(f for f in AutoDateNode._fields if f.name == "updated_at")
    assert isinstance(fi.field.converter, DatetimeConverter)


def test_datetime_converter_roundtrip() -> None:
    fi = next(f for f in AutoDateNode._fields if f.name == "created_at")
    assert fi.field.converter is not None
    dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    encoded = fi.field.converter.to_graph(dt)
    assert encoded == "2024-01-15T12:00:00+00:00"
    decoded = fi.field.converter.from_graph(encoded)
    assert decoded == dt


# ---------------------------------------------------------------------------
# Auto-converter: Enum
# ---------------------------------------------------------------------------


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


class Priority(Enum):
    LOW = 1
    HIGH = 2


class AutoEnumNode(Node, labels=["AutoEnumNode"]):
    id: str
    color: Color
    priority: Priority | None = Field(default=None)


def test_enum_field_gets_enum_converter() -> None:
    fi = next(f for f in AutoEnumNode._fields if f.name == "color")
    assert isinstance(fi.field.converter, EnumConverter)


def test_optional_enum_field_gets_enum_converter() -> None:
    fi = next(f for f in AutoEnumNode._fields if f.name == "priority")
    assert isinstance(fi.field.converter, EnumConverter)


def test_enum_converter_roundtrip_str_enum() -> None:
    fi = next(f for f in AutoEnumNode._fields if f.name == "color")
    assert fi.field.converter is not None
    encoded = fi.field.converter.to_graph(Color.RED)
    assert encoded == "red"
    decoded = fi.field.converter.from_graph(encoded)
    assert decoded is Color.RED


def test_enum_converter_roundtrip_int_enum() -> None:
    fi = next(f for f in AutoEnumNode._fields if f.name == "priority")
    assert fi.field.converter is not None
    encoded = fi.field.converter.to_graph(Priority.HIGH)
    assert encoded == 2
    decoded = fi.field.converter.from_graph(encoded)
    assert decoded is Priority.HIGH


# ---------------------------------------------------------------------------
# Auto-converter: Vector
# ---------------------------------------------------------------------------


class AutoVecNode(Node, labels=["AutoVecNode"]):
    id: str
    embedding: Vector
    alt_embedding: Vector | None = Field(default=None, index_type="VECTOR")


def test_vector_field_gets_vector_converter() -> None:
    fi = next(f for f in AutoVecNode._fields if f.name == "embedding")
    assert isinstance(fi.field.converter, VectorConverter)


def test_optional_vector_field_gets_vector_converter() -> None:
    fi = next(f for f in AutoVecNode._fields if f.name == "alt_embedding")
    assert isinstance(fi.field.converter, VectorConverter)


# ---------------------------------------------------------------------------
# Auto-converter: GeoLocation
# ---------------------------------------------------------------------------


class AutoGeoNode(Node, labels=["AutoGeoNode"]):
    id: str = Field()
    location: GeoLocation
    alt_location: GeoLocation | None = Field(default=None)


def test_geolocation_field_gets_geolocation_converter() -> None:
    fi = next(f for f in AutoGeoNode._fields if f.name == "location")
    assert isinstance(fi.field.converter, GeoLocationConverter)


def test_optional_geolocation_field_gets_geolocation_converter() -> None:
    fi = next(f for f in AutoGeoNode._fields if f.name == "alt_location")
    assert isinstance(fi.field.converter, GeoLocationConverter)


# ---------------------------------------------------------------------------
# Explicit converter is never overridden
# ---------------------------------------------------------------------------


class CustomConverter(DatetimeConverter):
    """Sentinel subclass to verify explicit converters are preserved."""


class ExplicitConverterNode(Node, labels=["ExplicitConverterNode"]):
    id: str
    ts: datetime = Field(converter=CustomConverter())


def test_explicit_converter_not_overridden() -> None:
    fi = next(f for f in ExplicitConverterNode._fields if f.name == "ts")
    assert isinstance(fi.field.converter, CustomConverter)


# ---------------------------------------------------------------------------
# Plain str/int fields receive no auto-converter
# ---------------------------------------------------------------------------


class PlainNode(Node, labels=["PlainAutoNode"]):
    id: str
    name: str = Field()
    count: int = Field(default=0)


def test_str_field_has_no_converter() -> None:
    fi = next(f for f in PlainNode._fields if f.name == "name")
    assert fi.field.converter is None


def test_int_field_has_no_converter() -> None:
    fi = next(f for f in PlainNode._fields if f.name == "count")
    assert fi.field.converter is None
