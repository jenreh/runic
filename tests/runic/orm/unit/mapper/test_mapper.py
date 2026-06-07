"""Unit tests for runic.orm.mapper.mapper — encode/decode, _new/_dirty paths."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, Relation
from runic.orm.core.metadata import MetaData
from runic.orm.core.models import Node
from runic.orm.core.types import (
    EnumConverter,
    GeoLocation,
    GeoLocationConverter,
    Vector,
    VectorConverter,
)
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
    friend: MapperPerson | None = Relation(
        relationship="KNOWS",
        direction="OUTGOING",
        target="MapperPerson",
    )


class MapperInterned(Node, labels=["MapperInterned"]):
    id: str = Field()
    country: str = Field(interned=True)
    name: str = Field()


class MapperVec(Node, labels=["MapperVec"]):
    id: str = Field()
    embedding: Vector = Field(converter=VectorConverter())


class MapperGeo(Node, labels=["MapperGeo"]):
    id: str = Field()
    location: GeoLocation = Field(converter=GeoLocationConverter())


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


# ---------------------------------------------------------------------------
# Cypher wrapper: interned fields
# ---------------------------------------------------------------------------


class TestInternedCypher:
    def test_create_interned_field_uses_intern_fn(self, mapper: Mapper) -> None:
        n = MapperInterned(id="i1", country="Germany", name="Alice")
        cypher, params = mapper.build_create_query(n)
        assert "intern($country)" in cypher
        assert "$country" not in cypher.replace("intern($country)", "")
        assert params["country"] == "Germany"

    def test_create_non_interned_field_uses_plain_ref(self, mapper: Mapper) -> None:
        n = MapperInterned(id="i1", country="Germany", name="Alice")
        cypher, _ = mapper.build_create_query(n)
        assert "name: $name" in cypher

    def test_update_interned_field_uses_intern_fn(self, mapper: Mapper) -> None:
        n = MapperInterned(id="i1", country="France", name="Bob")
        cypher, params = mapper.build_update_query(n)
        assert "intern($country)" in cypher
        assert params["country"] == "France"

    def test_update_non_interned_field_plain(self, mapper: Mapper) -> None:
        n = MapperInterned(id="i1", country="France", name="Bob")
        cypher, _ = mapper.build_update_query(n)
        assert "n.name = $name" in cypher

    def test_interned_value_decoded_as_plain_string(self, mapper: Mapper) -> None:
        node = _fake_node(
            ["MapperInterned"], {"id": "i1", "country": "Germany", "name": "Alice"}
        )
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperInterned)
        assert entity.__dict__["country"] == "Germany"


# ---------------------------------------------------------------------------
# Cypher wrapper: Vector fields (vecf32)
# ---------------------------------------------------------------------------


class TestVectorCypher:
    def test_create_vector_field_uses_vecf32_fn(self, mapper: Mapper) -> None:
        n = MapperVec(id="v1", embedding=Vector([0.1, 0.2, 0.3]))
        cypher, params = mapper.build_create_query(n)
        assert "vecf32($embedding)" in cypher
        assert params["embedding"] == [0.1, 0.2, 0.3]

    def test_update_vector_field_uses_vecf32_fn(self, mapper: Mapper) -> None:
        n = MapperVec(id="v1", embedding=Vector([0.4, 0.5]))
        cypher, params = mapper.build_update_query(n)
        assert "vecf32($embedding)" in cypher
        assert params["embedding"] == [0.4, 0.5]

    def test_vector_decoded_as_vector_instance(self, mapper: Mapper) -> None:
        node = _fake_node(["MapperVec"], {"id": "v1", "embedding": [0.1, 0.2, 0.3]})
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperVec)
        assert isinstance(entity.__dict__["embedding"], Vector)

    def test_vector_to_graph_returns_plain_list(self) -> None:
        conv = VectorConverter()
        result = conv.to_graph(Vector([1.0, 2.0]))
        assert result == [1.0, 2.0]
        assert isinstance(result, list)

    def test_vector_from_graph_returns_vector(self) -> None:
        conv = VectorConverter()
        result = conv.from_graph([0.5, 0.6])
        assert isinstance(result, Vector)
        assert list(result) == [0.5, 0.6]

    def test_vector_none_passthrough(self) -> None:
        conv = VectorConverter()
        assert conv.to_graph(None) is None
        assert conv.from_graph(None) is None


# ---------------------------------------------------------------------------
# Cypher wrapper: GeoLocation fields (point)
# ---------------------------------------------------------------------------


class TestGeoLocationCypher:
    def test_create_geolocation_uses_point_fn(self, mapper: Mapper) -> None:
        n = MapperGeo(id="g1", location=GeoLocation(latitude=48.137, longitude=11.576))
        cypher, params = mapper.build_create_query(n)
        assert "point($location)" in cypher
        assert params["location"] == {"latitude": 48.137, "longitude": 11.576}

    def test_update_geolocation_uses_point_fn(self, mapper: Mapper) -> None:
        n = MapperGeo(id="g1", location=GeoLocation(latitude=51.507, longitude=-0.127))
        cypher, params = mapper.build_update_query(n)
        assert "point($location)" in cypher
        assert params["location"] == {"latitude": 51.507, "longitude": -0.127}

    def test_geolocation_decoded_from_dict(self, mapper: Mapper) -> None:
        node = _fake_node(
            ["MapperGeo"],
            {"id": "g1", "location": {"latitude": 48.137, "longitude": 11.576}},
        )
        entity = mapper.decode_node(node)
        assert isinstance(entity, MapperGeo)
        loc = entity.__dict__["location"]
        assert isinstance(loc, GeoLocation)
        assert loc.latitude == 48.137
        assert loc.longitude == 11.576

    def test_geolocation_to_graph(self) -> None:
        conv = GeoLocationConverter()
        result = conv.to_graph(GeoLocation(latitude=1.0, longitude=2.0))
        assert result == {"latitude": 1.0, "longitude": 2.0}

    def test_geolocation_from_graph(self) -> None:
        conv = GeoLocationConverter()
        result = conv.from_graph({"latitude": 3.0, "longitude": 4.0})
        assert isinstance(result, GeoLocation)
        assert result.latitude == 3.0
        assert result.longitude == 4.0

    def test_geolocation_none_passthrough(self) -> None:
        conv = GeoLocationConverter()
        assert conv.to_graph(None) is None
        assert conv.from_graph(None) is None


# ---------------------------------------------------------------------------
# Mapper dialect helpers (labels_clause / subtype_where / _labels injection)
# ---------------------------------------------------------------------------


class _SingleLabelDialect:
    """Stub dialect that emulates single-label backends (AGE-like)."""

    def labels_clause(self, labels: list[str]) -> str:
        return labels[0]

    def subtype_where(self, alias: str, labels: list[str]) -> str | None:
        if len(labels) > 1:
            return " AND ".join(f'"{lbl}" IN {alias}._labels' for lbl in labels[1:])
        return None

    def needs_labels_property(self) -> bool:
        return True

    def generated_id_where(self, alias: str, param: str) -> str:
        return f"WHERE id({alias}) = ${param}"

    def cypher_fn_for_field(self, fi: Any) -> str | None:  # noqa: ARG002
        return None

    def fulltext_call(self, label: str, alias: str, query_param: str) -> str:  # noqa: ARG002
        raise NotImplementedError

    def vector_knn_start(
        self,
        alias: str,
        labels_str: str,
        type_name: str,
        field_name: str,  # noqa: ARG002
    ) -> str:
        raise NotImplementedError

    def vector_knn_score_expr(self, alias: str, field_name: str) -> str:  # noqa: ARG002
        raise NotImplementedError

    def wrap_node(self, raw: Any) -> Any:
        return raw

    def wrap_edge(self, raw: Any) -> Any:
        return raw


class TestDialectHelpers:
    def test_labels_clause_default_multi_label(self, meta: MetaData) -> None:
        mapper = Mapper(meta)
        assert mapper.labels_clause(["A", "B"]) == "A:B"

    def test_labels_clause_delegates_to_dialect(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        assert mapper.labels_clause(["Location", "Country"]) == "Location"

    def test_subtype_where_default_none(self, meta: MetaData) -> None:
        mapper = Mapper(meta)
        assert mapper.subtype_where("n", ["A", "B"]) is None

    def test_subtype_where_delegates_to_dialect(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        result = mapper.subtype_where("n", ["Location", "Country"])
        assert result == '"Country" IN n._labels'

    def test_build_create_injects_labels_property(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        child = MapperChild(id="c1", kind="test", extra="x")
        cypher, params = mapper.build_create_query(child)
        assert "_labels" in params
        assert params["_labels"] == ["MapperParent", "MapperChild"]
        assert "MapperParent" in cypher

    def test_build_create_no_labels_property_for_single_label(
        self, meta: MetaData
    ) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        p = MapperPerson(id="p1", name="Alice")
        _, params = mapper.build_create_query(p)
        assert "_labels" not in params

    def test_build_find_all_includes_subtype_filter(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, _ = mapper.build_find_all_query(MapperChild)
        assert "MapperParent" in cypher
        assert '"MapperChild" IN n._labels' in cypher

    def test_build_paginated_includes_subtype_filter(self, meta: MetaData) -> None:
        from runic.orm.repository.pagination import Pageable

        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        pageable = Pageable(page=0, size=10)
        cypher, _ = mapper.build_paginated_query(MapperChild, pageable)
        assert '"MapperChild" IN n._labels' in cypher

    def test_build_count_includes_subtype_filter(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, _ = mapper.build_count_query(MapperChild)
        assert '"MapperChild" IN n._labels' in cypher

    def test_build_exists_includes_subtype_filter_generated_pk(
        self, meta: MetaData
    ) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, _ = mapper.build_exists_query(MapperGenerated, 42)
        assert "MapperGenerated" in cypher

    def test_build_exists_includes_subtype_filter_field_pk(
        self, meta: MetaData
    ) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, params = mapper.build_exists_query(MapperChild, "c1")
        assert '"MapperChild" IN n._labels' in cypher
        assert params["__pk"] == "c1"

    def test_build_get_includes_subtype_filter_field_pk(self, meta: MetaData) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, params = mapper.build_get_query(MapperChild, "c1")
        assert '"MapperChild" IN n._labels' in cypher
        assert params["__pk"] == "c1"

    def test_build_find_all_by_ids_includes_subtype_filter(
        self, meta: MetaData
    ) -> None:
        mapper = Mapper(meta, dialect=_SingleLabelDialect())
        cypher, params = mapper.build_find_all_by_ids_query(MapperChild, ["c1", "c2"])
        assert '"MapperChild" IN n._labels' in cypher
        assert params["__pks"] == ["c1", "c2"]
