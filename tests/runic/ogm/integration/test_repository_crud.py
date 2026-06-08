"""Integration tests for Repository CRUD, identity map, and eager loading."""

from __future__ import annotations

from typing import Any

import pytest

from runic.ogm.core.descriptors import Field
from runic.ogm.core.models import Node
from runic.ogm.repository.repository import Repository
from runic.ogm.session.session import Session

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class CrudPerson(Node, labels=["CrudPerson"]):
    id: str = Field()
    name: str = Field()
    age: int | None = Field(default=None)


class CrudTag(Node, labels=["CrudTag"]):
    id: int | None = Field(default=None, generated=True)
    label: str = Field()


class CrudLocation(Node, labels=["CrudLocation"], primary_label="CrudLocation"):
    id: str = Field()
    title: str = Field()


class CrudCountry(
    CrudLocation,
    labels=["CrudLocation", "CrudCountry"],
    primary_label="CrudLocation",
):
    iso_code: str = Field(default=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_graph(graph_driver: Any) -> Any:
    """Graph pre-loaded with 5 CrudPerson nodes."""
    with Session(graph_driver) as s:
        for i in range(1, 6):
            s.add(CrudPerson(id=f"p{i}", name=f"Person {i}", age=20 + i))
    return graph_driver


# ---------------------------------------------------------------------------
# find_all
# ---------------------------------------------------------------------------


def test_find_all_returns_all_entities(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        all_people = repo.find_all()
    assert len(all_people) == 5


def test_find_all_empty_graph(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        repo = Repository(s, CrudPerson)
        assert repo.find_all() == []


def test_find_all_decodes_fields_correctly(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        people = repo.find_all()
    ids = {p.id for p in people}
    assert ids == {"p1", "p2", "p3", "p4", "p5"}


# ---------------------------------------------------------------------------
# find_all_by_ids
# ---------------------------------------------------------------------------


def test_find_all_by_ids_returns_matching_subset(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        subset = repo.find_all_by_ids(["p1", "p3", "p5"])
    assert len(subset) == 3
    assert {p.id for p in subset} == {"p1", "p3", "p5"}


def test_find_all_by_ids_empty_list(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        assert repo.find_all_by_ids([]) == []


def test_find_all_by_ids_unknown_ids_returns_empty(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        assert repo.find_all_by_ids(["unknown"]) == []


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


def test_count_returns_correct_number(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        assert repo.count() == 5


def test_count_returns_zero_for_empty_graph(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        repo = Repository(s, CrudPerson)
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


def test_exists_true_for_known_id(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        assert repo.exists("p1") is True


def test_exists_false_for_unknown_id(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CrudPerson)
        assert repo.exists("unknown") is False


# ---------------------------------------------------------------------------
# Identity map deduplication
# ---------------------------------------------------------------------------


def test_find_all_returns_same_instance_as_get(populated_graph: Any) -> None:
    """Entity loaded via session.get and find_all in same session must be the same instance."""
    with Session(populated_graph) as s:
        person_via_get = s.get(CrudPerson, "p1")
        repo = Repository(s, CrudPerson)
        all_people = repo.find_all()

    found = next(p for p in all_people if p.id == "p1")
    assert found is person_via_get


def test_find_all_by_ids_returns_same_instance_as_get(
    populated_graph: Any,
) -> None:
    with Session(populated_graph) as s:
        person_via_get = s.get(CrudPerson, "p2")
        repo = Repository(s, CrudPerson)
        by_ids = repo.find_all_by_ids(["p2"])

    assert len(by_ids) == 1
    assert by_ids[0] is person_via_get


# ---------------------------------------------------------------------------
# Polymorphic nodes
# ---------------------------------------------------------------------------


@pytest.mark.requires_multi_label
def test_find_all_polymorphic_base_returns_subtypes(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        s.add(CrudLocation(id="LOC1", title="Base Location"))
        s.add(CrudCountry(id="FR", title="France", iso_code="FR"))

    with Session(graph_driver) as s:
        repo = Repository(s, CrudLocation)
        all_locs = repo.find_all()

    assert len(all_locs) == 2
    classes = {type(loc).__name__ for loc in all_locs}
    assert "CrudLocation" in classes
    assert "CrudCountry" in classes


@pytest.mark.requires_multi_label
def test_find_all_subtype_returns_only_subtype(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        s.add(CrudLocation(id="LOC1", title="Base Location"))
        s.add(CrudCountry(id="FR", title="France", iso_code="FR"))

    with Session(graph_driver) as s:
        repo = Repository(s, CrudCountry)
        countries = repo.find_all()

    assert len(countries) == 1
    assert countries[0].id == "FR"
    assert isinstance(countries[0], CrudCountry)


# ---------------------------------------------------------------------------
# Generated IDs
# ---------------------------------------------------------------------------


def test_find_all_by_ids_generated_pk(graph_driver: Any) -> None:
    with Session(graph_driver) as s:
        tag = CrudTag(label="python")
        s.add(tag)
        s.commit()
        tag_id = tag.id

    with Session(graph_driver) as s:
        repo = Repository(s, CrudTag)
        result = repo.find_all_by_ids([tag_id])

    assert len(result) == 1
    assert result[0].label == "python"
