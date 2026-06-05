"""TypeConverter interface and built-in converters for common Python types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class TypeConverter(ABC):
    """Interface for encoding/decoding custom Python types to/from graph values."""

    @abstractmethod
    def to_graph(self, value: Any) -> Any:
        """Convert a Python value to a graph-compatible representation."""

    @abstractmethod
    def from_graph(self, value: Any) -> Any:
        """Convert a graph value back to the Python type."""


class DatetimeConverter(TypeConverter):
    """Converts between Python datetime objects and ISO-8601 strings.

    FalkorDB stores datetimes as strings; this converter handles the round-trip.
    """

    def to_graph(self, value: Any) -> Any:
        from datetime import datetime

        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def from_graph(self, value: Any) -> Any:
        from datetime import datetime

        if value is None:
            return None
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return value


class EnumConverter(TypeConverter):
    """Converts between Python Enum members and their string values.

    Stores the enum's `.value` in the graph and reconstructs on load.
    """

    def __init__(self, enum_class: type[Enum]) -> None:
        self._enum_class = enum_class

    def to_graph(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Enum):
            return value.value
        return value

    def from_graph(self, value: Any) -> Any:
        if value is None:
            return None
        return self._enum_class(value)
