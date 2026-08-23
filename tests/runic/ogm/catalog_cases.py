"""The 37 statements of the ``mailarc-analytics`` catalogue, as parity cases.

Each :class:`CatalogCase` names one Cypher constant from that project's
``queries/catalog.py`` and records what runic must be able to express to
replace it.  While a statement is not yet expressible, ``build`` is ``None`` and
``gaps`` names the capabilities that block it — the suite reports those as
expected failures, so the count of built statements is the burn-down chart for
this work package.

Parity is **semantic, not textual**: runic will not emit byte-identical Cypher
(parameter naming, clause spacing and alias choice all differ).  ``expect``
therefore holds the Cypher fragments that must appear, not a whole statement.

Gap identifiers (G1…G19) are defined in the plan and repeated here so a failing
case explains itself:

=====  =========================================================================
G1     Projection aliasing (``AS name``) and expression projection
G2     Named bound parameters, including ``LIMIT $limit``
G3     Field-to-field comparison (``a.id < b.id``)
G4     Reverse list membership (``$token IN m.refs``)
G5     Relationship type alternation (``[:SENT_TO|COPIED_TO]``)
G6     Traversal from an explicit source alias (fan-out)
G7     Rich ``WITH`` — ``ORDER BY`` / ``LIMIT`` inside, repeatable
G8     Conditional aggregation (``count(CASE WHEN … THEN 1 END)``)
G9     ``collect(DISTINCT alias.prop)`` over a traversal alias
G10    ``DELETE`` / ``DETACH DELETE`` over a matched set
G11    ``UNWIND $rows`` + node ``MERGE`` + ``SET``
G12    ``UNWIND`` + multi-pattern ``MATCH`` + edge ``MERGE`` + ``SET``
G13    Undirected ``MERGE``
G14    Bulk ``SET`` over a matched set
G15    Edge-rooted / anonymous-endpoint patterns
G16    Index-backed KNN, score exposure, ``$k`` distinct from ``$limit``
G17    Fulltext score exposure
G18    Correlated ``CALL`` after a ``MATCH``
G19    Runtime index DDL and index introspection
=====  =========================================================================
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CATALOG_CASES",
    "CatalogCase",
    "expressible",
    "operations",
    "statements",
    "unexpressible",
]


#: "Addressed" is defined as the walk over both types; matching them in two
#: separate patterns would double-count a message that used both.
ADDRESSED_TYPES = ["SENT_TO", "COPIED_TO"]

DEFAULT_PARAM_VALUES: Mapping[str, Any] = {
    # Cursors and paging. The cursor starts at "" so it is the exact complement
    # of the "no canonical id" filter, and the two still add up to every node.
    "after": "",
    "limit": 10,
    "batch": 100,
    "ids": ["m1", "m2"],
    # Thresholds
    "min_size": 2,
    "min_messages": 5,
    "direction": "sent",
    "max_distance": 0.35,
    # Semantic phase
    "model": "test-embedder",
    "max_chars": 2000,
    "k": 20,
    # Non-zero: Neo4j rejects a vector with no positive l2-norm.
    "vector": [0.1, 0.2, 0.3, 0.4],
    "text": "invoice",
    # Vector index options — the migration's own constants.
    "dimension": 4,
    "similarity": "cosine",
    "m": 16,
    "ef_construction": 200,
    "ef_runtime": 10,
}
"""Representative binding for each parameter name the catalogue uses."""


@dataclass(frozen=True)
class CatalogCase:
    """One catalogue statement and what runic must do to express it."""

    name: str
    """The constant's name in the source catalogue."""

    params: tuple[str, ...] = ()
    """Parameter names the statement binds. Checked once ``param()`` exists."""

    expect: tuple[str, ...] = ()
    """Cypher fragments that must appear in the built statement."""

    build: Callable[[], Any] | None = None
    """Returns the runic statement, or ``None`` while not yet expressible."""

    operation: Callable[[Any], Any] | None = None
    """Performs the statement's effect through an API rather than a statement.

    Index DDL is not a query, so it has no builder form and never will: it is
    reached through :class:`~runic.ogm.schema.runtime_index.IndexOperations`.
    Such a case is still *expressible in runic* — it simply is not a statement,
    and the live suite verifies it by running it and checking the effect.
    """

    gaps: tuple[str, ...] = field(default_factory=tuple)
    """Capability gaps blocking this statement. Empty once ``build`` is set."""

    unsupported: Mapping[str, str] = field(default_factory=dict)
    """Backends that reject this statement, mapped to why.

    Not a licence to skip: a statement lands here only when the backend cannot
    express it for a reason that is recorded and understood.  The live suite
    reports the reason rather than silently passing.
    """

    sample_params: Mapping[str, Any] = field(default_factory=dict)
    """Per-statement bindings that differ from :data:`DEFAULT_PARAM_VALUES`.

    ``$rows`` is always per-statement: a group row and an edge row share a
    parameter name and nothing else.
    """

    @property
    def is_expressible(self) -> bool:
        return self.build is not None or self.operation is not None

    @property
    def is_statement(self) -> bool:
        """Whether this is a builder statement, as opposed to an operation."""
        return self.build is not None

    def bind(self) -> dict[str, Any]:
        """Representative values for every parameter this statement declares.

        Used by the live suite to run each statement against a real backend —
        the only way a statement ever gets checked rather than merely read.
        """
        values: dict[str, Any] = {}
        for name in self.params:
            if name in self.sample_params:
                values[name] = self.sample_params[name]
            elif name in DEFAULT_PARAM_VALUES:
                values[name] = DEFAULT_PARAM_VALUES[name]
            else:
                raise KeyError(
                    f"{self.name}: no sample value for ${name}; add one to "
                    f"DEFAULT_PARAM_VALUES or the case's sample_params"
                )
        return values

    def reason(self) -> str:
        return f"{self.name}: needs {', '.join(self.gaps) or 'nothing'}"


def _load_cases() -> tuple[CatalogCase, ...]:
    """Import the case definitions.

    Deferred so :mod:`tests.runic.ogm.catalog_statements` can import
    :class:`CatalogCase` from here without a cycle.
    """
    from tests.runic.ogm.catalog_statements import ALL_CASES

    return ALL_CASES


CATALOG_CASES: tuple[CatalogCase, ...] = _load_cases()
"""Every catalogue statement, in source order.

Written out rather than scraped, for the reason the catalogue itself gives:
adding a statement without listing it is then visible in a diff.
"""


def expressible() -> tuple[CatalogCase, ...]:
    """Cases runic can express today, as a statement or an operation."""
    return tuple(c for c in CATALOG_CASES if c.is_expressible)


def statements() -> tuple[CatalogCase, ...]:
    """Cases that compile to a builder statement."""
    return tuple(c for c in CATALOG_CASES if c.is_statement)


def operations() -> tuple[CatalogCase, ...]:
    """Cases reached through an API rather than a statement (index DDL)."""
    return tuple(c for c in CATALOG_CASES if c.operation is not None)


def unexpressible() -> tuple[CatalogCase, ...]:
    """Cases still blocked on a capability gap."""
    return tuple(c for c in CATALOG_CASES if not c.is_expressible)
