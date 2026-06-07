"""Integration tests for Vector, GeoLocation, interned strings, and auto-converters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.core.types import GeoLocation, Vector
from runic.orm.session.session import Session

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test entities — unique "Int" prefix labels avoid collision with other modules
# ---------------------------------------------------------------------------


class IntInternedNode(Node, labels=["IntInternedNode"]):
    id: str = Field()
    country: str = Field(interned=True)
    tag: str = Field(interned=True)
    name: str = Field()


class IntVectorNode(Node, labels=["IntVectorNode"]):
    id: str = Field()
    embedding: Vector = Field()


class IntGeoNode(Node, labels=["IntGeoNode"]):
    id: str = Field()
    location: GeoLocation = Field()


class IntStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class IntAutoNode(Node, labels=["IntAutoNode"]):
    """Tests auto-converter assignment for datetime and Enum without explicit converter=."""

    id: str = Field()
    status: IntStatus = Field()
    created_at: datetime = Field()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Interned strings
# ---------------------------------------------------------------------------


def test_interned_field_roundtrip(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntInternedNode(id="i1", country="Germany", tag="europe", name="Alice")
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntInternedNode, "i1")
        assert loaded is not None
        assert loaded.country == "Germany"
        assert loaded.tag == "europe"
        assert loaded.name == "Alice"


def test_interned_field_update(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntInternedNode(id="i2", country="France", tag="eu", name="Bob")
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntInternedNode, "i2")
        assert loaded is not None
        loaded.country = "Germany"
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntInternedNode, "i2")
        assert loaded is not None
        assert loaded.country == "Germany"


def test_interned_field_is_string_on_read(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntInternedNode(id="i3", country="Spain", tag="es", name="Carlos")
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntInternedNode, "i3")
        assert loaded is not None
        assert isinstance(loaded.country, str)


# ---------------------------------------------------------------------------
# Vector
# ---------------------------------------------------------------------------


def test_vector_roundtrip(graph_driver: Any) -> None:
    emb = Vector([0.1, 0.2, 0.3])
    with Session(graph_driver) as s:
        node = IntVectorNode(id="v1", embedding=emb)
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntVectorNode, "v1")
        assert loaded is not None
        result = loaded.embedding
        assert isinstance(result, Vector)
        assert len(result) == 3
        assert abs(result[0] - 0.1) < 1e-5
        assert abs(result[1] - 0.2) < 1e-5
        assert abs(result[2] - 0.3) < 1e-5


def test_vector_update(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntVectorNode(id="v2", embedding=Vector([1.0, 0.0]))
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntVectorNode, "v2")
        assert loaded is not None
        loaded.embedding = Vector([0.0, 1.0])
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntVectorNode, "v2")
        assert loaded is not None
        assert abs(loaded.embedding[0]) < 1e-5
        assert abs(loaded.embedding[1] - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# GeoLocation
# ---------------------------------------------------------------------------


def test_geolocation_roundtrip(graph_driver: Any) -> None:
    munich = GeoLocation(latitude=48.137154, longitude=11.576124)
    with Session(graph_driver) as s:
        node = IntGeoNode(id="g1", location=munich)
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntGeoNode, "g1")
        assert loaded is not None
        loc = loaded.location
        assert isinstance(loc, GeoLocation)
        assert abs(loc.latitude - 48.137154) < 1e-3
        assert abs(loc.longitude - 11.576124) < 1e-3


@pytest.mark.requires_geo_update
def test_geolocation_update(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntGeoNode(
            id="g2", location=GeoLocation(latitude=51.507, longitude=-0.127)
        )
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntGeoNode, "g2")
        assert loaded is not None
        loaded.location = GeoLocation(latitude=48.137, longitude=11.576)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntGeoNode, "g2")
        assert loaded is not None
        assert abs(loaded.location.latitude - 48.137) < 1e-3


# ---------------------------------------------------------------------------
# Auto-converters: datetime and Enum (no explicit converter= on Field)
# ---------------------------------------------------------------------------


def test_auto_datetime_roundtrip(graph_driver: Any) -> None:
    ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
    with Session(graph_driver) as s:
        node = IntAutoNode(id="a1", status=IntStatus.ACTIVE, created_at=ts)
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntAutoNode, "a1")
        assert loaded is not None
        assert isinstance(loaded.created_at, datetime)
        assert loaded.created_at == ts


def test_auto_enum_roundtrip(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntAutoNode(
            id="a2",
            status=IntStatus.ARCHIVED,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntAutoNode, "a2")
        assert loaded is not None
        assert loaded.status is IntStatus.ARCHIVED


def test_auto_enum_update(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        node = IntAutoNode(
            id="a3",
            status=IntStatus.ACTIVE,
            created_at=datetime(2024, 3, 1, tzinfo=UTC),
        )
        s.add(node)
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntAutoNode, "a3")
        assert loaded is not None
        loaded.status = IntStatus.ARCHIVED
        s.commit()

    with Session(graph_driver) as s:
        loaded = s.get(IntAutoNode, "a3")
        assert loaded is not None
        assert loaded.status is IntStatus.ARCHIVED
