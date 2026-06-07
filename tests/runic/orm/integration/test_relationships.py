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
