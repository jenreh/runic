"""A model whose property names are Cypher keywords works on every backend.

The unit suite proves runic *quotes* every property key and result alias; this
one proves each backend then *accepts* the result.  Apache AGE is the backend
that needs it — it reads an unquoted ``n.count`` as a call to the aggregate
function and rejects the statement — but the whole matrix runs, because quoting
is only worth doing if it is portable.

A failure here on AGE is worth reading carefully: one syntax error aborts the
PostgreSQL transaction, so every later statement in the same Session fails with
"current transaction is aborted".  The first error is the real one.
"""

from __future__ import annotations

from typing import Any

import pytest

from runic.ogm.core.descriptors import Field, Relation
from runic.ogm.core.models import Edge, Node
from runic.ogm.query.expressions import count
from runic.ogm.query.values import alias, param
from runic.ogm.repository.repository import Repository
from runic.ogm.session.session import Session

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Models — every property name below is a word AGE rejects unquoted
# ---------------------------------------------------------------------------


class RwTally(Edge, type="RW_TALLY"):
    count: int | None = Field(default=None)
    end: str | None = Field(default=None)


class RwNode(Node, labels=["RwNode"]):
    id: str = Field(primary_key=True)
    count: int | None = Field(default=None)
    end: str | None = Field(default=None)
    order: int | None = Field(default=None)
    match: str | None = Field(default=None)
    tallied: list[RwNode] = Relation(
        relationship="RW_TALLY",
        direction="OUTGOING",
        target="RwNode",
        edge_model="RwTally",
    )


class RwKeyed(Node, labels=["RwKeyed"]):
    """The primary key itself is a reserved word."""

    end: str = Field(primary_key=True)
    order: int | None = Field(default=None)


@pytest.fixture
def seeded(graph_driver: Any) -> Any:
    with Session(graph_driver) as session:
        session.add(RwNode(id="rw1", count=3, end="alpha", order=2, match="x"))
        session.add(RwNode(id="rw2", count=9, end="beta", order=1, match="y"))
        session.add(RwKeyed(end="k1", order=5))
        session.commit()
    return graph_driver


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def test_create_and_read_back(seeded: Any) -> None:
    with Session(seeded) as session:
        found = session.get(RwNode, "rw1")
    assert found is not None
    assert found.count == 3
    assert found.end == "alpha"


def test_update_a_reserved_property(seeded: Any) -> None:
    with Session(seeded) as session:
        entity = session.get(RwNode, "rw1")
        assert entity is not None
        entity.count = 42
        session.commit()

    with Session(seeded) as session:
        reloaded = session.get(RwNode, "rw1")
    assert reloaded is not None
    assert reloaded.count == 42


def test_reserved_primary_key_round_trips(seeded: Any) -> None:
    with Session(seeded) as session:
        found = session.get(RwKeyed, "k1")
    assert found is not None
    assert found.order == 5


def test_delete_by_reserved_primary_key(seeded: Any) -> None:
    with Session(seeded) as session:
        entity = session.get(RwKeyed, "k1")
        assert entity is not None
        session.delete(entity)
        session.commit()

    with Session(seeded) as session:
        assert session.get(RwKeyed, "k1") is None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_filter_on_a_reserved_property(seeded: Any) -> None:
    with Session(seeded) as session:
        rows = session.query(RwNode).where(RwNode.count > 5).all()  # ty: ignore[unsupported-operator]
    assert [r.id for r in rows] == ["rw2"]


def test_null_check_on_a_reserved_property(seeded: Any) -> None:
    with Session(seeded) as session:
        rows = session.query(RwNode).where(RwNode.end.is_not_null()).all()  # ty: ignore[unresolved-attribute]
    assert {r.id for r in rows} == {"rw1", "rw2"}


def test_project_and_order_by_reserved_properties(seeded: Any) -> None:
    with Session(seeded) as session:
        rows = (
            session.query(RwNode)
            .project(RwNode.id.as_("id"), RwNode.count.as_("count"))  # ty: ignore[unresolved-attribute]
            .order_by(RwNode.order)
            .all_rows()
        )
    assert [r["id"] for r in rows] == ["rw2", "rw1"]
    assert [r["count"] for r in rows] == [9, 3]


def test_aggregate_over_a_reserved_property(seeded: Any) -> None:
    with Session(seeded) as session:
        rows = session.query(RwNode).project(count(RwNode.count).as_("end")).all_rows()
    assert rows[0]["end"] == 2


def test_unaliased_projection_keys_carry_no_quoting(seeded: Any) -> None:
    """The store reports an unaliased projection under the text it was sent.

    Quoting is an emission detail, so it must be stripped back off before the
    column names become ``all_rows()`` keys — otherwise every caller reading
    ``row["n.count"]`` would break the day runic started quoting.
    """
    with Session(seeded) as session:
        rows = session.query(RwNode).project(RwNode.count).all_rows()
    assert "`" not in "".join(rows[0])


def test_a_named_handle_reads_a_reserved_property(seeded: Any) -> None:
    """A handle reaches the property by attribute — the quoting still applies."""
    a = alias(RwNode, "a")
    with Session(seeded) as session:
        rows = (
            session.query(a)  # ty: ignore[invalid-argument-type]
            .where(a.count < param("ceiling"))
            .project(a.id.as_("id"))
            .all_rows({"ceiling": 5})
        )
    assert [r["id"] for r in rows] == ["rw1"]


def test_find_all_by_reserved_primary_keys(seeded: Any) -> None:
    with Session(seeded) as session:
        rows = Repository(session, RwKeyed).find_all_by_ids(["k1"])
    assert [r.end for r in rows] == ["k1"]


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


def test_edge_with_a_reserved_property(seeded: Any) -> None:
    with Session(seeded) as session:
        source = session.get(RwNode, "rw1")
        target = session.get(RwNode, "rw2")
        assert source is not None
        assert target is not None
        session.relate(source, RwNode.tallied, target, edge=RwTally(count=7, end="z"))  # ty: ignore[invalid-argument-type]
        session.commit()

    with Session(seeded) as session:
        a, b, r = alias(RwNode, "a"), alias(RwNode, "b"), alias(RwTally, "r")
        rows = (
            session.query(a)  # ty: ignore[invalid-argument-type]
            .where(a.id == "rw1")
            .traverse(a.tallied, edge=r, to=b)
            .where(r.count.is_not_null())
            .project(b.id.as_("id"))
            .all_rows()
        )
    assert [r["id"] for r in rows] == ["rw2"]
