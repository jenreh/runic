"""Value expressions — anything that can stand where Cypher expects a value.

Overview
--------
:mod:`~runic.ogm.query.expressions` covers *predicates*: the things that go in a
``WHERE``.  This module covers *values*: the things a predicate compares, a
``RETURN`` projects, a ``SET`` assigns, and an ``ORDER BY`` sorts on.  One
hierarchy serves all four positions, so a property reference written once can be
projected, compared against another property, aliased, wrapped in a function, or
counted conditionally.

.. code-block:: python

    from runic.ogm.query import alias, count, left, param, row, when

    # A field is a value: project it, name it, wrap it in a function
    Message.subject.as_("subject")
    left(Message.body_clean, param("max_chars")).as_("body")

    # A caller-bound parameter, not an auto-numbered one
    Message.id > param("after")

    # Two properties compared against each other, which no $parameter can express
    a, b = alias(Address, "a"), alias(Address, "b")
    a.id < b.id

    # Conditional aggregation — one scan, several counts
    count(when(Message.embedding_model == param("model"), 1)).as_("embedded")

Named parameters
----------------
:func:`param` declares a parameter instead of binding a value.  It compiles to
``$name`` and is recorded on the statement, so
:meth:`~runic.ogm.query.builder.QueryBuilder.parameter_names` can report what a
statement expects and the session can refuse to run one with a parameter
missing.  This is what lets a statement be a module-level constant that callers
supply values to, rather than a query built per call:

.. code-block:: python

    RECENT_MESSAGES: Final = (
        select(Message).where(Message.id > param("after")).limit(param("limit"))
    )

    rows = session.scalars(RECENT_MESSAGES, {"after": cursor, "limit": 500})

Everything else is bound automatically as ``$p0``, ``$p1``, … — a Python value
reaching any of these constructors becomes a parameter, never text spliced into
the query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload

from runic.cypher import escape_identifier, property_ref, validate_identifier
from runic.ogm.query.expressions import Expr, FilterExpr

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from runic.ogm.core.descriptors import FieldDescriptor

log = logging.getLogger(__name__)

__all__ = [
    "Alias",
    "AliasedExpr",
    "CaseExpr",
    "FnCall",
    "LiteralValue",
    "ParamRef",
    "PropertyRef",
    "RowRef",
    "ValueExpr",
    "alias",
    "coalesce",
    "col",
    "encode_rows",
    "fn",
    "left",
    "literal",
    "param",
    "row",
    "score",
    "to_lower",
    "to_upper",
    "var",
    "when",
]


class ValueExpr:
    """Abstract base for expressions that render to a Cypher *value*.

    Subclasses implement :meth:`to_cypher`, which receives the query builder
    doing the compiling so operands can be bound as parameters rather than
    interpolated.

    Comparison operators produce a
    :class:`~runic.ogm.query.expressions.FilterExpr` usable in ``where()``, so
    ``col("a", Address.id) < col("b", Address.id)`` reads the way the Cypher
    does.
    """

    def to_cypher(self, compiler: Any) -> str:
        """Render to a Cypher fragment, binding operands via *compiler*."""
        raise NotImplementedError

    def referenced_aliases(self, compiler: Any) -> set[str]:  # noqa: ARG002
        """The Cypher variables this expression reads.

        The builder uses this to decide where a predicate may be emitted: one
        naming a variable that a later ``MATCH`` introduces cannot precede it.
        A parameter or a literal reads nothing, so it constrains nothing.
        """
        return set()

    def as_(self, alias: str) -> AliasedExpr:
        """Give this expression a ``AS alias`` name in the RETURN clause."""
        return AliasedExpr(expr=self, alias=validate_identifier(alias, "result alias"))

    # -- comparison, producing predicates -------------------------------

    def _compare(self, op: str, other: Any) -> FilterExpr:
        return FilterExpr(cls=type(self), prop="", op=op, value=other, left=self)

    def __eq__(self, other: object) -> Any:  # type: ignore[override]
        if other is None:
            return self._compare("IS NULL", None)
        return self._compare("=", other)

    def __ne__(self, other: object) -> Any:  # type: ignore[override]
        if other is None:
            return self._compare("IS NOT NULL", None)
        return self._compare("<>", other)

    def __gt__(self, other: Any) -> FilterExpr:
        return self._compare(">", other)

    def __ge__(self, other: Any) -> FilterExpr:
        return self._compare(">=", other)

    def __lt__(self, other: Any) -> FilterExpr:
        return self._compare("<", other)

    def __le__(self, other: Any) -> FilterExpr:
        return self._compare("<=", other)

    # -- predicate helpers, mirroring FieldDescriptor's ------------------

    def is_null(self) -> FilterExpr:
        """``IS NULL`` predicate."""
        return self._compare("IS NULL", None)

    def is_not_null(self) -> FilterExpr:
        """``IS NOT NULL`` predicate."""
        return self._compare("IS NOT NULL", None)

    def contains(self, value: Any) -> FilterExpr:
        """``CONTAINS`` predicate."""
        return self._compare("CONTAINS", value)

    def startswith(self, value: Any) -> FilterExpr:
        """``STARTS WITH`` predicate."""
        return self._compare("STARTS WITH", value)

    def endswith(self, value: Any) -> FilterExpr:
        """``ENDS WITH`` predicate."""
        return self._compare("ENDS WITH", value)

    def matches(self, pattern: Any) -> FilterExpr:
        """Regex predicate: ``=~``."""
        return self._compare("=~", pattern)

    def in_(self, values: Any) -> FilterExpr:
        """``IN`` predicate: is this value one of *values*?"""
        return self._compare("IN", values)

    def not_in_(self, values: Any) -> FilterExpr:
        """``NOT … IN`` predicate."""
        return FilterExpr(
            cls=type(self), prop="", op="IN", value=values, left=self, negate=True
        )

    def any_of(self, value: Any) -> FilterExpr:
        """Membership against a **list-valued** expression: ``$value IN expr``."""
        return FilterExpr(
            cls=type(self), prop="", op="IN", value=value, left=self, reverse=True
        )

    __hash__ = object.__hash__


@dataclass(eq=False)
class PropertyRef(ValueExpr):
    """A property on a specific Cypher variable: ``alias.prop``.

    The alias is explicit, which is what makes a self-join expressible: the same
    Node class can appear under two variables and be compared against itself.
    """

    alias: str
    prop: str
    owner: type | None = None

    def to_cypher(self, compiler: Any) -> str:
        alias = self._resolve_alias(compiler)
        return property_ref(alias, self.prop) if self.prop else alias

    def referenced_aliases(self, compiler: Any) -> set[str]:
        return {self._resolve_alias(compiler)}

    def _resolve_alias(self, compiler: Any) -> str:
        """Pin the Cypher variable, deferring to the builder when unset.

        ``col(Message.id)`` does not know which variable the builder gave
        ``Message`` — that is only decided once the statement is compiled.
        """
        if self.alias != _DEFERRED_ALIAS:
            return self.alias
        if self.owner is not None:
            return compiler._alias_for_cls(self.owner)  # noqa: SLF001
        return compiler._root_alias  # noqa: SLF001


class Alias(ValueExpr):
    """A named Cypher variable bound to a model class.

    Created by :func:`alias`.  A handle is both things a variable is in
    Cypher: used bare it *is* the variable (``project(m)`` → ``RETURN m``),
    and attribute access reaches its properties (``m.id`` → ``m.id``).

    The same class under two handles is what makes a self-join readable::

        a, b = alias(Address, "a"), alias(Address, "b")
        select(a).traverse(a.co_addressed, to=b).where(a.id < b.id)
    """

    # Private storage: attribute access is the API (m.id → m.id), so the
    # handle's own state must not shadow a model field — "name" would.
    __slots__ = ("_cls", "_name")

    _name: str
    _cls: type

    def __init__(self, name: str, cls: type) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_cls", cls)

    def to_cypher(self, compiler: Any) -> str:  # noqa: ARG002
        return self._name

    def referenced_aliases(self, compiler: Any) -> set[str]:  # noqa: ARG002
        return {self._name}

    def __getattr__(self, item: str) -> PropertyRef:
        if item.startswith("_"):
            raise AttributeError(item)
        from runic.ogm.core.descriptors import FieldDescriptor

        cls: type = object.__getattribute__(self, "_cls")
        descriptor = getattr(cls, item, None)
        if not isinstance(descriptor, FieldDescriptor):
            msg = f"{cls.__name__!r} has no field {item!r}"
            raise AttributeError(msg)
        return PropertyRef(
            alias=self._name, prop=descriptor.field_name, owner=descriptor.owner
        )

    def __repr__(self) -> str:
        return f"Alias({self._name!r}, {self._cls.__name__})"


def alias(cls: type, name: str) -> Alias:
    """Bind *cls* to a named Cypher variable and return the handle.

    The handle replaces alias strings everywhere: ``select(m)`` names the
    root, ``traverse(…, to=r)`` names a traversal target, ``m.id`` references
    a property on it, ``project(m)`` returns it whole.

    Example::

        m, r = alias(Message, "m"), alias(Address, "r")
        select(m).traverse(Message.sent_to, from_=m, to=r).where(m.id > r.id)
    """
    return Alias(validate_identifier(name, "alias"), cls)


@dataclass(eq=False)
class ParamRef(ValueExpr):
    """A named parameter the caller binds at execution: ``$name``.

    Declaring rather than binding is the point — the statement can be a
    module-level constant and the value arrives per call.
    """

    name: str

    def __post_init__(self) -> None:
        validate_identifier(self.name, "parameter name")

    def to_cypher(self, compiler: Any) -> str:
        compiler.declare_param(self.name)
        return f"${self.name}"


@dataclass(eq=False)
class LiteralValue(ValueExpr):
    """A Python value, bound as an auto-numbered parameter.

    Never interpolated: a literal in an expression tree still reaches the graph
    as ``$pN``.
    """

    value: Any

    def to_cypher(self, compiler: Any) -> str:
        return f"${compiler._next_param(self.value)}"  # noqa: SLF001


@dataclass(eq=False)
class RowRef(ValueExpr):
    """A key of the loop variable introduced by ``UNWIND``: ``row.key``.

    Used by bulk writes, where each ``$rows`` entry supplies the properties for
    one node or edge.
    """

    key: str
    var: str = "row"

    def __post_init__(self) -> None:
        validate_identifier(self.key, "row key")
        validate_identifier(self.var, "unwind variable")

    def to_cypher(self, compiler: Any) -> str:  # noqa: ARG002
        return property_ref(self.var, self.key)


@dataclass(eq=False)
class FnCall(ValueExpr):
    """A scalar function call: ``name(arg, …)``.

    Arguments are themselves value expressions, so a function's operands are
    bound like any other value.  The function *name* is validated as an
    identifier — it is the one part that must be interpolated.
    """

    name: str
    args: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.name, "function name")

    def to_cypher(self, compiler: Any) -> str:
        rendered = [_render(a, compiler) for a in self.args]
        return f"{self.name}({', '.join(rendered)})"

    def referenced_aliases(self, compiler: Any) -> set[str]:
        return _aliases_of(self.args, compiler)


@dataclass(eq=False)
class CaseExpr(ValueExpr):
    """A ``CASE WHEN … THEN … [ELSE …] END`` expression.

    Its reason for existing is conditional aggregation: several differently
    filtered counts over one scan, which is otherwise several queries whose
    populations can disagree.
    """

    branches: tuple[tuple[Expr, Any], ...]
    else_value: Any = None
    has_else: bool = False

    def to_cypher(self, compiler: Any) -> str:
        parts = ["CASE"]
        for condition, value in self.branches:
            rendered_when = compiler._compile_expr(condition)  # noqa: SLF001
            parts.append(f"WHEN {rendered_when} THEN {_render(value, compiler)}")
        if self.has_else:
            parts.append(f"ELSE {_render(self.else_value, compiler)}")
        parts.append("END")
        return " ".join(parts)

    def referenced_aliases(self, compiler: Any) -> set[str]:
        found: set[str] = set()
        for condition, value in self.branches:
            found |= compiler._expr_aliases(condition)  # noqa: SLF001
            found |= _aliases_of((value,), compiler)
        if self.has_else:
            found |= _aliases_of((self.else_value,), compiler)
        return found


@dataclass(eq=False)
class AliasedExpr(ValueExpr):
    """An expression with a ``AS alias`` name for the RETURN clause."""

    expr: ValueExpr
    alias: str

    def to_cypher(self, compiler: Any) -> str:
        return f"{self.expr.to_cypher(compiler)} AS {escape_identifier(self.alias)}"

    def referenced_aliases(self, compiler: Any) -> set[str]:
        return self.expr.referenced_aliases(compiler)

    @property
    def result_name(self) -> str:
        """The column name this expression produces."""
        return self.alias


# ---------------------------------------------------------------------------
# Rendering helper
# ---------------------------------------------------------------------------


def _prop_ref(descriptor: Any) -> PropertyRef:
    """Wrap a bare field descriptor as a deferred-alias property reference.

    The internal counterpart of writing ``Message.id`` in a query: the Cypher
    variable is resolved from the owning class at compile time.
    """
    return PropertyRef(
        alias=_DEFERRED_ALIAS, prop=descriptor.field_name, owner=descriptor.owner
    )


def _aliases_of(values: tuple[Any, ...], compiler: Any) -> set[str]:
    """Union the Cypher variables read by a tuple of operands."""
    from runic.ogm.core.descriptors import FieldDescriptor

    found: set[str] = set()
    for value in values:
        if isinstance(value, ValueExpr):
            found |= value.referenced_aliases(compiler)
        elif isinstance(value, FieldDescriptor):
            found |= _prop_ref(value).referenced_aliases(compiler)
    return found


def _render(value: Any, compiler: Any) -> str:
    """Render *value* as a Cypher fragment, binding it if it is a plain value.

    The single chokepoint through which every operand passes, so a Python value
    anywhere in an expression tree becomes a parameter rather than text.
    """
    from runic.ogm.core.descriptors import FieldDescriptor

    if isinstance(value, ValueExpr):
        return value.to_cypher(compiler)
    if isinstance(value, FieldDescriptor):
        return _prop_ref(value).to_cypher(compiler)
    return f"${compiler._next_param(value)}"  # noqa: SLF001


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


@overload
def col(field: FieldDescriptor, on: str) -> PropertyRef: ...


@overload
def col(field: str, on: FieldDescriptor) -> PropertyRef: ...


def col(field: Any, on: Any = None) -> PropertyRef:
    """Pin a property to a named Cypher variable.

    The one-off form of an :func:`alias` handle: ``col("m", Message.id)`` (or
    ``col(Message.id, "m")``) reads ``m.id``.  Prefer a handle when the
    variable is referenced more than once — ``m = alias(Message, "m")`` then
    ``m.id``.

    For the builder-assigned default variable no wrapper is needed at all:
    pass the bare descriptor (``Message.id``) anywhere a value is expected.
    """
    from runic.ogm.core.descriptors import FieldDescriptor

    # Alias-first form: col("a", Address.id)
    if isinstance(field, str) and isinstance(on, FieldDescriptor):
        pinned, descriptor = field, on
        return PropertyRef(
            alias=pinned, prop=descriptor.field_name, owner=descriptor.owner
        )

    # Descriptor-first form: col(Address.id, "a")
    if isinstance(field, FieldDescriptor) and isinstance(on, str):
        return PropertyRef(alias=on, prop=field.field_name, owner=field.owner)

    if isinstance(field, FieldDescriptor) and on is None:
        msg = (
            "col() pins a property to a named variable and needs both: "
            "col('m', Model.field). For the default variable, pass the bare "
            "descriptor (Model.field) instead — no wrapper needed."
        )
        raise TypeError(msg)

    msg = (
        "col() takes an alias and a field descriptor: col('alias', Model.field) "
        "or col(Model.field, 'alias')."
    )
    raise TypeError(msg)


#: Sentinel alias meaning "resolve from the owning class at compile time".
_DEFERRED_ALIAS = "\x00deferred"


def param(name: str) -> ParamRef:
    """Declare a parameter the caller binds at execution time.

    Example::

        select(Message).where(Message.id > param("after")).limit(param("limit"))
    """
    return ParamRef(name=name)


def literal(value: Any) -> LiteralValue:
    """Bind a Python value as a parameter inside an expression tree."""
    return LiteralValue(value=value)


def row(key: str, *, var: str = "row") -> RowRef:
    """Reference a key of the ``UNWIND`` loop variable: ``row.key``."""
    return RowRef(key=key, var=var)


def fn(name: str, *args: Any) -> FnCall:
    """Call a scalar Cypher function with bound arguments.

    Example::

        fn("left", col(Message.body_clean), param("max_chars"))
    """
    return FnCall(name=name, args=args)


def left(value: Any, length: Any) -> FnCall:
    """``left(value, length)`` — truncate in the store, not in Python."""
    return FnCall(name="left", args=(value, length))


def coalesce(*values: Any) -> FnCall:
    """``coalesce(a, b, …)`` — first non-null argument."""
    return FnCall(name="coalesce", args=values)


def to_lower(value: Any) -> FnCall:
    """``toLower(value)``."""
    return FnCall(name="toLower", args=(value,))


def to_upper(value: Any) -> FnCall:
    """``toUpper(value)``."""
    return FnCall(name="toUpper", args=(value,))


def var(name: str) -> PropertyRef:
    """Reference a bare Cypher variable by name.

    For values a query introduces that no model declares — what a procedure
    yields, or a name bound by an earlier ``WITH`` stage::

        .call("db.idx.vector.queryNodes", …, yields=["node", "score"])
        .where(var("score") <= param("max_distance"))
    """
    return PropertyRef(alias=validate_identifier(name, "variable"), prop="")


def score() -> PropertyRef:
    """The score a search procedure yielded, for projecting or filtering.

    Its meaning depends on which search produced it, and the two conventions
    are opposite:

    * a **vector** search yields a distance — lower is closer;
    * a **fulltext** search yields a relevance — higher is better.

    They are not comparable. Merging both into one ranking without a stated
    normalisation invents an ordering neither index produced.

    Example::

        session.vector_search(...).project(score().as_("distance"))
    """
    return PropertyRef(alias="__score", prop="", owner=None)


def when(
    condition: Expr,
    then: Any,
    *more: Any,
    else_: Any = None,
    has_else: bool = False,
) -> CaseExpr:
    """Build a ``CASE WHEN`` expression.

    Pass additional ``condition, value`` pairs positionally for more branches.
    ``else_`` is only emitted when *has_else* is set, so ``ELSE null`` — which
    ``count()`` skips and ``collect()`` does not — is never emitted by accident.

    Example::

        count(when(Message.embedding_model == param("model"), 1)).as_("embedded")
    """
    if len(more) % 2:
        msg = "when() takes condition/value pairs; got an odd number of extra args"
        raise ValueError(msg)
    branches: list[tuple[Expr, Any]] = [(condition, then)]
    branches.extend((more[i], more[i + 1]) for i in range(0, len(more), 2))
    return CaseExpr(
        branches=tuple(branches),
        else_value=else_,
        has_else=has_else or else_ is not None,
    )


# ---------------------------------------------------------------------------
# Row encoding
# ---------------------------------------------------------------------------


def encode_rows(
    cls: type, rows: Iterable[Mapping[str, Any]], *, metadata: Any = None
) -> list[dict[str, Any]]:
    """Apply *cls*'s field converters across a list of ``$rows`` payload dicts.

    A bulk write sends its values inside one ``$rows`` parameter, so they never
    pass through the mapper that converts a property on a single entity.  A
    ``datetime`` in such a payload would reach the driver as an object it has no
    encoding for — this applies the same conversions the mapper would, keyed by
    field name, and leaves unrecognised keys untouched.

    Keys that are not fields of *cls* are passed through unchanged: a row for an
    edge upsert carries ``message_id`` and ``group_id`` alongside the edge's own
    properties.

    Example
    -------
    .. code-block:: python

        session.execute_write(MERGE_GROUPS, {"rows": encode_rows(Group, group_rows)})
    """
    from runic.ogm.core.metadata import metadata as _global_metadata

    meta = metadata or _global_metadata
    node_meta = meta.get_node_meta(cls) or meta.get_edge_meta(cls)
    converters: dict[str, Any] = {}
    if node_meta is not None:
        for fi in node_meta.fields:
            converter = getattr(fi.field, "converter", None)
            if converter is not None:
                converters[fi.name] = converter

    encoded: list[dict[str, Any]] = []
    for source in rows:
        out: dict[str, Any] = {}
        for key, value in source.items():
            converter = converters.get(key)
            out[key] = (
                converter.to_graph(value) if converter and value is not None else value
            )
        encoded.append(out)
    return encoded
