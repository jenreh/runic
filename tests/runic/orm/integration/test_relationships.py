"""Integration tests for lazy and eager relationship loading."""

from __future__ import annotations

from typing import Any

import pytest

from runic.orm.core.descriptors import _NOT_LOADED, Field, Relation
from runic.orm.core.models import Node
from runic.orm.exceptions import DetachedEntityError
from runic.orm.session.session import Session

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------


class Department(Node, labels=["Department"]):
    id: str = Field()
    name: str = Field()
    # Mirror of Employee.department — same BELONGS_TO edge from the Department side
    staff: list[Employee] = Relation(
        relationship="BELONGS_TO",
        direction="INCOMING",
        target="Employee",
    )


class Employee(Node, labels=["Employee"]):
    id: str = Field()
    name: str = Field()
    department: Department | None = Relation(
        relationship="BELONGS_TO",
        direction="OUTGOING",
        target="Department",
    )
    colleagues: list[Employee] = Relation(
        relationship="KNOWS",
        direction="OUTGOING",
        target="Employee",
        lazy=True,
    )
    # Symmetric peer relationship — undirected WORKS_WITH edge
    peers: list[Employee] = Relation(
        relationship="WORKS_WITH",
        direction="BOTH",
        target="Employee",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_department(graph_driver: Any, dept_id: str, name: str) -> None:
    graph_driver.execute(
        "CREATE (:Department {id: $id, name: $name})", {"id": dept_id, "name": name}
    )


def _create_employee(graph_driver: Any, emp_id: str, name: str) -> None:
    graph_driver.execute(
        "CREATE (:Employee {id: $id, name: $name})", {"id": emp_id, "name": name}
    )


def _link_dept(graph_driver: Any, emp_id: str, dept_id: str) -> None:
    graph_driver.execute(
        "MATCH (e:Employee {id: $eid}), (d:Department {id: $did}) "
        "CREATE (e)-[:BELONGS_TO]->(d)",
        {"eid": emp_id, "did": dept_id},
    )


def _link_knows(graph_driver: Any, emp1_id: str, emp2_id: str) -> None:
    graph_driver.execute(
        "MATCH (a:Employee {id: $a}), (b:Employee {id: $b}) CREATE (a)-[:KNOWS]->(b)",
        {"a": emp1_id, "b": emp2_id},
    )


# ---------------------------------------------------------------------------
# Lazy loading — single relationship
# ---------------------------------------------------------------------------


def test_lazy_load_single_relationship(graph_driver: Any) -> None:
    _create_department(graph_driver, "d1", "Engineering")
    _create_employee(graph_driver, "e1", "Alice")
    _link_dept(graph_driver, "e1", "d1")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e1")
        assert emp is not None
        assert emp.__dict__["department"] is _NOT_LOADED

        dept = emp.department
        assert dept is not None
        assert dept.id == "d1"
        assert dept.name == "Engineering"
        assert emp.__dict__["department"] is dept  # cached


def test_lazy_load_none_when_no_relationship(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e2", "Bob")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e2")
        assert emp is not None
        dept = emp.department
        assert dept is None
        assert emp.__dict__["department"] is None  # cached as None


def test_lazy_load_does_not_retrigger_on_second_access(graph_driver: Any) -> None:
    _create_department(graph_driver, "d2", "Design")
    _create_employee(graph_driver, "e3", "Carol")
    _link_dept(graph_driver, "e3", "d2")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e3")
        assert emp is not None
        _ = emp.department  # first access loads it
        dept2 = emp.department  # second access should return cached value
        assert dept2 is not None
        assert dept2.name == "Design"


# ---------------------------------------------------------------------------
# Lazy loading — collection relationship
# ---------------------------------------------------------------------------


def test_lazy_load_collection_relationship(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e4", "Dave")
    _create_employee(graph_driver, "e5", "Eve")
    _create_employee(graph_driver, "e6", "Frank")
    _link_knows(graph_driver, "e4", "e5")
    _link_knows(graph_driver, "e4", "e6")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e4")
        assert emp is not None
        assert emp.__dict__["colleagues"] is _NOT_LOADED

        colleagues = emp.colleagues
        assert isinstance(colleagues, list)
        assert len(colleagues) == 2
        ids = {c.id for c in colleagues}
        assert ids == {"e5", "e6"}


def test_lazy_load_empty_collection(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e7", "Grace")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e7")
        assert emp is not None
        colleagues = emp.colleagues
        assert colleagues == []


# ---------------------------------------------------------------------------
# Eager loading — fetch=
# ---------------------------------------------------------------------------


def test_eager_fetch_single_relationship(graph_driver: Any) -> None:
    _create_department(graph_driver, "d3", "Marketing")
    _create_employee(graph_driver, "e8", "Hank")
    _link_dept(graph_driver, "e8", "d3")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e8", fetch=["department"])
        assert emp is not None

        dept = emp.__dict__["department"]
        assert dept is not None
        assert dept.id == "d3"
        assert dept.name == "Marketing"


def test_eager_fetch_returns_none_when_no_relationship(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e9", "Iris")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e9", fetch=["department"])
        assert emp is not None
        assert emp.__dict__["department"] is None


def test_eager_fetch_collection(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e10", "Jill")
    _create_employee(graph_driver, "e11", "Kyle")
    _create_employee(graph_driver, "e12", "Lena")
    _link_knows(graph_driver, "e10", "e11")
    _link_knows(graph_driver, "e10", "e12")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e10", fetch=["colleagues"])
        assert emp is not None

        colleagues = emp.__dict__["colleagues"]
        assert isinstance(colleagues, list)
        assert len(colleagues) == 2
        ids = {c.id for c in colleagues}
        assert ids == {"e11", "e12"}


def test_eager_fetch_empty_collection(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e13", "Mia")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e13", fetch=["colleagues"])
        assert emp is not None
        assert emp.__dict__["colleagues"] == []


def test_eager_fetch_multiple_relationships(graph_driver: Any) -> None:
    _create_department(graph_driver, "d4", "Sales")
    _create_employee(graph_driver, "e14", "Nick")
    _create_employee(graph_driver, "e15", "Olga")
    _link_dept(graph_driver, "e14", "d4")
    _link_knows(graph_driver, "e14", "e15")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e14", fetch=["department", "colleagues"])
        assert emp is not None

        dept = emp.__dict__["department"]
        assert dept is not None
        assert dept.name == "Sales"

        colleagues = emp.__dict__["colleagues"]
        assert isinstance(colleagues, list)
        assert len(colleagues) == 1
        assert colleagues[0].id == "e15"


def test_eager_fetch_injects_session_into_related_entities(graph_driver: Any) -> None:
    _create_department(graph_driver, "d5", "HR")
    _create_employee(graph_driver, "e16", "Pam")
    _link_dept(graph_driver, "e16", "d5")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e16", fetch=["department"])
        assert emp is not None
        dept = emp.__dict__["department"]
        assert dept is not None
        assert "_session" in dept.__dict__


# ---------------------------------------------------------------------------
# Detached entity raises on lazy access
# ---------------------------------------------------------------------------


def test_detached_entity_lazy_access_raises(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e17", "Quinn")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e17")
        assert emp is not None
        s.expunge(emp)

    with pytest.raises(DetachedEntityError):
        _ = emp.department


# ---------------------------------------------------------------------------
# Lazy-loaded entity gets _session injected (chain traversal)
# ---------------------------------------------------------------------------


def test_lazy_loaded_entity_has_session_for_further_traversal(
    graph_driver: Any,
) -> None:
    _create_department(graph_driver, "d6", "Finance")
    _create_employee(graph_driver, "e18", "Rita")
    _link_dept(graph_driver, "e18", "d6")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e18")
        assert emp is not None
        dept = emp.department
        assert dept is not None
        assert "_session" in dept.__dict__


# ---------------------------------------------------------------------------
# Mirrored declarations — same edge accessed from both sides
# ---------------------------------------------------------------------------


def test_incoming_mirror_reflects_outgoing_edge(graph_driver: Any) -> None:
    # Employee.department is OUTGOING; Department.staff is INCOMING.
    # Writing via the Employee side makes the edge visible from the
    # Department side without any extra relate() call.
    _create_department(graph_driver, "d20", "Backend")
    _create_employee(graph_driver, "e20", "Sam")
    _create_employee(graph_driver, "e21", "Tina")
    _link_dept(graph_driver, "e20", "d20")
    _link_dept(graph_driver, "e21", "d20")

    with Session(graph_driver) as s:
        dept = s.get(Department, "d20")
        assert dept is not None
        staff = dept.staff  # type: ignore[attr-defined]
        assert isinstance(staff, list)
        ids = {e.id for e in staff}
        assert ids == {"e20", "e21"}


def test_incoming_mirror_session_relate(graph_driver: Any) -> None:
    # session.relate() via the OUTGOING side; read back via the INCOMING mirror.
    _create_department(graph_driver, "d21", "Ops")
    _create_employee(graph_driver, "e22", "Uma")

    with Session(graph_driver) as s:
        emp = s.get(Employee, "e22")
        dept = s.get(Department, "d21")
        assert emp is not None
        assert dept is not None
        s.relate(emp, Employee.department, dept)  # ty: ignore[invalid-argument-type]

    with Session(graph_driver) as s:
        dept = s.get(Department, "d21")
        assert dept is not None
        staff = dept.staff  # type: ignore[attr-defined]
        assert len(staff) == 1
        assert staff[0].id == "e22"


# ---------------------------------------------------------------------------
# direction="BOTH" — undirected peer relationship
# ---------------------------------------------------------------------------


def test_both_direction_lazy_load_from_source(graph_driver: Any) -> None:
    # Writing the edge from Alice's side; Alice should see Bob as a peer.
    _create_employee(graph_driver, "e30", "Alice")
    _create_employee(graph_driver, "e31", "Bob")
    graph_driver.execute(
        "MATCH (a:Employee {id: $a}), (b:Employee {id: $b}) CREATE (a)-[:WORKS_WITH]-(b)",
        {"a": "e30", "b": "e31"},
    )

    with Session(graph_driver) as s:
        alice = s.get(Employee, "e30")
        assert alice is not None
        peers = alice.peers  # type: ignore[attr-defined]
        assert isinstance(peers, list)
        assert any(p.id == "e31" for p in peers)


def test_both_direction_lazy_load_from_target(graph_driver: Any) -> None:
    # Accessing .peers from the node that was the physical *target* of the edge.
    _create_employee(graph_driver, "e32", "Carol")
    _create_employee(graph_driver, "e33", "Dave")
    graph_driver.execute(
        "MATCH (a:Employee {id: $a}), (b:Employee {id: $b}) CREATE (a)-[:WORKS_WITH]-(b)",
        {"a": "e32", "b": "e33"},
    )

    with Session(graph_driver) as s:
        dave = s.get(Employee, "e33")
        assert dave is not None
        # Dave is the physical target; the BOTH pattern still finds the edge
        peers = dave.peers  # type: ignore[attr-defined]
        assert any(p.id == "e32" for p in peers)


def test_both_direction_session_relate_and_read_both_sides(
    graph_driver: Any,
) -> None:
    _create_employee(graph_driver, "e34", "Eve")
    _create_employee(graph_driver, "e35", "Frank")

    with Session(graph_driver) as s:
        eve = s.get(Employee, "e34")
        frank = s.get(Employee, "e35")
        assert eve is not None
        assert frank is not None
        s.relate(eve, Employee.peers, frank)  # ty: ignore[invalid-argument-type]

    with Session(graph_driver) as s:
        eve = s.get(Employee, "e34")
        frank = s.get(Employee, "e35")
        assert eve is not None
        assert frank is not None

        # Both sides find the peer through the undirected pattern
        eve_peers = eve.peers  # type: ignore[attr-defined]
        frank_peers = frank.peers  # type: ignore[attr-defined]
        assert any(p.id == "e35" for p in eve_peers)
        assert any(p.id == "e34" for p in frank_peers)


def test_both_direction_session_unrelate(graph_driver: Any) -> None:
    _create_employee(graph_driver, "e36", "Grace")
    _create_employee(graph_driver, "e37", "Hank")
    graph_driver.execute(
        "MATCH (a:Employee {id: $a}), (b:Employee {id: $b}) CREATE (a)-[:WORKS_WITH]-(b)",
        {"a": "e36", "b": "e37"},
    )

    with Session(graph_driver) as s:
        grace = s.get(Employee, "e36")
        hank = s.get(Employee, "e37")
        assert grace is not None
        assert hank is not None
        s.unrelate(grace, Employee.peers, hank)  # ty: ignore[invalid-argument-type]

    with Session(graph_driver) as s:
        grace = s.get(Employee, "e36")
        assert grace is not None
        peers = grace.peers  # type: ignore[attr-defined]
        assert peers == []
