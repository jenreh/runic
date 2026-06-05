"""Unit tests for lazy and eager relationship loading."""

from __future__ import annotations

import weakref
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, FieldInfo
from runic.orm.core.models import Node
from runic.orm.exceptions import DetachedEntityError, LazyLoadError
from runic.orm.mapper.mapper import Mapper
from runic.orm.mapper.relationship_loader import RelationshipLoader
from runic.orm.session.async_session import AsyncSession
from runic.orm.session.session import Session

# ---------------------------------------------------------------------------
# Model definitions — use unique labels to avoid collision with other test files
# ---------------------------------------------------------------------------


class RelCompany(Node, labels=["RelCompany"]):
    id: str = Field()
    name: str = Field()


class RelPerson(Node, labels=["RelPerson"]):
    id: str = Field()
    name: str = Field()
    company: RelCompany | None = Field(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="RelCompany",
        default=None,
    )
    friends: list[RelPerson] = Field(
        relationship="KNOWS",
        direction="OUTGOING",
        target="RelPerson",
        lazy=True,
        default=None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_falkor_node(
    node_id: Any, labels: list[str], props: dict[str, Any]
) -> MagicMock:
    n = MagicMock()
    n.id = node_id
    n.labels = labels
    n.properties = props
    return n


def _make_result(*rows: list[Any]) -> MagicMock:
    r = MagicMock()
    r.result_set = list(rows)
    return r


def _empty_result() -> MagicMock:
    r = MagicMock()
    r.result_set = []
    return r


# ---------------------------------------------------------------------------
# _NOT_LOADED sentinel tests
# ---------------------------------------------------------------------------


def test_not_loaded_is_singleton() -> None:
    from runic.orm.core.descriptors import _NotLoadedType

    assert _NotLoadedType() is _NOT_LOADED


def test_not_loaded_repr() -> None:
    assert repr(_NOT_LOADED) == "_NOT_LOADED"


def test_not_loaded_is_falsy() -> None:
    assert not _NOT_LOADED


# ---------------------------------------------------------------------------
# FieldInfo.is_collection
# ---------------------------------------------------------------------------


def test_field_info_is_collection_single() -> None:
    fi = next(f for f in RelPerson._fields if f.name == "company")
    assert fi.is_collection is False


def test_field_info_is_collection_list() -> None:
    fi = next(f for f in RelPerson._fields if f.name == "friends")
    assert fi.is_collection is True


# ---------------------------------------------------------------------------
# decode_node sets _NOT_LOADED for relationship fields
# ---------------------------------------------------------------------------


def test_decode_node_sets_not_loaded_for_relationship_fields() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)

    falkor_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    entity = mapper.decode_node(falkor_node, RelPerson)

    assert entity.__dict__["company"] is _NOT_LOADED
    assert entity.__dict__["friends"] is _NOT_LOADED


def test_update_entity_from_node_resets_relationship_fields() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)

    entity = RelPerson(id="p1", name="Alice")
    company = RelCompany(id="c1", name="Acme")
    entity.__dict__["company"] = company  # simulate previously loaded

    falkor_node = _make_falkor_node(
        0, ["RelPerson"], {"id": "p1", "name": "Alice Updated"}
    )
    mapper.update_entity_from_node(entity, falkor_node)

    assert entity.__dict__["company"] is _NOT_LOADED
    assert entity.name == "Alice Updated"


# ---------------------------------------------------------------------------
# Field.__get__ lazy trigger
# ---------------------------------------------------------------------------


def test_field_get_raises_when_not_loaded_and_no_session() -> None:
    """Accessing _NOT_LOADED without a session raises DetachedEntityError."""
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    falkor_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    entity = mapper.decode_node(falkor_node, RelPerson)

    with pytest.raises(DetachedEntityError):
        _ = entity.company


def test_field_get_triggers_lazy_load_via_session(mock_graph: MagicMock) -> None:
    """Accessing _NOT_LOADED on a session-attached entity calls load_relationship."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    company_node = _make_falkor_node(1, ["RelCompany"], {"id": "c1", "name": "Acme"})
    mock_graph.query.return_value = _make_result([company_node])

    company = entity.company
    assert company is not None
    assert company.id == "c1"
    assert company.name == "Acme"


def test_field_get_caches_loaded_value(mock_graph: MagicMock) -> None:
    """Once loaded, re-accessing the field does not trigger another query."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    company_node = _make_falkor_node(1, ["RelCompany"], {"id": "c1", "name": "Acme"})
    mock_graph.query.return_value = _make_result([company_node])

    _ = entity.company
    call_count_after_first = mock_graph.query.call_count

    # Access again — should NOT trigger another query
    _ = entity.company
    assert mock_graph.query.call_count == call_count_after_first


