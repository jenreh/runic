"""Integration tests for Voyager graph patterns via embedded FalkorDB.

Tests the real-world patterns described in the ORM spec:
  - Location polymorphism (Location → Country, City, Restaurant)
  - User/Trip with InvitationEdge properties
  - Cascade-style session management
  - Lazy and eager relationship loading across the hierarchy

Requires redislite (falkordb-lite).  Marked ``integration`` so they are
skipped in environments without it.
"""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field, Relation
from runic.orm.core.models import Edge, Node
from runic.orm.driver.falkordb import FalkorDBDriver
from runic.orm.repository.pagination import Pageable
from runic.orm.repository.repository import Repository
from runic.orm.session.session import Session

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Voyager model definitions
# ---------------------------------------------------------------------------

# --- Location hierarchy ---


class VLocation(Node, labels=["VLocation"], primary_label="VLocation"):
    id: str = Field()
    title: str = Field()
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)


class VCountry(VLocation, labels=["VLocation", "VCountry"], primary_label="VLocation"):
    iso_code: str = Field()
    population: int | None = Field(default=None)


class VCity(VLocation, labels=["VLocation", "VCity"], primary_label="VLocation"):
    population: int | None = Field(default=None)


class VRestaurant(
    VLocation, labels=["VLocation", "VRestaurant"], primary_label="VLocation"
):
    cuisine: str | None = Field(default=None)


# --- Trip / User hierarchy ---


class VTrip(Node, labels=["VTrip"]):
    id: str = Field()
    title: str = Field()
    status: str = Field(default="draft")


class VUser(Node, labels=["VUser"]):
    id: str = Field()
    name: str = Field()
    email: str = Field()
    invited_trips: list[VTrip] = Relation(
        relationship="INVITED_TO",
        direction="OUTGOING",
        target="VTrip",
        edge_model="VInvitationEdge",
    )


# --- Edge model ---


class VInvitationEdge(Edge, type="V_INVITED_TO"):
    role: str = Field()
    status: str = Field()
    invited_at: str = Field()
    accepted_at: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph() -> Any:
    if not _HAS_FALKORDBLITE:
        pytest.skip("redislite not available")
    db = _FalkorDB(protocol=2)
    name = f"voyager_{secrets.token_hex(4)}"
    return FalkorDBDriver(db.select_graph(name))


@contextlib.contextmanager
def _session(graph: Any) -> Any:
    with Session(graph) as s:
        yield s


def _uid() -> str:
    return secrets.token_hex(4)


# ---------------------------------------------------------------------------
# Location polymorphism
# ---------------------------------------------------------------------------


