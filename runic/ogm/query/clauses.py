"""Ordered clause objects for the query builder's middle section.

Why an ordered list
-------------------
A query's opening ``MATCH`` and its closing ``RETURN`` are fixed, but everything
between them has to appear in the order the caller wrote it.  ``WITH`` before a
traversal means something different from ``WITH`` after one:

.. code-block:: cypher

    MATCH (m:Message)
    WHERE m.id > $after
    WITH m ORDER BY m.id LIMIT $limit     -- take the page off the index first
    OPTIONAL MATCH (m)-[:SENT_TO]->(r:Address)
    RETURN m.id, collect(DISTINCT r.id)

Cutting the page *before* the expansions is the whole point: five optional
matches that cross-multiply are the expensive half of that statement, and a
``LIMIT`` at the end would pay for the entire archive's expansion in order to
keep one page.  A builder that always emitted ``WITH`` in the same position
could not express the difference.

So the builder holds these clauses in one list, in call order, and each renders
itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from runic.cypher import property_ref, validate_identifier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from runic.ogm.query.expressions import Expr, OrderExpr

log = logging.getLogger(__name__)

__all__ = [
    "CallClause",
    "Clause",
    "DeleteClause",
    "MatchClause",
    "MergeClause",
    "SetClause",
    "UnwindClause",
    "WithClause",
]


class Clause:
    """One clause in the pipeline between the opening MATCH and the RETURN."""

    def to_cypher(self, compiler: Any) -> str:
        """Render this clause, binding any operands via *compiler*."""
        raise NotImplementedError


@dataclass
class MatchClause(Clause):
    """One ``MATCH`` or ``OPTIONAL MATCH`` over a pattern.

    ``optional`` is a left join: source rows with no match survive, carrying
    nulls.  Like Cypher itself, ``OPTIONAL`` is the marked case — note that a
    ``WHERE`` on an optional match nullifies rows instead of dropping them.
    """

    pattern: str
    optional: bool = False
    requires: tuple[str, str] | None = None
    """``(feature, description)`` this pattern needs the backend to support.

    Checked when the clause renders rather than when it is built: a statement
    created by ``select()`` has no session yet, so the backend is unknown until
    the query is compiled for one.
    """

    def to_cypher(self, compiler: Any) -> str:
        if self.requires is not None:
            from runic.ogm.driver import require_feature

            feature, description = self.requires
            require_feature(compiler._dialect, feature, description)  # noqa: SLF001
        prefix = "OPTIONAL MATCH" if self.optional else "MATCH"
        return f"{prefix} {self.pattern}"


@dataclass
class WithClause(Clause):
    """A ``WITH`` stage: carry variables forward, optionally narrowing first.

    ``WITH`` is the only place Cypher lets a query order and cut *mid-flight*.
    Its own ``ORDER BY`` / ``LIMIT`` apply to the rows entering the next stage,
    which is what makes paging-before-expansion possible.

    Attributes
    ----------
    variables:
        Cypher variables (or rendered expressions) to carry forward.
    order_by:
        Sort applied to this stage, before its ``LIMIT``.  Paging without an
        order is undefined — two runs may return different pages.
    limit / skip:
        Row bounds for this stage. Integers or bound parameters.
    where:
        Predicates applied after the stage, which is how a computed or
        aggregated value gets filtered (Cypher's ``HAVING`` equivalent).
    distinct:
        Emit ``WITH DISTINCT``.
    """

    variables: tuple[Any, ...]
    order_by: Sequence[OrderExpr] = ()
    limit: Any = None
    skip: Any = None
    where: Sequence[Expr] = field(default_factory=tuple)
    distinct: bool = False

    def to_cypher(self, compiler: Any) -> str:
        rendered = [_render_variable(v, compiler) for v in self.variables]
        distinct_kw = "DISTINCT " if self.distinct else ""
        parts = [f"WITH {distinct_kw}{', '.join(rendered)}"]

        if self.order_by:
            terms = ", ".join(o.to_cypher(compiler) for o in self.order_by)
            parts.append(f"ORDER BY {terms}")
        for keyword, value in (("SKIP", self.skip), ("LIMIT", self.limit)):
            if value is not None:
                parts.append(f"{keyword} {_render_bound(value, compiler)}")
        if self.where:
            parts.append(f"WHERE {compiler._compile_and(list(self.where))}")  # noqa: SLF001

        return "\n".join(parts)


def _render_variable(value: Any, compiler: Any) -> str:
    """Render one item carried by a ``WITH``.

    A bare string is a Cypher variable and is validated as an identifier; a
    value expression or aggregate renders itself, so ``WITH m, count(r) AS n``
    is expressible.
    """
    from runic.ogm.query.expressions import AggExpr
    from runic.ogm.query.values import ValueExpr

    if isinstance(value, ValueExpr):
        return value.to_cypher(compiler)
    if isinstance(value, AggExpr):
        # A stage that aggregates is how a query filters on a computed value:
        # WITH m, count(r) AS n ... WHERE n > 1.
        return compiler._compile_agg(value, compiler._cls_alias_map())  # noqa: SLF001
    return validate_identifier(str(value), "WITH variable")


def _render_bound(value: Any, compiler: Any) -> str:
    """Render a row bound, which may be an integer or a bound parameter."""
    from runic.ogm.query.values import ValueExpr

    if isinstance(value, ValueExpr):
        return value.to_cypher(compiler)
    return str(int(value))


@dataclass
class UnwindClause(Clause):
    """``UNWIND $rows AS row`` — turn one list parameter into many rows.

    The shape every bulk write takes: one round trip carrying a list, expanded
    in the store into a row per entry, each driving a MERGE or a SET.  The
    alternative is a query per entity, which for a rebuild is the difference
    between one statement and a hundred thousand.
    """

    source: Any
    variable: str = "row"

    def __post_init__(self) -> None:
        validate_identifier(self.variable, "unwind variable")

    def to_cypher(self, compiler: Any) -> str:
        from runic.ogm.query.values import ValueExpr

        rendered = (
            self.source.to_cypher(compiler)
            if isinstance(self.source, ValueExpr)
            else f"${compiler._next_param(self.source)}"  # noqa: SLF001
        )
        return f"UNWIND {rendered} AS {self.variable}"


@dataclass
class MergeClause(Clause):
    """``MERGE`` a node or an edge — match it, or create it if absent.

    Idempotence is the reason this exists separately from ``CREATE``.  A derived
    label usually carries no unique constraint, so re-running a job that
    ``CREATE``d its output silently produces a second copy of every node, and
    every edge written afterwards is written twice.  ``MERGE`` on the key makes
    a second run change nothing.
    """

    pattern: str
    requires: tuple[str, str] | None = None

    def to_cypher(self, compiler: Any) -> str:
        if self.requires is not None:
            from runic.ogm.driver import require_feature

            feature, description = self.requires
            require_feature(compiler._dialect, feature, description)  # noqa: SLF001
        return f"MERGE {self.pattern}"


@dataclass
class SetClause(Clause):
    """``SET`` properties on an already-bound variable.

    Assignments are rendered through the mapper's property reference, so a
    dialect that wraps a field on the way in — ``vecf32``, ``point``,
    ``intern`` — still wraps it here.
    """

    assignments: tuple[tuple[str, str, Any], ...]
    """``(alias, property, value)`` triples."""

    def to_cypher(self, compiler: Any) -> str:
        parts = [
            f"{property_ref(alias, prop)} = "
            f"{_render_assignment(alias, prop, value, compiler)}"
            for alias, prop, value in self.assignments
        ]
        return f"SET {', '.join(parts)}"


@dataclass
class DeleteClause(Clause):
    """``DELETE`` or ``DETACH DELETE`` the named variables.

    ``detach`` also removes the edges incident to a node, which a node delete
    requires — Cypher refuses to delete a node that still has relationships.

    It is the wrong choice for an *edge*: detaching there would take the
    endpoints down with it, and on a derived edge between two ground-truth
    nodes that means deleting real data to clean up a computed one.
    """

    variables: tuple[str, ...]
    detach: bool = False

    def __post_init__(self) -> None:
        for variable in self.variables:
            validate_identifier(variable, "delete target")

    def to_cypher(self, compiler: Any) -> str:  # noqa: ARG002
        keyword = "DETACH DELETE" if self.detach else "DELETE"
        return f"{keyword} {', '.join(self.variables)}"


def _render_assignment(alias: str, prop: str, value: Any, compiler: Any) -> str:
    """Render the right-hand side of one ``SET`` assignment.

    ``None`` becomes the Cypher literal ``NULL`` rather than a bound parameter:
    ``SET n.p = $x`` with ``x`` bound to null does remove the property, but
    reads as an assignment of a value, and some backends treat the two
    differently. Clearing is stated outright.
    """
    from runic.ogm.query.values import ValueExpr

    if value is None:
        return "NULL"
    if isinstance(value, ValueExpr):
        rendered = value.to_cypher(compiler)
        fn = compiler._cypher_fn_for(alias, prop)  # noqa: SLF001
        return f"{fn}({rendered})" if fn else rendered
    param = compiler._next_param(compiler._convert_for(alias, prop, value))  # noqa: SLF001
    fn = compiler._cypher_fn_for(alias, prop)  # noqa: SLF001
    return f"{fn}(${param})" if fn else f"${param}"


@dataclass
class CallClause(Clause):
    """``CALL procedure(args) YIELD …`` — an index search or graph algorithm.

    Procedures are the one part of a query that cannot be expressed as a
    pattern, and index-backed search is the reason they matter here: a vector or
    fulltext index is only reachable through one.

    A procedure **cannot be narrowed before the fact**.  A ``MATCH`` above it
    does not restrict what it searches, so a filter after the ``YIELD`` drops
    rows the index already paid to find.  That is why an index search takes two
    numbers: how wide to search, and how many rows the caller wants.
    """

    procedure: str
    args: tuple[Any, ...] = ()
    yields: tuple[str, ...] = ()
    requires: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        for part in self.procedure.split("."):
            validate_identifier(part, "procedure name")

    def to_cypher(self, compiler: Any) -> str:
        if self.requires is not None:
            from runic.ogm.driver import require_feature

            feature, description = self.requires
            require_feature(compiler._dialect, feature, description)  # noqa: SLF001

        rendered = [_render_call_arg(a, compiler) for a in self.args]
        call = f"CALL {self.procedure}({', '.join(rendered)})"
        if self.yields:
            return f"{call} YIELD {', '.join(self.yields)}"
        return call


def _render_call_arg(value: Any, compiler: Any) -> str:
    """Render one procedure argument.

    A string is a literal name — an index or label the *model* names, not the
    caller — and is escaped as a Cypher string. Everything else is an
    expression or a bound value.
    """
    from runic.cypher import escape_string
    from runic.ogm.query.values import ValueExpr

    if isinstance(value, ValueExpr):
        return value.to_cypher(compiler)
    if isinstance(value, str):
        return escape_string(value)
    return f"${compiler._next_param(value)}"  # noqa: SLF001