def test_field_get_returns_none_for_missing_relationship(mock_graph: MagicMock) -> None:
    """Lazy load returns None when the graph has no matching relationship."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    mock_graph.query.return_value = _empty_result()
    result = entity.company
    assert result is None
    assert entity.__dict__["company"] is None


def test_field_get_returns_list_for_collection(mock_graph: MagicMock) -> None:
    """Lazy load returns a list for collection relationship fields."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    friend_node = _make_falkor_node(2, ["RelPerson"], {"id": "p2", "name": "Bob"})
    mock_graph.query.return_value = _make_result([friend_node])

    friends = entity.friends
    assert isinstance(friends, list)
    assert len(friends) == 1
    assert friends[0].id == "p2"


def test_field_get_returns_empty_list_for_missing_collection(
    mock_graph: MagicMock,
) -> None:
    """Lazy load returns [] when the graph has no collection members."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    mock_graph.query.return_value = _empty_result()
    friends = entity.friends
    assert friends == []


# ---------------------------------------------------------------------------
# AsyncSession: lazy access raises LazyLoadError
# ---------------------------------------------------------------------------


def test_async_session_lazy_load_raises(mock_graph: MagicMock) -> None:
    """In AsyncSession, accessing _NOT_LOADED raises LazyLoadError."""
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    async_s = AsyncSession(mock_graph, mapper)

    falkor_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    entity = mapper.decode_node(falkor_node, RelPerson)
    entity.__dict__["_session"] = weakref.ref(async_s)

    with pytest.raises(LazyLoadError, match="AsyncSession"):
        _ = entity.company


# ---------------------------------------------------------------------------
# Expunge clears _session
# ---------------------------------------------------------------------------


def test_expunge_clears_session_ref(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None
    assert "_session" in entity.__dict__

    s.expunge(entity)
    assert "_session" not in entity.__dict__


def test_expunge_all_clears_session_refs(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    s.expunge_all()
    assert "_session" not in entity.__dict__


def test_detached_entity_raises_on_lazy_access(mock_graph: MagicMock) -> None:
    """After expunge, accessing a lazy field raises DetachedEntityError."""
    s = Session(mock_graph)
    mock_graph.query.return_value = _make_result(
        [_make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})]
    )
    entity = s.get(RelPerson, "p1")
    assert entity is not None
    s.expunge(entity)

    with pytest.raises(DetachedEntityError):
        _ = entity.company


# ---------------------------------------------------------------------------
# RelationshipLoader — build_lazy_load_query
# ---------------------------------------------------------------------------


def test_build_lazy_load_query_outgoing() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    entity = RelPerson(id="p1", name="Alice")
    entity.__dict__["_new"] = False

    fi = next(f for f in RelPerson._fields if f.name == "company")
    cypher, params = loader.build_lazy_load_query(entity, fi)

    assert "MATCH" in cypher
    assert "WORKS_FOR" in cypher
    assert "->" in cypher
    assert "RelCompany" in cypher
    assert params == {"__pk": "p1"}


def test_build_lazy_load_query_incoming() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    entity = RelPerson(id="p1", name="Alice")
    entity.__dict__["_new"] = False

    fi_incoming = FieldInfo(
        name="friends",
        field=Field(
            relationship="KNOWS",
            direction="INCOMING",
            target="RelPerson",
            default=None,
        ),
        is_collection=True,
    )
    fi_incoming.field._name = "friends"

    cypher, params = loader.build_lazy_load_query(entity, fi_incoming)

    assert "<-" in cypher
    assert "KNOWS" in cypher
    assert params == {"__pk": "p1"}


# ---------------------------------------------------------------------------
# RelationshipLoader — build_get_with_fetch_query
# ---------------------------------------------------------------------------


def test_build_get_with_fetch_query_structure() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    cypher, params, fetch_meta = loader.build_get_with_fetch_query(
        RelPerson, "p1", ["company"]
    )

    assert "MATCH" in cypher
    assert "OPTIONAL MATCH" in cypher
    assert "collect(distinct" in cypher
    assert "WORKS_FOR" in cypher
    assert "->" in cypher
    assert params == {"__pk": "p1"}
    assert len(fetch_meta) == 1
    assert fetch_meta[0][0] == "company"


def test_build_get_with_fetch_query_skips_unknown_fields() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    cypher, params, fetch_meta = loader.build_get_with_fetch_query(
        RelPerson, "p1", ["nonexistent_field", "company"]
    )

    assert len(fetch_meta) == 1
    assert fetch_meta[0][0] == "company"


def test_build_get_with_fetch_query_multiple() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    cypher, params, fetch_meta = loader.build_get_with_fetch_query(
        RelPerson, "p1", ["company", "friends"]
    )

    assert cypher.count("OPTIONAL MATCH") == 2
    assert len(fetch_meta) == 2


# ---------------------------------------------------------------------------
# RelationshipLoader — decode_eager_columns
# ---------------------------------------------------------------------------


def test_decode_eager_columns_single_relationship() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    entity = RelPerson(id="p1", name="Alice")
    entity.__dict__["_new"] = False

    company_node = _make_falkor_node(1, ["RelCompany"], {"id": "c1", "name": "Acme"})
    fi = next(f for f in RelPerson._fields if f.name == "company")
    fetch_meta = [("company", fi)]

    row = [
        _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"}),
        [company_node],
    ]

    related = loader.decode_eager_columns(row, entity, fetch_meta)

    assert entity.__dict__["company"] is not None
    assert entity.__dict__["company"].id == "c1"
    assert len(related) == 1


def test_decode_eager_columns_empty_single_returns_none() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    entity = RelPerson(id="p1", name="Alice")
    entity.__dict__["_new"] = False

    fi = next(f for f in RelPerson._fields if f.name == "company")
    fetch_meta = [("company", fi)]
    row = [
        _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"}),
        [],
    ]

    related = loader.decode_eager_columns(row, entity, fetch_meta)

    assert entity.__dict__["company"] is None
    assert related == []


def test_decode_eager_columns_collection() -> None:
    from runic.orm.core.metadata import metadata

    mapper = Mapper(metadata)
    loader = RelationshipLoader(metadata, mapper)

    entity = RelPerson(id="p1", name="Alice")
    entity.__dict__["_new"] = False

    fi = next(f for f in RelPerson._fields if f.name == "friends")
    fetch_meta = [("friends", fi)]

    friend1 = _make_falkor_node(2, ["RelPerson"], {"id": "p2", "name": "Bob"})
    friend2 = _make_falkor_node(3, ["RelPerson"], {"id": "p3", "name": "Carol"})
    row = [
        _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"}),
        [friend1, friend2],
    ]

    related = loader.decode_eager_columns(row, entity, fetch_meta)

    friends = entity.__dict__["friends"]
    assert isinstance(friends, list)
    assert len(friends) == 2
    assert len(related) == 2


# ---------------------------------------------------------------------------
# Session.get with fetch
# ---------------------------------------------------------------------------


def test_session_get_with_fetch_single_relationship(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)

    person_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    company_node = _make_falkor_node(1, ["RelCompany"], {"id": "c1", "name": "Acme"})
    mock_graph.query.return_value = _make_result([person_node, [company_node]])

    entity = s.get(RelPerson, "p1", fetch=["company"])
    assert entity is not None
    assert entity.__dict__["company"] is not None
    assert entity.__dict__["company"].id == "c1"


def test_session_get_with_fetch_empty_relationship(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)

    person_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    mock_graph.query.return_value = _make_result([person_node, []])

    entity = s.get(RelPerson, "p1", fetch=["company"])
    assert entity is not None
    assert entity.__dict__["company"] is None


def test_session_get_with_fetch_injects_session_into_related(
    mock_graph: MagicMock,
) -> None:
    s = Session(mock_graph)

    person_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    company_node = _make_falkor_node(1, ["RelCompany"], {"id": "c1", "name": "Acme"})
    mock_graph.query.return_value = _make_result([person_node, [company_node]])

    entity = s.get(RelPerson, "p1", fetch=["company"])
    assert entity is not None
    company = entity.__dict__["company"]
    assert company is not None
    assert "_session" in company.__dict__


def test_session_get_without_fetch_does_not_eager_load(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)

    person_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    mock_graph.query.return_value = _make_result([person_node])

    entity = s.get(RelPerson, "p1")
    assert entity is not None
    assert entity.__dict__["company"] is _NOT_LOADED


# ---------------------------------------------------------------------------
# Lazy load query cypher includes expected pattern
# ---------------------------------------------------------------------------


def test_lazy_load_cypher_uses_outgoing_pattern(mock_graph: MagicMock) -> None:
    s = Session(mock_graph)
    person_node = _make_falkor_node(0, ["RelPerson"], {"id": "p1", "name": "Alice"})
    mock_graph.query.return_value = _make_result([person_node])
    entity = s.get(RelPerson, "p1")
    assert entity is not None

    mock_graph.query.return_value = _empty_result()
    _ = entity.company

    last_cypher = mock_graph.query.call_args_list[-1][0][0]
    assert "->" in last_cypher
    assert "WORKS_FOR" in last_cypher
    assert "RelCompany" in last_cypher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_graph() -> MagicMock:
    g = MagicMock()
    g.query.return_value = MagicMock(result_set=[])
    return g
