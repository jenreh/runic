"""Catalogue parity: can runic's builder express a real statement catalogue?

The reference is ``mailarc-analytics``' ``queries/catalog.py`` — 37 Cypher
constants whose module docstring argues, statement by statement, that runic's
query builder cannot express them.  Each is encoded as a
:class:`~tests.runic.ogm.catalog_cases.CatalogCase`; this module builds the ones
that are expressible and reports the rest as expected failures naming the gap.

The count of built statements is the burn-down chart for this work package, so
:func:`test_burndown` prints it on every run.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.mapper.mapper import Mapper
from tests.runic.ogm.catalog_cases import (
    CATALOG_CASES,
    CatalogCase,
    expressible,
    operations,
    statements,
    unexpressible,
)

log = logging.getLogger(__name__)

_real_meta.finalize()

_TOTAL = len(CATALOG_CASES)


def _mock_session() -> Any:
    """A MagicMock session wired to the real MetaData and Mapper.

    Mirrors ``test_builder._mock_session``; parity assertions are about emitted
    Cypher, so no live backend is involved.
    """
    mapper = Mapper(_real_meta)
    sess = MagicMock()
    sess._mapper = mapper
    sess.mapper = mapper
    sess.register_or_get = lambda e: e
    return sess


#: The unit suite compiles against FalkorDB — the backend the reference
#: catalogue itself targets, and the one whose ``vecf32`` wrapping the expected
#: fragments assume.
_UNIT_BACKEND = "falkordb"


def _build(case: CatalogCase) -> tuple[str, dict[str, Any]]:
    """Compile *case* to ``(cypher, params)`` against a mock session."""
    assert case.build is not None  # guarded by the caller
    stmt = case.build()
    with stmt._bound_to(_mock_session()) as bound:
        return bound.build()


def _skip_if_unsupported(case: CatalogCase) -> None:
    """Skip a case the compiling backend has a recorded reason to reject."""
    if _UNIT_BACKEND in case.unsupported:
        pytest.skip(f"{_UNIT_BACKEND}: {case.unsupported[_UNIT_BACKEND]}")


# ---------------------------------------------------------------------------
# Structure of the case table itself
# ---------------------------------------------------------------------------


class TestCaseTable:
    def test_every_statement_is_listed(self) -> None:
        """The catalogue has 37 statements; so must this table."""
        assert _TOTAL == 37

    def test_names_are_unique(self) -> None:
        names = [c.name for c in CATALOG_CASES]
        assert len(set(names)) == len(names)

    def test_buildable_cases_declare_no_gaps(self) -> None:
        """A case that builds has nothing left blocking it."""
        leftovers = {c.name: c.gaps for c in expressible() if c.gaps}
        assert not leftovers, f"buildable cases still naming gaps: {leftovers}"

    def test_blocked_cases_name_their_gap(self) -> None:
        """An unbuildable case must say what it is waiting for."""
        silent = [c.name for c in unexpressible() if not c.gaps]
        assert not silent, f"blocked cases with no stated gap: {silent}"


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", statements(), ids=lambda c: c.name if isinstance(c, CatalogCase) else ""
)
class TestExpressible:
    def test_emits_expected_fragments(self, case: CatalogCase) -> None:
        _skip_if_unsupported(case)
        cypher, _ = _build(case)
        missing = [frag for frag in case.expect if frag not in cypher]
        assert not missing, (
            f"{case.name}: missing {missing} from generated Cypher:\n{cypher}"
        )

    def test_declares_expected_parameters(self, case: CatalogCase) -> None:
        """Named parameters are the catalogue's whole security contract.

        Skipped until ``param()`` and ``parameter_names()`` land (phase 1); the
        statements buildable before then bind no caller input at all.
        """
        stmt = case.build() if case.build else None
        if stmt is None or not hasattr(stmt, "parameter_names"):
            pytest.skip("named parameters not implemented yet")
        assert set(stmt.parameter_names()) == set(case.params)

    def test_no_value_is_interpolated(self, case: CatalogCase) -> None:
        """Every bound value reaches the graph as a parameter, never as text."""
        _skip_if_unsupported(case)
        cypher, params = _build(case)
        for name, value in params.items():
            if isinstance(value, str) and value:
                assert value not in cypher, (
                    f"{case.name}: value of ${name} was interpolated into Cypher"
                )


@pytest.mark.parametrize(
    "case", unexpressible(), ids=lambda c: c.name if isinstance(c, CatalogCase) else ""
)
def test_not_yet_expressible(case: CatalogCase) -> None:
    """Placeholder for a statement the builder cannot yet produce.

    Fails once ``build`` is filled in, which is the signal to drop the case out
    of this parametrisation and into :class:`TestExpressible`.
    """
    pytest.xfail(case.reason())


def test_index_ddl_is_reachable() -> None:
    """DDL is not a query, so it is an operation rather than a statement.

    Still expressible in runic — through
    :class:`~runic.ogm.schema.runtime_index.IndexOperations` — which the live
    suite runs against a real backend.
    """
    from runic.ogm.schema.runtime_index import IndexOperations

    assert operations(), "index DDL cases should be reachable"
    for case in operations():
        assert case.operation is not None
        assert not case.gaps, f"{case.name} still names a gap"
    for name in ("create_vector_index", "drop_vector_index", "describe"):
        assert hasattr(IndexOperations, name)


def test_burndown() -> None:
    """Report progress: how many catalogue statements runic can express."""
    built = len(expressible())
    blocked = sorted({gap for c in unexpressible() for gap in c.gaps})
    log.info("catalogue parity: %d/%d statements built", built, _TOTAL)
    log.info("outstanding gaps: %s", ", ".join(blocked) or "none")
    assert built + len(unexpressible()) == _TOTAL


# ---------------------------------------------------------------------------
# The catalogue's first premise: no free Cypher from outside
# ---------------------------------------------------------------------------


_INJECTIONS = [
    "n.id DESC WITH n MATCH (x) DETACH DELETE x //",
    "n) DETACH DELETE n RETURN count(*",
    "n.id, count(*)",
    "n.id ASC, m.id DESC",
]


class TestNoFreeCypher:
    """The raw-string escape hatches must not accept a second clause.

    ``project()``, ``order_by()`` and the aggregate helpers interpolate raw
    strings into RETURN and ORDER BY.  A caller-supplied value reaching one of
    them would otherwise execute as Cypher — which is precisely the property a
    statement catalogue exists to guarantee, so it is asserted here.
    """

    @pytest.mark.parametrize("payload", _INJECTIONS)
    def test_order_by_rejects_injection(self, payload: str) -> None:
        from runic.ogm import select
        from tests.runic.ogm.catalog_models import Message

        with pytest.raises(ValueError, match="order_by term"):
            select(Message).order_by(payload)

    @pytest.mark.parametrize("payload", _INJECTIONS)
    def test_projection_rejects_injection(self, payload: str) -> None:
        from runic.ogm import select
        from tests.runic.ogm.catalog_models import Message

        with pytest.raises(ValueError, match="projection"):
            select(Message).project(payload)

    @pytest.mark.parametrize("payload", _INJECTIONS)
    def test_aggregate_operand_rejects_injection(self, payload: str) -> None:
        from runic.ogm import select
        from runic.ogm.query.expressions import count
        from tests.runic.ogm.catalog_models import Message

        stmt = select(Message).project(count(payload).as_("t"))
        with pytest.raises(ValueError, match="aggregate operand"):
            _build(CatalogCase(name="injection-probe", build=lambda: stmt))

    def test_legitimate_raw_strings_still_work(self) -> None:
        """The escape hatch stays usable for what it was for."""
        from runic.ogm import select
        from runic.ogm.query.expressions import count
        from tests.runic.ogm.catalog_models import Message

        stmt = (
            select(Message)
            .project("n.subject", count("*").as_("total"))
            .order_by("total DESC")
        )
        cypher, _ = _build(CatalogCase(name="raw-ok", build=lambda: stmt))
        assert "RETURN n.subject, count(*) AS total" in cypher
        assert "ORDER BY total DESC" in cypher