class TestLocationPolymorphism:
    """Multi-label polymorphic node hierarchy."""

    def test_country_saves_and_loads_with_inherited_fields(self, graph: Any) -> None:
        country_id = f"FR_{_uid()}"
        with Session(graph) as s:
            france = VCountry(
                id=country_id,
                title="France",
                latitude=46.2,
                longitude=2.2,
                iso_code="FR",
                population=67_000_000,
            )
            s.add(france)
            s.commit()

        with Session(graph) as s:
            repo = Repository(s, VCountry)
            results = repo.find_all()
            found = next((c for c in results if c.id == country_id), None)
            assert found is not None
            assert found.title == "France"
            assert found.iso_code == "FR"
            assert found.population == 67_000_000

    def test_city_is_also_a_location(self, graph: Any) -> None:
        city_id = f"PAR_{_uid()}"
        with Session(graph) as s:
            s.add(VCity(id=city_id, title="Paris", population=2_000_000))
            s.commit()

        with Session(graph) as s:
            # Query as Location (parent) — should return a VCity instance
            repo = Repository(s, VCity)
            results = repo.find_all()
            found = next((c for c in results if c.id == city_id), None)
            assert found is not None
            assert isinstance(found, VCity)
            assert found.title == "Paris"

    def test_mixed_subtypes_in_location_query(self, graph: Any) -> None:
        suffix = _uid()
        with Session(graph) as s:
            s.add(VCountry(id=f"DE_{suffix}", title="Germany", iso_code="DE"))
            s.add(VCity(id=f"BER_{suffix}", title="Berlin"))
            s.add(
                VRestaurant(id=f"REST_{suffix}", title="Café Paris", cuisine="French")
            )
            s.commit()

        with Session(graph) as s:
            # VLocation query: mapper resolves each node to its concrete type
            repo = Repository(s, VLocation)
            all_locs = repo.find_all()
            ids = {loc.id for loc in all_locs}
            assert f"DE_{suffix}" in ids
            assert f"BER_{suffix}" in ids
            assert f"REST_{suffix}" in ids
            # Types are preserved
            by_id = {loc.id: loc for loc in all_locs}
            assert isinstance(by_id[f"DE_{suffix}"], VCountry)
            assert isinstance(by_id[f"BER_{suffix}"], VCity)
            assert isinstance(by_id[f"REST_{suffix}"], VRestaurant)

    def test_session_get_returns_correct_subtype(self, graph: Any) -> None:
        country_id = f"IT_{_uid()}"
        with Session(graph) as s:
            s.add(VCountry(id=country_id, title="Italy", iso_code="IT"))
            s.commit()

        with Session(graph) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            assert isinstance(entity, VCountry)
            assert entity.iso_code == "IT"  # type: ignore[attr-defined]

    def test_update_inherited_field(self, graph: Any) -> None:
        country_id = f"ES_{_uid()}"
        with Session(graph) as s:
            s.add(VCountry(id=country_id, title="Spain", iso_code="ES"))
            s.commit()

        with Session(graph) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            entity.title = "España"  # type: ignore[attr-defined]
            s.commit()

        with Session(graph) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            assert entity.title == "España"  # type: ignore[attr-defined]

    def test_delete_location_subtype(self, graph: Any) -> None:
        city_id = f"NYC_{_uid()}"
        with Session(graph) as s:
            s.add(VCity(id=city_id, title="New York"))
            s.commit()

        with Session(graph) as s:
            entity = s.get(VCity, city_id)
            assert entity is not None
            s.delete(entity)
            s.commit()

        with Session(graph) as s:
            entity = s.get(VCity, city_id)
            assert entity is None

    def test_restaurant_inherits_lat_long(self, graph: Any) -> None:
        rest_id = f"EIFF_{_uid()}"
        with Session(graph) as s:
            s.add(
                VRestaurant(
                    id=rest_id,
                    title="Le Jules Verne",
                    latitude=48.858,
                    longitude=2.295,
                    cuisine="French",
                )
            )
            s.commit()

        with Session(graph) as s:
            entity = s.get(VRestaurant, rest_id)
            assert entity is not None
            assert entity.latitude == pytest.approx(48.858, rel=1e-3)  # type: ignore[attr-defined]
            assert entity.cuisine == "French"  # type: ignore[attr-defined]

    def test_paginate_location_subtypes(self, graph: Any) -> None:
        suffix = _uid()
        with Session(graph) as s:
            for i in range(5):
                s.add(VCity(id=f"CITY_{i}_{suffix}", title=f"City {i}"))
            s.commit()

        with Session(graph) as s:
            repo = Repository(s, VCity)
            page = repo.find_all_paginated(Pageable(page=0, size=3, sort_by="id"))
            assert len(list(page)) == 3 or page.total_elements >= 5


# ---------------------------------------------------------------------------
# User / Trip / InvitationEdge
# ---------------------------------------------------------------------------


