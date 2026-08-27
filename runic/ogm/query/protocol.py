"""The compilation interface clauses and value expressions render against.

Why a Protocol
--------------
A :class:`~runic.ogm.query.clauses.Clause` or
:class:`~runic.ogm.query.values.ValueExpr` renders itself, but it cannot render
alone: it needs somewhere to bind a parameter, the Cypher variable a class was
given, and the dialect's opinion on how a property is written.  It gets those
from the object doing the compiling — the
:class:`~runic.ogm.query.builder.QueryBuilder`, via
:class:`~runic.ogm.query._compiler._CypherCompiler`.

Naming that dependency structurally is what keeps it honest.  Without it the
render methods take an untyped builder and reach into whatever they need, so a
rename inside the compiler breaks siblings the type checker never looked at.
:class:`CompilationContext` is the whole of what a renderer may use, and the
compiler implements it — everything else on the builder stays its own business.

Custom renderers type against it too::

    from runic.ogm.query import CompilationContext, ValueExpr


    class Haversine(ValueExpr):
        def __init__(self, left: ValueExpr, right: ValueExpr) -> None:
            self.left, self.right = left, right

        def to_cypher(self, compiler: CompilationContext) -> str:
            a = self.left.to_cypher(compiler)
            b = self.right.to_cypher(compiler)
            return f"point.distance({a}, {b})"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from runic.ogm.query.expressions import AggExpr, Expr

__all__ = ["CompilationContext"]


@runtime_checkable
class CompilationContext(Protocol):  # pragma: no cover
    """What a clause or value expression may use while rendering itself.

    Implemented by :class:`~runic.ogm.query._compiler._CypherCompiler`, and so
    by every :class:`~runic.ogm.query.builder.QueryBuilder`.

    Runtime-checkable, which for a Protocol means ``isinstance`` verifies that
    the members are *present* — not that their signatures match.  Every member
    below is therefore declared at class level, since that is all the runtime
    check can see.
    """

    root_alias: str
    """The Cypher variable bound to the statement's root class."""

    params: dict[str, Any]
    """Values bound so far, keyed by parameter name."""

    @property
    def dialect(self) -> Any:
        """The bound backend's dialect, or ``None`` on an unbound statement."""
        ...

    # -- parameters -----------------------------------------------------

    def bind_param(self, value: Any) -> str:
        """Bind *value* under a fresh auto-numbered name and return the name."""
        ...

    def declare_param(self, name: str) -> str:
        """Record a caller-bound parameter, binding no value, and return *name*."""
        ...

    # -- aliases --------------------------------------------------------

    def alias_for_cls(self, cls: type) -> str:
        """The Cypher variable *cls* was given."""
        ...

    def cls_alias_map(self) -> dict[type, str]:
        """First registered Cypher variable per class, for aggregates."""
        ...

    def expr_aliases(self, expr: Expr) -> set[str]:
        """The Cypher variables *expr* reads."""
        ...

    # -- rendering ------------------------------------------------------

    def compile_expr(self, expr: Expr) -> str:
        """Render one predicate expression tree."""
        ...

    def compile_and(self, exprs: list[Expr]) -> str:
        """Render several predicates as a single AND-joined condition."""
        ...

    def compile_agg(self, agg: AggExpr, cls_to_alias: dict[type, str]) -> str:
        """Render one aggregation, whose operand may itself be an expression."""
        ...

    # -- field-aware writing --------------------------------------------

    def cypher_fn_for(self, alias: str, prop: str) -> str | None:
        """The dialect's wrapping function for a property, if it declares one."""
        ...

    def convert_for(self, alias: str, prop: str, value: Any) -> Any:
        """Apply a field's ``TypeConverter`` to a value being written."""
        ...
