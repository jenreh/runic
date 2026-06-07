"""Unit tests for TypeConverter and built-in converters."""

from datetime import UTC, datetime
from enum import Enum

import pytest

from runic.orm.core.types import DatetimeConverter, EnumConverter, TypeConverter

# ---------------------------------------------------------------------------
# TypeConverter interface
# ---------------------------------------------------------------------------


def test_type_converter_is_abstract() -> None:
    with pytest.raises(TypeError):
        TypeConverter()  # type: ignore[abstract]


def test_type_converter_requires_to_graph() -> None:
    class Partial(TypeConverter):
        def from_graph(self, value: object) -> object:
            return value

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]


def test_type_converter_requires_from_graph() -> None:
    class Partial(TypeConverter):
        def to_graph(self, value: object) -> object:
            return value

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]


def test_custom_converter_works() -> None:
    class UpperConverter(TypeConverter):
        def to_graph(self, value: object) -> object:
            return str(value).upper() if value is not None else None

        def from_graph(self, value: object) -> object:
            return str(value).lower() if value is not None else None

    c = UpperConverter()
    assert c.to_graph("hello") == "HELLO"
    assert c.from_graph("HELLO") == "hello"


# ---------------------------------------------------------------------------
# DatetimeConverter
# ---------------------------------------------------------------------------


def test_datetime_to_graph_produces_iso_string() -> None:
    c = DatetimeConverter()
    dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    result = c.to_graph(dt)
    assert result == "2024-06-01T12:00:00+00:00"


def test_datetime_from_graph_produces_datetime() -> None:
    c = DatetimeConverter()
    result = c.from_graph("2024-06-01T12:00:00+00:00")
    assert isinstance(result, datetime)
    assert result == datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_datetime_roundtrip() -> None:
    c = DatetimeConverter()
    dt = datetime(2025, 1, 15, 8, 30, 0, tzinfo=UTC)
    assert c.from_graph(c.to_graph(dt)) == dt


def test_datetime_to_graph_none() -> None:
    c = DatetimeConverter()
    assert c.to_graph(None) is None


def test_datetime_from_graph_none() -> None:
    c = DatetimeConverter()
    assert c.from_graph(None) is None


def test_datetime_passthrough_non_datetime() -> None:
    c = DatetimeConverter()
    # Already a string → returned as-is.
    assert c.to_graph("2024-01-01") == "2024-01-01"


# ---------------------------------------------------------------------------
# EnumConverter
# ---------------------------------------------------------------------------


class _Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


def test_enum_to_graph_returns_value() -> None:
    c = EnumConverter(_Color)
    assert c.to_graph(_Color.RED) == "red"


def test_enum_from_graph_returns_member() -> None:
    c = EnumConverter(_Color)
    result = c.from_graph("green")
    assert result is _Color.GREEN


def test_enum_roundtrip() -> None:
    c = EnumConverter(_Color)
    assert c.from_graph(c.to_graph(_Color.BLUE)) is _Color.BLUE


def test_enum_to_graph_none() -> None:
    c = EnumConverter(_Color)
    assert c.to_graph(None) is None


def test_enum_from_graph_none() -> None:
    c = EnumConverter(_Color)
    assert c.from_graph(None) is None
