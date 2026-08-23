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

from runic.cypher import validate_identifier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from runic.ogm.query.expressions import Expr, OrderExpr

log = logging.getLogger(__name__)

__all__ = ["Clause", "MatchClause", "WithClause"]


class Clause:
    """One clause in the pipeline between the opening MATCH and the RETURN."""

    def to_cypher(self, compiler: Any) -> str:
        """Render this clause, binding any operands via *compiler*."""
        raise NotImplementedError


@dataclass
class MatchClause(Clause):
    """One ``MATCH`` or ``OPTIONAL MATCH`` over a pattern.

    ``optional`` is a left join: source rows with no match survive, carrying
    nulls.  That is the right default for reading a node's relationships, and
    the wrong one when a predicate on the traversed edge is supposed to *drop*
    rows — a ``WHERE`` on an optional match nullifies instead of filtering.
    """

    pattern: str
    optional: bool = True
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
