"""Catalogue parity against a real backend.

The unit suite proves runic *emits* the right Cypher; this one proves the
backend *accepts* it.  Every expressible statement has its parameters bound and
is executed against each configured backend — which is the only way a statement
ever gets checked rather than merely read, and is the test the reference
catalogue's docstring describes.

Run against all backends with::

    RUNIC_TEST_BACKENDS=falkordb,neo4j,memgraph,arcadedb,age task test:integration
"""

from __future__ import annotations

from typing import Any

import pytest

from runic.ogm.session.session import Session
from tests.runic.ogm.catalog_cases import CATALOG_CASES, CatalogCase, expressible
from tests.runic.ogm.catalog_models import (
    Address,
    Group,
    Message,
    Template,
    Topic,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(graph_driver: Any) -> Any:
    """A graph holding one of everything the catalogue reads.

    Deliberately tiny: parity is about whether a statement runs and returns the
    shape it claims, not about result volume.  One message without a canonical
    id is included because several statements are defined by how they skip it.
    """
    with Session(graph_driver) as session:
        session.add(Message(id="m1", subject="Invoice 42", body_clean="please pay"))
        session.add(Message(id="m2", subject="Re: Invoice 42", body_clean="paid"))
        session.add(Message(id="", subject="no canonical id"))
        session.add(Address(id="a1"))
        session.add(Address(id="a2"))
        session.add(Group(id="g1", size=2, message_count=2))
        session.add(Topic(id="t1", label="billing", method="token"))
        session.add(Template(id="tpl1", direction="sent", occurrences=2))
        session.commit()
    return graph_driver


def _ids(case: object) -> str:
    return case.name if isinstance(case, CatalogCase) else ""


def _backend_of(driver: Any) -> str:
    """Name the backend behind *driver*, for per-backend expectations."""
    dialect = type(driver.dialect).__name__.removesuffix("Dialect").lower()
    return {
        "falkordb": "falkordb",
        "neo4j": "neo4j",
        "memgraph": "memgraph",
        "arcadedb": "arcadedb",
        "age": "age",
    }.get(dialect, dialect)


@pytest.mark.parametrize("case", expressible(), ids=_ids)
def test_statement_runs_against_backend(case: CatalogCase, seeded: Any) -> None:
    """Bind every parameter and execute — the statement must be accepted."""
    backend = _backend_of(seeded)
    if backend in case.unsupported:
        pytest.skip(f"{backend}: {case.unsupported[backend]}")
    stmt = case.build() if case.build else None
    assert stmt is not None

    with Session(seeded) as session:
        rows = session.all_rows(stmt, case.bind())

    assert isinstance(rows, list)


@pytest.mark.parametrize("case", expressible(), ids=_ids)
def test_unbound_parameter_is_refused(case: CatalogCase, seeded: Any) -> None:
    """A statement must not run with a declared parameter left unbound.

    An unsupplied ``$parameter`` is a null in Cypher: it matches nothing and
    returns an empty result that looks exactly like an empty archive.  Failing
    loudly is the only way that distinction survives.
    """
    if not case.params:
        pytest.skip("statement binds no caller input")
    stmt = case.build() if case.build else None
    assert stmt is not None

    with Session(seeded) as session, pytest.raises(ValueError, match="missing values"):
        session.all_rows(stmt, {})


@pytest.mark.parametrize("case", expressible(), ids=_ids)
def test_bindings_cover_declared_parameters(case: CatalogCase) -> None:
    """Every declared parameter has a representative value.

    Guards the live suite against a statement that gains a parameter and then
    silently stops being executed with it bound.
    """
    assert set(case.bind()) == set(case.params)


def test_every_case_has_bindable_parameters() -> None:
    """Including the ones not yet expressible — bindings must not lag behind."""
    unbindable: dict[str, str] = {}
    for case in CATALOG_CASES:
        try:
            case.bind()
        except KeyError as exc:  # missing sample value
            unbindable[case.name] = str(exc)
    assert not unbindable, f"cases with unbindable parameters: {unbindable}"
