"""Integration tests for Session.relate() and Session.unrelate().

Requires falkordblite (installed as the ``redislite`` module).
Marked with ``integration`` so they are skipped in environments without it.
"""

from __future__ import annotations

import contextlib
import secrets
from typing import Any

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, Relation
from runic.orm.core.models import Edge, Node
from runic.orm.session.session import Session

try:
    from redislite import FalkorDB as _FalkorDB

    _HAS_FALKORDBLITE = True
except ImportError:
    _HAS_FALKORDBLITE = False

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class MutTeam(Node, labels=["MutTeam"]):
    id: str = Field()
    name: str = Field()


class MutMembershipEdge(Edge, type="MUT_MEMBER"):
    role: str
    since: str | None = None


class MutPerson(Node, labels=["MutPerson"]):
    id: str = Field()
    name: str = Field()
    team: MutTeam | None = Relation(
        relationship="BELONGS_TO",
        direction="OUTGOING",
        target="MutTeam",
    )
    peers: list[MutPerson] = Relation(
        relationship="PEERS_WITH",
        direction="OUTGOING",
        target="MutPerson",
    )
    member_of: MutTeam | None = Relation(
        relationship="MUT_MEMBER",
        direction="OUTGOING",
        target="MutTeam",
        edge_model=MutMembershipEdge,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph() -> Any:
    if not _HAS_FALKORDBLITE:
        pytest.skip("falkordblite (redislite) not installed")
    db = _FalkorDB(protocol=2)
    graph_name = f"test_mut_{secrets.token_hex(6)}"
    g = db.select_graph(graph_name)
    yield g
    with contextlib.suppress(Exception):
        g.delete()


def _edge_count(graph: Any, rel_type: str) -> int:
    result = graph.query(f"MATCH ()-[r:{rel_type}]->() RETURN count(r)")
    return result.result_set[0][0] if result.result_set else 0


def _edge_props(graph: Any, rel_type: str) -> dict[str, Any] | None:
    result = graph.query(f"MATCH ()-[r:{rel_type}]->() RETURN r")
    if not result.result_set:
        return None
    rel = result.result_set[0][0]
    return dict(rel.properties) if hasattr(rel, "properties") else {}


# ---------------------------------------------------------------------------
# relate() — basic create
# ---------------------------------------------------------------------------


def test_relate_creates_relationship(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p1", name="Alice")
        team = MutTeam(id="t1", name="Alpha")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p1")
        team = s.get(MutTeam, "t1")
        assert person is not None
        assert team is not None
        s.relate(person, "team", team)

    assert _edge_count(graph, "BELONGS_TO") == 1


def test_relate_is_idempotent(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p2", name="Bob")
        team = MutTeam(id="t2", name="Beta")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p2")
        team = s.get(MutTeam, "t2")
        assert person is not None
        assert team is not None
        s.relate(person, "team", team)
        s.relate(person, "team", team)  # second call — same MERGE

    assert _edge_count(graph, "BELONGS_TO") == 1  # not duplicated


def test_relate_invalidates_field_cache(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p3", name="Carol")
        team = MutTeam(id="t3", name="Gamma")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p3")
        team = s.get(MutTeam, "t3")
        assert person is not None
        assert team is not None
        person.__dict__["team"] = team  # simulate cached value

        s.relate(person, "team", team)

        assert person.__dict__["team"] is _NOT_LOADED


# ---------------------------------------------------------------------------
# relate() — with edge properties (upsert)
# ---------------------------------------------------------------------------


def test_relate_with_edge_writes_properties(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p4", name="Dave")
        team = MutTeam(id="t4", name="Delta")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p4")
        team = s.get(MutTeam, "t4")
        assert person is not None
        assert team is not None
        edge = MutMembershipEdge(role="admin", since="2024-01-01")
        s.relate(person, "member_of", team, edge=edge)

    props = _edge_props(graph, "MUT_MEMBER")
    assert props is not None
    assert props.get("role") == "admin"
    assert props.get("since") == "2024-01-01"


def test_relate_upserts_edge_properties(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p5", name="Eve")
        team = MutTeam(id="t5", name="Epsilon")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p5")
        team = s.get(MutTeam, "t5")
        assert person is not None
        assert team is not None
        s.relate(person, "member_of", team, edge=MutMembershipEdge(role="viewer"))

    with Session(graph) as s:
        person = s.get(MutPerson, "p5")
        team = s.get(MutTeam, "t5")
        assert person is not None
        assert team is not None
        s.relate(person, "member_of", team, edge=MutMembershipEdge(role="owner"))

    props = _edge_props(graph, "MUT_MEMBER")
    assert props is not None
    assert props.get("role") == "owner"  # updated, not duplicated
    assert _edge_count(graph, "MUT_MEMBER") == 1


# ---------------------------------------------------------------------------
# unrelate()
# ---------------------------------------------------------------------------


def test_unrelate_removes_relationship(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p6", name="Frank")
        team = MutTeam(id="t6", name="Zeta")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p6")
        team = s.get(MutTeam, "t6")
        assert person is not None
        assert team is not None
        s.relate(person, "team", team)

    assert _edge_count(graph, "BELONGS_TO") >= 1

    with Session(graph) as s:
        person = s.get(MutPerson, "p6")
        team = s.get(MutTeam, "t6")
        assert person is not None
        assert team is not None
        s.unrelate(person, "team", team)

    assert _edge_count(graph, "BELONGS_TO") == 0


def test_unrelate_invalidates_field_cache(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p7", name="Grace")
        team = MutTeam(id="t7", name="Eta")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p7")
        team = s.get(MutTeam, "t7")
        assert person is not None
        assert team is not None
        s.relate(person, "team", team)

    with Session(graph) as s:
        person = s.get(MutPerson, "p7")
        team = s.get(MutTeam, "t7")
        assert person is not None
        assert team is not None
        person.__dict__["team"] = team  # simulate cached

        s.unrelate(person, "team", team)

        assert person.__dict__["team"] is _NOT_LOADED


def test_unrelate_noop_when_no_relationship(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p8", name="Hank")
        team = MutTeam(id="t8", name="Theta")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p8")
        team = s.get(MutTeam, "t8")
        assert person is not None
        assert team is not None
        s.unrelate(person, "team", team)  # no relationship exists — should not raise

    assert _edge_count(graph, "BELONGS_TO") == 0


# ---------------------------------------------------------------------------
# relate() then lazy-load
# ---------------------------------------------------------------------------


def test_relate_then_lazy_load_returns_target(graph: Any) -> None:
    with Session(graph) as s:
        person = MutPerson(id="p9", name="Iris")
        team = MutTeam(id="t9", name="Iota")
        s.add(person)
        s.add(team)
        s.commit()

    with Session(graph) as s:
        person = s.get(MutPerson, "p9")
        team = s.get(MutTeam, "t9")
        assert person is not None
        assert team is not None
        s.relate(person, "team", team)

    with Session(graph) as s:
        person = s.get(MutPerson, "p9")
        assert person is not None
        loaded_team = person.team  # type: ignore[attr-defined]
        assert loaded_team is not None
        assert loaded_team.id == "t9"
