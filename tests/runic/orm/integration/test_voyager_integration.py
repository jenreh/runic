"""Canonical Voyager integration test — covers all ORM features end-to-end.

Domain:
  - Location polymorphism (VLocation → VCountry, VCity, VRestaurant)
  - User / Trip / InvitationEdge with INVITED_TO and LOCATED_IN relationships
  - Custom types: GeoLocation on VRestaurant, datetime/StrEnum on VTrip

Test classes:
  TestPolymorphism, TestSessionLifecycle, TestIdentityMap, TestRepositoryCrud,
  TestRelationshipLoading, TestRelationshipMutations, TestPagination,
  TestCustomTypes, TestSearch, TestDataOperations
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, Relation
from runic.orm.core.models import Edge, Node
from runic.orm.core.types import GeoLocation
from runic.orm.exceptions import DetachedEntityError
from runic.orm.repository.repository import Repository
from runic.orm.session.session import Session

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Voyager models
# ---------------------------------------------------------------------------


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
    geo: GeoLocation | None = Field(default=None)


class VTripStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class VTrip(Node, labels=["VTrip"]):
    id: str = Field()
    title: str = Field()
    status: VTripStatus = Field(default=VTripStatus.DRAFT)
    created_at: datetime | None = Field(default=None)


class VInvitationEdge(Edge, type="V_INVITED_TO"):
    role: str = Field()
    status: str = Field()
    invited_at: str = Field()
    accepted_at: str | None = Field(default=None)


class VUser(Node, labels=["VUser"]):
    id: str = Field()
    name: str = Field()
    email: str = Field()
    home: VCity | None = Relation(
        relationship="LOCATED_IN",
        direction="OUTGOING",
        target="VCity",
    )
    invited_trips: list[VTrip] = Relation(
        relationship="INVITED_TO",
        direction="OUTGOING",
        target="VTrip",
        edge_model="VInvitationEdge",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return secrets.token_hex(4)


# ---------------------------------------------------------------------------
# TestPolymorphism
# ---------------------------------------------------------------------------


@pytest.mark.requires_multi_label
class TestPolymorphism:
    """Multi-label polymorphic Location hierarchy."""

    def test_country_saves_and_loads_with_inherited_fields(
        self, graph_driver: Any
    ) -> None:
        country_id = f"FR_{_uid()}"
        with Session(graph_driver) as s:
            s.add(
                VCountry(
                    id=country_id,
                    title="France",
                    latitude=46.2,
                    longitude=2.2,
                    iso_code="FR",
                    population=67_000_000,
                )
            )
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCountry)
            results = repo.find_all()
            found = next((c for c in results if c.id == country_id), None)
            assert found is not None
            assert found.title == "France"
            assert found.iso_code == "FR"
            assert found.population == 67_000_000

    def test_city_is_also_a_location(self, graph_driver: Any) -> None:
        city_id = f"PAR_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Paris", population=2_000_000))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            results = repo.find_all()
            found = next((c for c in results if c.id == city_id), None)
            assert found is not None
            assert isinstance(found, VCity)
            assert found.title == "Paris"

    def test_mixed_subtypes_in_location_query(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            s.add(VCountry(id=f"DE_{suffix}", title="Germany", iso_code="DE"))
            s.add(VCity(id=f"BER_{suffix}", title="Berlin"))
            s.add(
                VRestaurant(id=f"REST_{suffix}", title="Café Berlin", cuisine="German")
            )
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VLocation)
            all_locs = repo.find_all()
            by_id = {loc.id: loc for loc in all_locs}
            assert f"DE_{suffix}" in by_id
            assert f"BER_{suffix}" in by_id
            assert f"REST_{suffix}" in by_id
            assert isinstance(by_id[f"DE_{suffix}"], VCountry)
            assert isinstance(by_id[f"BER_{suffix}"], VCity)
            assert isinstance(by_id[f"REST_{suffix}"], VRestaurant)

    def test_session_get_returns_correct_subtype(self, graph_driver: Any) -> None:
        country_id = f"IT_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCountry(id=country_id, title="Italy", iso_code="IT"))
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            assert isinstance(entity, VCountry)
            assert entity.iso_code == "IT"  # type: ignore[attr-defined]

    def test_update_inherited_field(self, graph_driver: Any) -> None:
        country_id = f"ES_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCountry(id=country_id, title="Spain", iso_code="ES"))
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            entity.title = "España"  # type: ignore[attr-defined]
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VCountry, country_id)
            assert entity is not None
            assert entity.title == "España"  # type: ignore[attr-defined]

    def test_delete_location_subtype(self, graph_driver: Any) -> None:
        city_id = f"NYC_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="New York"))
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VCity, city_id)
            assert entity is not None
            s.delete(entity)
            s.commit()

        with Session(graph_driver) as s:
            assert s.get(VCity, city_id) is None

    def test_restaurant_inherits_lat_long(self, graph_driver: Any) -> None:
        rest_id = f"EIFF_{_uid()}"
        with Session(graph_driver) as s:
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

        with Session(graph_driver) as s:
            entity = s.get(VRestaurant, rest_id)
            assert entity is not None
            assert entity.latitude == pytest.approx(48.858, rel=1e-3)  # type: ignore[attr-defined]
            assert entity.cuisine == "French"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestSessionLifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_rollback_discards_pending(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Ghost", email="ghost@example.com"))
            s.rollback()
            assert s.get(VUser, user_id) is None

    def test_context_manager_rolls_back_on_error(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        try:
            with Session(graph_driver) as s:
                s.add(VUser(id=user_id, name="Err", email="err@example.com"))
                raise RuntimeError("simulated failure")
        except RuntimeError:
            pass

        with Session(graph_driver) as s:
            assert s.get(VUser, user_id) is None

    def test_expire_and_refresh(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Refresh", email="refresh@example.com"))
            s.commit()
            entity = s.get(VUser, user_id)
            assert entity is not None
            s.expire(entity)
            s.refresh(entity)
            assert entity.name == "Refresh"  # type: ignore[attr-defined]

    def test_refresh_picks_up_external_change(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Before", email="b@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VUser, user_id)
            assert entity is not None
            s.execute(
                "MATCH (n:VUser {id: $id}) SET n.name = $n",
                {"id": user_id, "n": "After"},
                write=True,
            )
            s.refresh(entity)
            assert entity.name == "After"  # type: ignore[attr-defined]

    def test_expunge_removes_from_session(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Detach", email="detach@example.com"))
            s.commit()
            entity = s.get(VUser, user_id)
            assert entity is not None
            s.expunge(entity)
            entity2 = s.get(VUser, user_id)
            assert entity2 is not entity

    @pytest.mark.requires_multi_label
    def test_detached_entity_lazy_access_raises(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Berlin"))
            s.add(VUser(id=user_id, name="Detached", email="d@example.com"))
            s.commit()

        user_entity: VUser | None = None
        with Session(graph_driver) as s:
            user_entity = s.get(VUser, user_id)
            assert user_entity is not None
            s.expunge(user_entity)

        with pytest.raises(DetachedEntityError):
            _ = user_entity.home  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestIdentityMap
# ---------------------------------------------------------------------------


class TestIdentityMap:
    def test_same_instance_returned_twice(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Iden", email="iden@example.com"))
            s.commit()
            a = s.get(VUser, user_id)
            b = s.get(VUser, user_id)
            assert a is b

    def test_find_all_same_instance_as_get(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="IdenGet", email="ig@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            via_get = s.get(VUser, user_id)
            repo = Repository(s, VUser)
            all_users = repo.find_all()
            via_find = next(u for u in all_users if u.id == user_id)
            assert via_get is via_find

    def test_find_all_by_ids_same_instance_as_get(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="IdenById", email="ibi@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            via_get = s.get(VUser, user_id)
            repo = Repository(s, VUser)
            by_ids = repo.find_all_by_ids([user_id])
            assert by_ids[0] is via_get


# ---------------------------------------------------------------------------
# TestRepositoryCrud
# ---------------------------------------------------------------------------


class TestRepositoryCrud:
    @pytest.mark.requires_multi_label
    def test_count_returns_correct_number(self, graph_driver: Any) -> None:
        with Session(graph_driver) as s:
            for i in range(3):
                s.add(VCity(id=f"CITY_{i}_{_uid()}", title=f"City {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            assert repo.count() >= 3

    @pytest.mark.requires_multi_label
    def test_exists_true_and_false(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Munich"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            assert repo.exists(city_id) is True
            assert repo.exists(f"NOTEXIST_{_uid()}") is False

    def test_custom_cypher_count(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            for i, status in enumerate(
                [VTripStatus.DRAFT, VTripStatus.DRAFT, VTripStatus.PUBLISHED]
            ):
                s.add(VTrip(id=f"TR_{i}_{suffix}", title=f"Trip {i}", status=status))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VTrip)
            count = repo.cypher_one(
                "MATCH (t:VTrip {status: $status}) RETURN count(t)",
                {"status": "draft"},
                returns=int,
            )
            assert isinstance(count, int)
            assert count >= 2

    def test_user_and_trip_independent_crud(self, graph_driver: Any) -> None:
        user_id, trip_id = f"U_{_uid()}", f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Alice", email="alice@example.com"))
            s.add(VTrip(id=trip_id, title="Paris Trip"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            trip = s.get(VTrip, trip_id)
            assert user is not None
            assert user.name == "Alice"  # type: ignore[attr-defined]
            assert trip is not None
            assert trip.title == "Paris Trip"  # type: ignore[attr-defined]

    def test_find_all_by_ids_subset(self, graph_driver: Any) -> None:
        ids = [f"LOC_{i}_{_uid()}" for i in range(3)]
        with Session(graph_driver) as s:
            for i, loc_id in enumerate(ids):
                s.add(VLocation(id=loc_id, title=f"Location {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VLocation)
            results = repo.find_all_by_ids(ids[:2])
            assert len(results) == 2
            assert {r.id for r in results} == set(ids[:2])

    def test_find_all_by_ids_empty_list(self, graph_driver: Any) -> None:
        with Session(graph_driver) as s:
            repo = Repository(s, VLocation)
            assert repo.find_all_by_ids([]) == []


# ---------------------------------------------------------------------------
# TestRelationshipLoading
# ---------------------------------------------------------------------------


class TestRelationshipLoading:
    @pytest.mark.requires_multi_label
    @pytest.mark.requires_multi_label
    def test_user_home_lazy_load(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Vienna"))
            s.add(VUser(id=user_id, name="Anna", email="anna@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (c:VCity {id: $cid}) "
                "CREATE (u)-[:LOCATED_IN]->(c)",
                {"uid": user_id, "cid": city_id},
                write=True,
            )

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            assert user is not None
            assert user.__dict__["home"] is _NOT_LOADED
            home = user.home  # type: ignore[attr-defined]
            assert home is not None
            assert home.id == city_id
            assert user.__dict__["home"] is home  # cached

    def test_user_home_lazy_load_none_when_no_rel(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Solo", email="solo@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            assert user is not None
            assert user.home is None  # type: ignore[attr-defined]
            assert user.__dict__["home"] is None  # cached

    def test_invited_trips_lazy_load_collection(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Carol", email="carol@example.com"))
            s.add(VTrip(id=trip_id, title="Tokyo Trip"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid}) "
                "CREATE (u)-[:INVITED_TO {role: 'owner', status: 'accepted', "
                "invited_at: '2026-01-01T00:00:00'}]->(t)",
                {"uid": user_id, "tid": trip_id},
                write=True,
            )

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            assert user is not None
            trips = user.invited_trips  # type: ignore[attr-defined]
            assert any(t.id == trip_id for t in trips)

    @pytest.mark.requires_multi_label
    def test_eager_fetch_home(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Amsterdam"))
            s.add(VUser(id=user_id, name="Dirk", email="dirk@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (c:VCity {id: $cid}) "
                "CREATE (u)-[:LOCATED_IN]->(c)",
                {"uid": user_id, "cid": city_id},
                write=True,
            )

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id, fetch=["home"])
            assert user is not None
            home = user.__dict__["home"]  # pre-loaded, no lazy trigger
            assert home is not None
            assert home.id == city_id

    def test_eager_fetch_invited_trips(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Dave", email="dave@example.com"))
            s.add(VTrip(id=trip_id, title="Berlin Trip"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid}) "
                "CREATE (u)-[:INVITED_TO {role: 'editor', status: 'accepted', "
                "invited_at: '2026-02-01T00:00:00'}]->(t)",
                {"uid": user_id, "tid": trip_id},
                write=True,
            )

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id, fetch=["invited_trips"])
            assert user is not None
            trips = user.__dict__["invited_trips"]
            assert isinstance(trips, list)
            assert any(t.id == trip_id for t in trips)

    @pytest.mark.requires_multi_label
    def test_lazy_loaded_entity_has_session_for_traversal(
        self, graph_driver: Any
    ) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Prague"))
            s.add(VUser(id=user_id, name="Emil", email="emil@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (c:VCity {id: $cid}) "
                "CREATE (u)-[:LOCATED_IN]->(c)",
                {"uid": user_id, "cid": city_id},
                write=True,
            )

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            assert user is not None
            home = user.home  # type: ignore[attr-defined]
            assert home is not None
            assert "_session" in home.__dict__


# ---------------------------------------------------------------------------
# TestRelationshipMutations
# ---------------------------------------------------------------------------


@pytest.mark.requires_multi_label
class TestRelationshipMutations:
    def test_relate_creates_located_in(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Warsaw"))
            s.add(VUser(id=user_id, name="Fela", email="fela@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            s.relate(user, "home", city)

        result = graph_driver.execute("MATCH ()-[r:LOCATED_IN]->() RETURN count(r)", {})
        assert result.rows[0][0] >= 1

    def test_relate_is_idempotent(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Oslo"))
            s.add(VUser(id=user_id, name="Gunnar", email="g@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            s.relate(user, "home", city)
            s.relate(user, "home", city)  # duplicate — MERGE

        result = graph_driver.execute(
            "MATCH (:VUser {id: $uid})-[r:LOCATED_IN]->() RETURN count(r)",
            {"uid": user_id},
        )
        assert result.rows[0][0] == 1

    def test_relate_invalidates_field_cache(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Copenhagen"))
            s.add(VUser(id=user_id, name="Helge", email="h@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            user.__dict__["home"] = city  # simulate cached
            s.relate(user, "home", city)
            assert user.__dict__["home"] is _NOT_LOADED

    def test_unrelate_removes_located_in(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Stockholm"))
            s.add(VUser(id=user_id, name="Ingrid", email="i@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            s.relate(user, "home", city)

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            s.unrelate(user, "home", city)

        result = graph_driver.execute(
            "MATCH (:VUser {id: $uid})-[r:LOCATED_IN]->() RETURN count(r)",
            {"uid": user_id},
        )
        assert result.rows[0][0] == 0

    def test_unrelate_noop_when_no_relationship(self, graph_driver: Any) -> None:
        city_id = f"C_{_uid()}"
        user_id = f"U_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Helsinki"))
            s.add(VUser(id=user_id, name="Jussi", email="j@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            user = s.get(VUser, user_id)
            city = s.get(VCity, city_id)
            assert user is not None
            assert city is not None
            s.unrelate(user, "home", city)  # must not raise


# ---------------------------------------------------------------------------
# TestPagination
# ---------------------------------------------------------------------------


@pytest.mark.requires_multi_label
class TestPagination:
    def test_find_all_with_limit_returns_correct_subset(
        self, graph_driver: Any
    ) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            for i in range(6):
                s.add(VCity(id=f"P_CITY_{i}_{suffix}", title=f"PCity {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            items = repo.find_all(limit=4)
        assert len(items) == 4

    def test_find_all_limit_respected(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            for i in range(6):
                s.add(VCity(id=f"PS_CITY_{i}_{suffix}", title=f"PSCity {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            items = repo.find_all(limit=3)
        assert len(items) == 3

    def test_find_all_skip_produces_different_results(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            for i in range(5):
                s.add(VCity(id=f"PN_CITY_{i}_{suffix}", title=f"PNCity {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCity)
            first = repo.find_all(skip=0, limit=2)
            second = repo.find_all(skip=2, limit=2)
        assert len(first) == 2
        assert len(second) == 2


# ---------------------------------------------------------------------------
# TestCustomTypes
# ---------------------------------------------------------------------------


class TestCustomTypes:
    @pytest.mark.requires_multi_label
    def test_geolocation_roundtrip_on_restaurant(self, graph_driver: Any) -> None:
        rest_id = f"R_{_uid()}"
        munich = GeoLocation(latitude=48.137, longitude=11.576)
        with Session(graph_driver) as s:
            s.add(
                VRestaurant(
                    id=rest_id,
                    title="Hofbräuhaus",
                    cuisine="Bavarian",
                    geo=munich,
                )
            )
            s.commit()

        with Session(graph_driver) as s:
            entity = s.get(VRestaurant, rest_id)
            assert entity is not None
            loc = entity.geo  # type: ignore[attr-defined]
            assert isinstance(loc, GeoLocation)
            assert abs(loc.latitude - 48.137) < 1e-3
            assert abs(loc.longitude - 11.576) < 1e-3

    def test_enum_status_roundtrip_on_trip(self, graph_driver: Any) -> None:
        trip_id = f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(
                VTrip(
                    id=trip_id,
                    title="Archived Trip",
                    status=VTripStatus.ARCHIVED,
                )
            )
            s.commit()

        with Session(graph_driver) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            assert trip.status is VTripStatus.ARCHIVED  # type: ignore[attr-defined]

    def test_enum_status_update(self, graph_driver: Any) -> None:
        trip_id = f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VTrip(id=trip_id, title="My Trip", status=VTripStatus.DRAFT))
            s.commit()

        with Session(graph_driver) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            trip.status = VTripStatus.PUBLISHED  # type: ignore[attr-defined]
            s.commit()

        with Session(graph_driver) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            assert trip.status is VTripStatus.PUBLISHED  # type: ignore[attr-defined]

    def test_datetime_roundtrip_on_trip(self, graph_driver: Any) -> None:
        trip_id = f"T_{_uid()}"
        ts = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        with Session(graph_driver) as s:
            s.add(VTrip(id=trip_id, title="Timestamped Trip", created_at=ts))
            s.commit()

        with Session(graph_driver) as s:
            trip = s.get(VTrip, trip_id)
            assert trip is not None
            assert isinstance(trip.created_at, datetime)  # type: ignore[attr-defined]
            assert trip.created_at == ts  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TestSearch
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.requires_multi_label
    def test_cypher_property_filter(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            s.add(VCountry(id=f"DE_{suffix}", title="Germany", iso_code="DE"))
            s.add(VCountry(id=f"AT_{suffix}", title="Austria", iso_code="AT"))
            s.add(VCountry(id=f"CH_{suffix}", title="Switzerland", iso_code="CH"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VCountry)
            count = repo.cypher_one(
                "MATCH (c:VCountry {iso_code: $code}) RETURN count(c)",
                {"code": "DE"},
                returns=int,
            )
            assert isinstance(count, int)
            assert count >= 1

    def test_find_all_by_ids_for_search_result_enrichment(
        self, graph_driver: Any
    ) -> None:
        suffix = _uid()
        ids = [f"LOC_S_{i}_{suffix}" for i in range(4)]
        with Session(graph_driver) as s:
            for i, loc_id in enumerate(ids):
                s.add(VLocation(id=loc_id, title=f"SearchLoc {i}"))
            s.commit()

        with Session(graph_driver) as s:
            repo = Repository(s, VLocation)
            results = repo.find_all_by_ids(ids[1:3])
        assert len(results) == 2
        found_ids = {r.id for r in results}
        assert ids[1] in found_ids
        assert ids[2] in found_ids

    def test_cypher_raw_search_with_session_execute(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            s.add(VUser(id=f"U_S1_{suffix}", name="Zara", email="z@example.com"))
            s.add(VUser(id=f"U_S2_{suffix}", name="Zayn", email="zy@example.com"))
            s.add(VUser(id=f"U_S3_{suffix}", name="John", email="jo@example.com"))
            s.commit()

        with Session(graph_driver) as s:
            result = s.execute(
                "MATCH (u:VUser) WHERE u.name STARTS WITH 'Za' RETURN u.name",
                {},
            )
        assert len(result.rows) >= 2


# ---------------------------------------------------------------------------
# TestDataOperations
# ---------------------------------------------------------------------------


class TestDataOperations:
    @pytest.mark.requires_multi_label
    def test_create_via_raw_cypher_readable_via_orm(self, graph_driver: Any) -> None:
        city_id = f"RAW_C_{_uid()}"
        graph_driver.execute(
            "CREATE (:VCity:VLocation {id: $id, title: $t})",
            {"id": city_id, "t": "Raw City"},
        )

        with Session(graph_driver) as s:
            city = s.get(VCity, city_id)
            assert city is not None
            assert city.title == "Raw City"  # type: ignore[attr-defined]

    @pytest.mark.requires_multi_label
    def test_update_via_raw_cypher_then_refresh(self, graph_driver: Any) -> None:
        city_id = f"UPD_C_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VCity(id=city_id, title="Before"))
            s.commit()

        with Session(graph_driver) as s:
            city = s.get(VCity, city_id)
            assert city is not None
            s.execute(
                "MATCH (n:VCity {id: $id}) SET n.title = $t",
                {"id": city_id, "t": "After"},
                write=True,
            )
            s.refresh(city)
            assert city.title == "After"  # type: ignore[attr-defined]

    def test_invitation_edge_properties_via_raw_cypher(self, graph_driver: Any) -> None:
        user_id = f"U_{_uid()}"
        trip_id = f"T_{_uid()}"
        with Session(graph_driver) as s:
            s.add(VUser(id=user_id, name="Bob", email="bob@example.com"))
            s.add(VTrip(id=trip_id, title="Rome Trip"))
            s.commit()

        with Session(graph_driver) as s:
            s.execute(
                "MATCH (u:VUser {id: $uid}), (t:VTrip {id: $tid}) "
                "CREATE (u)-[:INVITED_TO {role: $role, status: $status, "
                "invited_at: $ia}]->(t)",
                {
                    "uid": user_id,
                    "tid": trip_id,
                    "role": "viewer",
                    "status": "pending",
                    "ia": "2026-01-15T10:00:00",
                },
                write=True,
            )

        with Session(graph_driver) as s:
            result = s.execute(
                "MATCH (:VUser {id: $uid})-[e:INVITED_TO]->(:VTrip {id: $tid}) "
                "RETURN e.role AS role, e.status AS status",
                {"uid": user_id, "tid": trip_id},
            )
            assert len(result.rows) == 1
            row_dict = dict(zip(result.columns, result.rows[0], strict=False))
            assert row_dict["role"] == "viewer"
            assert row_dict["status"] == "pending"

    def test_aggregate_count_via_raw_cypher(self, graph_driver: Any) -> None:
        suffix = _uid()
        with Session(graph_driver) as s:
            for i in range(4):
                s.add(VTrip(id=f"AGG_T_{i}_{suffix}", title=f"Agg Trip {i}"))
            s.commit()

        with Session(graph_driver) as s:
            result = s.execute(
                "MATCH (t:VTrip) WHERE t.id STARTS WITH $prefix RETURN count(t)",
                {"prefix": "AGG_T_"},
            )
        assert result.rows[0][0] >= 4
