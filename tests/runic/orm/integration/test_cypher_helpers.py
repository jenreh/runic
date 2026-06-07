"""Integration tests for Repository cypher / cypher_one / cypher_raw helpers."""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import Field
from runic.orm.core.models import Node
from runic.orm.driver.falkordb import FalkorDBDriver
from runic.orm.repository.repository import Repository
from runic.orm.session.session import Session

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test entities
# ---------------------------------------------------------------------------


class CypherPerson(Node, labels=["CypherPerson"]):
    id: str = Field()
    name: str = Field()
    age: int | None = Field(default=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph(falkordb_server: Any) -> Any:
    db = falkordb_server
    g = db.select_graph(f"test_cypher_{secrets.token_hex(6)}")
    yield FalkorDBDriver(g)
    with contextlib.suppress(Exception):
        g.delete()


@pytest.fixture
def populated_graph(graph: Any) -> Any:
    with Session(graph) as s:
        for i in range(1, 6):
            s.add(CypherPerson(id=f"cp{i}", name=f"Cypher Person {i}", age=20 + i))
    return graph


# ---------------------------------------------------------------------------
# cypher — scalar returns
# ---------------------------------------------------------------------------


def test_cypher_count_returns_int(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        result = repo.cypher("MATCH (n:CypherPerson) RETURN count(n)", returns=int)
    assert result == [5]


def test_cypher_one_count(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        total = repo.cypher_one("MATCH (n:CypherPerson) RETURN count(n)", returns=int)
    assert total == 5


def test_cypher_one_returns_none_when_no_match(graph: Any) -> None:
    with Session(graph) as s:
        repo = Repository(s, CypherPerson)
        result = repo.cypher_one(
            "MATCH (n:CypherPerson {id: $id}) RETURN n",
            {"id": "missing"},
            returns=CypherPerson,
        )
    assert result is None


# ---------------------------------------------------------------------------
# cypher — entity returns
# ---------------------------------------------------------------------------


def test_cypher_returns_entity_list(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        people = repo.cypher(
            "MATCH (n:CypherPerson) WHERE n.age > $min RETURN n",
            {"min": 23},
            returns=CypherPerson,
        )
    assert len(people) == 2
    assert all(isinstance(p, CypherPerson) for p in people)
    assert all(p.age > 23 for p in people)


def test_cypher_one_returns_entity(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        person = repo.cypher_one(
            "MATCH (n:CypherPerson {id: $id}) RETURN n",
            {"id": "cp1"},
            returns=CypherPerson,
        )
    assert person is not None
    assert person.id == "cp1"


def test_cypher_entity_result_registered_in_identity_map(
    populated_graph: Any,
) -> None:
    """Entity returned from cypher() must deduplicate with identity map."""
    with Session(populated_graph) as s:
        via_get = s.get(CypherPerson, "cp1")
        repo = Repository(s, CypherPerson)
        via_cypher = repo.cypher_one(
            "MATCH (n:CypherPerson {id: $id}) RETURN n",
            {"id": "cp1"},
            returns=CypherPerson,
        )
    assert via_cypher is via_get


# ---------------------------------------------------------------------------
# cypher — dict returns
# ---------------------------------------------------------------------------


def test_cypher_dict_returns_list_of_dicts(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        rows = repo.cypher(
            "MATCH (n:CypherPerson) RETURN n.id AS id, n.name AS name ORDER BY n.id",
            returns=dict,
        )
    assert len(rows) == 5
    assert all(isinstance(r, dict) for r in rows)
    assert set(rows[0].keys()) == {"id", "name"}
    assert rows[0]["id"] == "cp1"
    assert rows[0]["name"] == "Cypher Person 1"


# ---------------------------------------------------------------------------
# cypher — write operations
# ---------------------------------------------------------------------------


def test_cypher_write_modifies_graph(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        repo.cypher(
            "MATCH (n:CypherPerson {id: $id}) SET n.age = $age",
            {"id": "cp1", "age": 99},
            write=True,
            returns=None,
        )

    with Session(populated_graph) as s:
        person = s.get(CypherPerson, "cp1")
    assert person is not None
    assert person.age == 99


# ---------------------------------------------------------------------------
# cypher_raw
# ---------------------------------------------------------------------------


def test_cypher_raw_returns_query_result(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        raw = repo.cypher_raw("MATCH (n:CypherPerson) RETURN n.id, n.name")

    assert hasattr(raw, "rows")
    assert len(raw.rows) == 5


def test_cypher_raw_result_not_decoded(populated_graph: Any) -> None:
    with Session(populated_graph) as s:
        repo = Repository(s, CypherPerson)
        raw = repo.cypher_raw("MATCH (n:CypherPerson) RETURN n.id ORDER BY n.id")

    ids = [row[0] for row in raw.rows]
    assert ids == ["cp1", "cp2", "cp3", "cp4", "cp5"]
