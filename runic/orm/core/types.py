"""TypeConverter interface and built-in converters for common Python types."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class TypeConverter(ABC):
    """Interface for encoding/decoding custom Python types to/from graph values.

    Optionally, set ``cypher_fn`` to name a FalkorDB Cypher function that wraps
    the parameter reference when writing to the graph (e.g. ``"vecf32"`` → ``vecf32($field)``).
    """

    cypher_fn: str | None = None

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


class Vector(list):
    """A typed list of floats representing a graph embedding vector.

    Use as an annotation on a Node field to store and query embeddings::

        class Article(Node, labels=["Article"]):
            id: str = Field(primary_key=True)
            embedding: Vector = Field(index=True, index_type="VECTOR")

    FalkorDB stores vectors via ``vecf32()``, preserving 32-bit float precision.
    """

    def __repr__(self) -> str:
        return f"Vector({list.__repr__(self)})"


class VectorConverter(TypeConverter):
    """Converts between Python Vector (list of floats) and FalkorDB's vecf32 format.

    Emits ``vecf32($field)`` in Cypher via ``cypher_fn = "vecf32"``.
    """

    cypher_fn = "vecf32"

    def to_graph(self, value: Any) -> Any:
        if value is None:
            return None
        return list(value)

    def from_graph(self, value: Any) -> Any:
        if value is None:
            return None
        return Vector(value)


@dataclass
class GeoLocation:
    """A geographic point with latitude and longitude.

    Maps to FalkorDB's native ``point()`` type::

        class Store(Node, labels=["Store"]):
            id: str = Field(primary_key=True)
            location: GeoLocation = Field()

    FalkorDB round-trips this as ``point({latitude: ..., longitude: ...})``.
    """

    latitude: float
    longitude: float

    def __repr__(self) -> str:
        return f"GeoLocation(latitude={self.latitude}, longitude={self.longitude})"


class GeoLocationConverter(TypeConverter):
    """Converts between GeoLocation and FalkorDB's point() dict format.

    Emits ``point($field)`` in Cypher via ``cypher_fn = "point"``.
    FalkorDB returns points as ``{"latitude": ..., "longitude": ...}`` dicts.
    """

    cypher_fn = "point"

    def to_graph(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, GeoLocation):
            return {"latitude": value.latitude, "longitude": value.longitude}
        return value

    def from_graph(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return GeoLocation(
                latitude=value["latitude"],
                longitude=value["longitude"],
            )
        # neo4j.spatial.WGS84Point and similar have .latitude/.longitude attrs
        if hasattr(value, "latitude") and hasattr(value, "longitude"):
            return GeoLocation(latitude=value.latitude, longitude=value.longitude)
        return value
