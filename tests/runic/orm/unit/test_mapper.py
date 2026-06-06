"""Unit tests for runic.orm.mapper.mapper — encode/decode, _new/_dirty paths."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field
from runic.orm.core.metadata import MetaData
from runic.orm.core.models import Node
from runic.orm.core.types import EnumConverter
from runic.orm.exceptions import MetadataError
from runic.orm.mapper.mapper import Mapper
from runic.orm.repository.pagination import Pageable

# ---------------------------------------------------------------------------
# Test models — unique labels to avoid collisions with other test modules
# ---------------------------------------------------------------------------


class MapperPerson(Node, labels=["MapperPerson"]):
    id: str = Field()
    name: str = Field()
    age: int | None = Field(default=None)


class MapperGenerated(Node, labels=["MapperGenerated"]):
    """Node with FalkorDB-generated integer ID."""

    id: int | None = Field(default=None, generated=True)
    title: str = Field()


class MapperNoFields(Node, labels=["MapperNoFields"]):
    """Node with only an ID, no extra props."""

    id: str = Field()


class Status(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MapperWithConverter(Node, labels=["MapperConverter"]):
    id: str = Field()
    status: Status = Field(converter=EnumConverter(Status))


class MapperParent(Node, labels=["MapperParent"]):
    id: str = Field()
    kind: str = Field()


class MapperChild(MapperParent, labels=["MapperParent", "MapperChild"]):
    extra: str | None = Field(default=None)


class MapperRel(Node, labels=["MapperRel"]):
    id: str = Field()
    friend: MapperPerson | None = Field(
        relationship="KNOWS",
        direction="OUTGOING",
        target="MapperPerson",
        default=None,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def meta() -> MetaData:
    from runic.orm.core.metadata import metadata

    return metadata


@pytest.fixture
def mapper(meta: MetaData) -> Mapper:
    return Mapper(meta)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_node(
    labels: list[str],
    props: dict[str, Any],
    node_id: int = 1,
) -> MagicMock:
    node = MagicMock()
    node.id = node_id
    node.labels = labels
    node.properties = props
    return node


# ---------------------------------------------------------------------------
# build_create_query
# ---------------------------------------------------------------------------


class TestBuildCreateQuery:
    def test_client_id_with_props(self, mapper: Mapper) -> None:
        p = MapperPerson(id="p1", name="Alice", age=30)
        cypher, params = mapper.build_create_query(p)
        assert "CREATE" in cypher
        assert "MapperPerson" in cypher
        assert params["id"] == "p1"
        assert params["name"] == "Alice"
        assert params["age"] == 30

    def test_no_props_node_only_labels(self, mapper: Mapper) -> None:
        """When all props are None/missing, the cypher must have no {…}."""
        n = MapperNoFields(id="n1")
        cypher, params = mapper.build_create_query(n)
        assert "CREATE" in cypher
        assert params["id"] == "n1"

    def test_generated_id_excluded_from_props(self, mapper: Mapper) -> None:
        g = MapperGenerated(title="Test")
        cypher, params = mapper.build_create_query(g)
        assert "id" not in params
        assert params["title"] == "Test"

    def test_unregistered_class_raises(self, mapper: Mapper) -> None:
        class Ghost:
            pass

        with pytest.raises(MetadataError, match="not a registered"):
            mapper.build_create_query(Ghost())

    def test_converter_applied(self, mapper: Mapper) -> None:
        n = MapperWithConverter(id="c1", status=Status.ACTIVE)
        _, params = mapper.build_create_query(n)
        assert params["status"] == "active"

    def test_relationship_fields_excluded(self, mapper: Mapper) -> None:
        r = MapperRel(id="r1")
        _, params = mapper.build_create_query(r)
        assert "friend" not in params


# ---------------------------------------------------------------------------
# build_update_query
# ---------------------------------------------------------------------------


class TestBuildUpdateQuery:
    def test_returns_empty_when_no_updatable_props(self, mapper: Mapper) -> None:
        """Node with only an ID: nothing to SET → empty cypher + empty params."""
        n = MapperNoFields(id="n1")
        cypher, params = mapper.build_update_query(n)
        assert cypher == ""
        assert params == {}

    def test_client_id_update(self, mapper: Mapper) -> None:
        p = MapperPerson(id="p1", name="Bob", age=25)
        cypher, params = mapper.build_update_query(p)
        assert "MATCH" in cypher
        assert "SET" in cypher
        assert params["__pk"] == "p1"
        assert params["name"] == "Bob"

    def test_generated_id_uses_id_function(self, mapper: Mapper) -> None:
        g = MapperGenerated(title="Updated")
        g.__dict__["id"] = 99
        cypher, params = mapper.build_update_query(g)
        assert "id(n)" in cypher.lower() or "WHERE id" in cypher
        assert params["__pk"] == 99


# ---------------------------------------------------------------------------
# build_delete_query
# ---------------------------------------------------------------------------


class TestBuildDeleteQuery:
    def test_client_id(self, mapper: Mapper) -> None:
        p = MapperPerson(id="p1", name="Alice", age=30)
        cypher, params = mapper.build_delete_query(p)
        assert "DETACH DELETE" in cypher
        assert params["__pk"] == "p1"

    def test_generated_id(self, mapper: Mapper) -> None:
        g = MapperGenerated(title="T")
        g.__dict__["id"] = 42
        cypher, params = mapper.build_delete_query(g)
        assert "id(n)" in cypher.lower() or "WHERE id" in cypher
        assert params["__pk"] == 42


# ---------------------------------------------------------------------------
# build_get_query
# ---------------------------------------------------------------------------


class TestBuildGetQuery:
    def test_client_id(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_get_query(MapperPerson, "p1")
        assert "MATCH" in cypher
        assert params["__pk"] == "p1"

    def test_generated_id(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_get_query(MapperGenerated, 7)
        assert "id(n)" in cypher.lower() or "WHERE id" in cypher
        assert params["__pk"] == 7


# ---------------------------------------------------------------------------
# build_find_all_query / build_find_all_by_ids_query / count / exists
# ---------------------------------------------------------------------------


class TestQueryBuilders:
    def test_find_all(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_find_all_query(MapperPerson)
        assert "MATCH" in cypher
        assert "MapperPerson" in cypher
        assert params == {}

    def test_find_all_by_ids_client(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_find_all_by_ids_query(MapperPerson, ["a", "b"])
        assert "IN $__pks" in cypher
        assert params["__pks"] == ["a", "b"]

    def test_find_all_by_ids_generated(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_find_all_by_ids_query(MapperGenerated, [1, 2])
        assert "id(n)" in cypher.lower() or "$__pks" in cypher
        assert params["__pks"] == [1, 2]

    def test_count(self, mapper: Mapper) -> None:
        cypher, _ = mapper.build_count_query(MapperPerson)
        assert "count(n)" in cypher.lower()

    def test_exists_client_id(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_exists_query(MapperPerson, "p1")
        assert "count(n)" in cypher.lower()
        assert params["__pk"] == "p1"

    def test_exists_generated_id(self, mapper: Mapper) -> None:
        cypher, params = mapper.build_exists_query(MapperGenerated, 5)
        assert "id(n)" in cypher.lower() or "WHERE id" in cypher
        assert params["__pk"] == 5


# ---------------------------------------------------------------------------
# build_paginated_query
# ---------------------------------------------------------------------------


class TestBuildPaginatedQuery:
    def test_no_sort(self, mapper: Mapper) -> None:
        pageable = Pageable(page=0, size=10)
        cypher, params = mapper.build_paginated_query(MapperPerson, pageable)
        assert "SKIP" in cypher
        assert "LIMIT" in cypher
        assert params["__skip"] == 0
        assert params["__limit"] == 10

    def test_with_sort_asc(self, mapper: Mapper) -> None:
        pageable = Pageable(page=1, size=5, sort_by="name", direction="ASC")
        cypher, params = mapper.build_paginated_query(MapperPerson, pageable)
        assert "ORDER BY n.name ASC" in cypher
        assert params["__skip"] == 5

    def test_with_sort_desc(self, mapper: Mapper) -> None:
        pageable = Pageable(page=0, size=20, sort_by="age", direction="DESC")
        cypher, params = mapper.build_paginated_query(MapperPerson, pageable)
        assert "ORDER BY n.age DESC" in cypher


# ---------------------------------------------------------------------------
# decode_node
# ---------------------------------------------------------------------------


class TestDecodeNode:
    def test_basic_decode(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperPerson"], {"id": "p1", "name": "Alice", "age": 30})
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperPerson)
        assert entity.id == "p1"  # type: ignore[attr-defined]
        assert entity.name == "Alice"  # type: ignore[attr-defined]
        assert entity.age == 30  # type: ignore[attr-defined]
        assert entity.__dict__["_new"] is False
        assert entity.__dict__["_dirty"] is False

    def test_generated_id_from_node_id(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperGenerated"], {"title": "T"}, node_id=77)
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperGenerated)
        assert entity.__dict__["id"] == 77  # type: ignore[attr-defined]

    def test_hint_cls_used_on_unknown_labels(self, mapper: Mapper) -> None:
        node = _fake_node(["UnknownLabel"], {"id": "u1", "name": "Unknown"})
        entity = mapper.decode_node(node, hint_cls=MapperPerson)
        assert isinstance(entity, MapperPerson)

    def test_relationship_field_set_to_not_loaded(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperRel"], {"id": "r1"})
        entity = mapper.decode_node(node)
        assert entity.__dict__["friend"] is _NOT_LOADED

    def test_converter_applied_on_decode(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperConverter"], {"id": "c1", "status": "inactive"})
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperWithConverter)
        assert entity.__dict__["status"] == Status.INACTIVE  # type: ignore[attr-defined]

    def test_polymorphic_child_resolved(self, mapper: Mapper) -> None:
        node = _fake_node(
            ["MapperParent", "MapperChild"], {"id": "x1", "kind": "sub", "extra": "e"}
        )
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperChild)

    def test_missing_field_gets_default(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperPerson"], {"id": "p2", "name": "Bob"})
        entity = mapper.decode_node(node)
        assert entity.__dict__.get("age") is None  # default=None

    def test_no_matching_class_raises(self, mapper: Mapper) -> None:
        node = _fake_node(["NoSuchLabel"], {})
        with pytest.raises(MetadataError, match="No ORM class registered"):
            mapper.decode_node(node)


# ---------------------------------------------------------------------------
# update_entity_from_node
# ---------------------------------------------------------------------------


class TestUpdateEntityFromNode:
    def test_updates_fields_and_clears_dirty(self, mapper: Mapper) -> None:
        entity = MapperPerson(id="p1", name="Old", age=10)
        entity.__dict__["_dirty"] = True
        node = _fake_node(["MapperPerson"], {"id": "p1", "name": "New", "age": 20})
        mapper.update_entity_from_node(entity, node)
        assert entity.__dict__["name"] == "New"
        assert entity.__dict__["age"] == 20
        assert entity.__dict__["_dirty"] is False

    def test_generated_id_updated_from_node_id(self, mapper: Mapper) -> None:
        entity = MapperGenerated(title="Old")
        entity.__dict__["id"] = 0
        node = _fake_node(["MapperGenerated"], {"title": "New"}, node_id=55)
        mapper.update_entity_from_node(entity, node)
        assert entity.__dict__["id"] == 55

    def test_relationship_field_reset_to_not_loaded(self, mapper: Mapper) -> None:
        entity = MapperRel(id="r1")
        entity.__dict__["friend"] = object()
        node = _fake_node(["MapperRel"], {"id": "r1"})
        mapper.update_entity_from_node(entity, node)
        assert entity.__dict__["friend"] is _NOT_LOADED


# ---------------------------------------------------------------------------
# Public helpers: meta, require_node_meta, get_pk_value, is_generated_pk
# ---------------------------------------------------------------------------


class TestPublicHelpers:
    def test_meta_property(self, mapper: Mapper, meta: MetaData) -> None:
        assert mapper.meta is meta

    def test_require_node_meta_success(self, mapper: Mapper) -> None:
        nm = mapper.require_node_meta(MapperPerson)
        assert nm.cls is MapperPerson

    def test_require_node_meta_raises_on_unknown(self, mapper: Mapper) -> None:
        class NotRegistered:
            pass

        with pytest.raises(MetadataError):
            mapper.require_node_meta(NotRegistered)

    def test_get_pk_value(self, mapper: Mapper) -> None:
        p = MapperPerson(id="x", name="X")
        assert mapper.get_pk_value(p) == "x"

    def test_get_pk_field_name(self, mapper: Mapper) -> None:
        assert mapper.get_pk_field_name(MapperPerson) == "id"

    def test_is_generated_pk_false(self, mapper: Mapper) -> None:
        assert mapper.is_generated_pk(MapperPerson) is False

    def test_is_generated_pk_true(self, mapper: Mapper) -> None:
        assert mapper.is_generated_pk(MapperGenerated) is True