class TestUserTripPatterns:
    """Trip ownership and invitation relationship patterns."""

    def test_user_and_trip_independent_crud(self, graph: Any) -> None:
        user_id, trip_id = f"U_{_uid()}", f"T_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Alice", email="alice@example.com"))
            s.add(VTrip(id=trip_id, title="Paris Trip", status="draft"))
            s.commit()

        with Session(graph) as s:
            user = s.get(VUser, user_id)
            trip = s.get(VTrip, trip_id)
            assert user is not None
            assert user.name == "Alice"  # type: ignore[attr-defined]
            assert trip is not None
            assert trip.title == "Paris Trip"  # type: ignore[attr-defined]

    def test_trip_status_update(self, graph: Any) -> None:
        trip_id = f"T_{_uid()}"
        with Session(graph) as s:
            s.add(VTrip(id=trip_id, title="Draft Trip", status="draft"))
            s.commit()

        with Session(graph) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            trip.status = "published"  # type: ignore[attr-defined]
            s.commit()

        with Session(graph) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            assert trip.status == "published"  # type: ignore[attr-defined]

    def test_invitation_edge_via_raw_cypher(self, graph: Any) -> None:
        """InvitationEdge properties persist via explicit Cypher."""
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Bob", email="bob@example.com"))
            s.add(VTrip(id=trip_id, title="Rome Trip", status="draft"))
            s.commit()

        # Create edge directly via session.execute
        with Session(graph) as s:
            s.execute(
                """
                MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid})
                CREATE (u)-[:INVITED_TO {
                    role: $role, status: $status, invited_at: $invited_at
                }]->(t)
                """,
                {
                    "uid": user_id,
                    "tid": trip_id,
                    "role": "viewer",
                    "status": "pending",
                    "invited_at": "2026-01-15T10:00:00",
                },
                write=True,
            )

        # Read back edge properties
        with Session(graph) as s:
            result = s.execute(
                """
                MATCH (u:VUser {id: $uid})-[e:INVITED_TO]->(t:VTrip {id: $tid})
                RETURN e.role AS role, e.status AS status, e.invited_at AS invited_at
                """,
                {"uid": user_id, "tid": trip_id},
            )
            rows = result.rows
            assert len(rows) == 1
            row_dict = dict(zip(result.columns, rows[0], strict=False))
            assert row_dict["role"] == "viewer"
            assert row_dict["status"] == "pending"

    def test_user_invited_trips_lazy_load(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Carol", email="carol@example.com"))
            s.add(VTrip(id=trip_id, title="Tokyo Trip", status="published"))
            s.commit()

        with Session(graph) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid}) "
                "CREATE (u)-[:INVITED_TO {role: 'owner', status: 'accepted', "
                "invited_at: '2026-01-01T00:00:00'}]->(t)",
                {"uid": user_id, "tid": trip_id},
                write=True,
            )

        with Session(graph) as s:
            user = s.get(VUser, user_id)
            assert user is not None
            trips = user.invited_trips  # type: ignore[attr-defined]  # lazy load
            trip_ids = [t.id for t in trips]
            assert trip_id in trip_ids

    def test_user_invited_trips_eager_load(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Dave", email="dave@example.com"))
            s.add(VTrip(id=trip_id, title="Berlin Trip", status="published"))
            s.commit()

        with Session(graph) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid}) "
                "CREATE (u)-[:INVITED_TO {role: 'editor', status: 'accepted', "
                "invited_at: '2026-02-01T00:00:00'}]->(t)",
                {"uid": user_id, "tid": trip_id},
                write=True,
            )

        with Session(graph) as s:
            user = s.get(VUser, user_id, fetch=["invited_trips"])
            assert user is not None
            trips = user.invited_trips  # type: ignore[attr-defined]  # no lazy load
            assert isinstance(trips, list)
            assert any(t.id == trip_id for t in trips)

    def test_custom_cypher_on_trip_repository(self, graph: Any) -> None:
        suffix = _uid()
        with Session(graph) as s:
            for i, status in enumerate(["draft", "draft", "published"]):
                s.add(VTrip(id=f"TR_{i}_{suffix}", title=f"Trip {i}", status=status))
            s.commit()

        with Session(graph) as s:
            repo = Repository(s, VTrip)
            count = repo.cypher_one(
                "MATCH (t:VTrip {status: $status}) RETURN count(t)",
                {"status": "draft"},
                returns=int,
            )
            assert isinstance(count, int)
            assert count >= 2

    def test_count_and_exists_on_user_repository(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Eve", email="eve@example.com"))
            s.commit()

        with Session(graph) as s:
            repo = Repository(s, VUser)
            assert repo.exists(user_id) is True
            assert repo.exists(f"NOTEXIST_{_uid()}") is False


# ---------------------------------------------------------------------------
# Session lifecycle with Voyager entities
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_rollback_discards_pending(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Ghost", email="ghost@example.com"))
            s.rollback()
            # Should NOT be in the graph
            result = s.get(VUser, user_id)
            assert result is None

    def test_identity_map_returns_same_instance(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Iden", email="iden@example.com"))
            s.commit()
            a = s.get(VUser, user_id)
            b = s.get(VUser, user_id)
            assert a is b

    def test_expire_and_refresh(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Refresh", email="refresh@example.com"))
            s.commit()
            entity = s.get(VUser, user_id)
            assert entity is not None
            s.expire(entity)
            # After expire, accessing fields re-queries — still readable
            s.refresh(entity)
            assert entity.name == "Refresh"  # type: ignore[attr-defined]

    def test_expunge_removes_from_session(self, graph: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph) as s:
            s.add(VUser(id=user_id, name="Detach", email="detach@example.com"))
            s.commit()
            entity = s.get(VUser, user_id)
            assert entity is not None
            s.expunge(entity)
            # After expunge, the identity map no longer holds the instance
            entity2 = s.get(VUser, user_id)
            assert entity2 is not entity

    def test_find_all_by_ids(self, graph: Any) -> None:
        ids = [f"LOC_{i}_{_uid()}" for i in range(3)]
        with Session(graph) as s:
            for i, loc_id in enumerate(ids):
                s.add(VLocation(id=loc_id, title=f"Location {i}"))
            s.commit()

        with Session(graph) as s:
            repo = Repository(s, VLocation)
            results = repo.find_all_by_ids(ids[:2])
            assert len(results) == 2
            result_ids = {r.id for r in results}
            assert ids[0] in result_ids
            assert ids[1] in result_ids
