"""Filter, order, and aggregate expression objects for the query builder DSL.

Overview
--------
The expression layer lets you compose Cypher WHERE, ORDER BY, and RETURN
clauses from OGM field references without writing raw strings.  Expressions
are created by applying Python comparison operators to Node or Edge field
descriptors when they are accessed at the **class level**:

.. code-block:: python

    from myapp.models import User, Post, Rated

    # Equality / inequality
    User.name == "Alice"  # FilterExpr  → WHERE n.name = $p0
    User.status != "banned"  # FilterExpr  → WHERE n.status <> $p0

    # Numeric comparison
    User.age > 18  # FilterExpr  → WHERE n.age > $p0
    User.score >= 4.5  # FilterExpr  → WHERE n.score >= $p0

    # String predicates (method-style, not operator-style)
    User.name.contains("ali")  # FilterExpr  → WHERE n.name CONTAINS $p0
    User.email.startswith("a@")  # FilterExpr  → WHERE n.email STARTS WITH $p0
    User.bio.matches(r".*graph.*")  # FilterExpr → WHERE n.bio =~ $p0

    # Null checks
    User.deleted_at.is_null()  # FilterExpr  → WHERE n.deleted_at IS NULL
    User.email.is_not_null()  # FilterExpr  → WHERE n.email IS NOT NULL

    # List membership
    User.role.in_(["admin", "mod"])  # FilterExpr → WHERE n.role IN $p0
    Post.tag.not_in_(["spam"])  # FilterExpr → WHERE NOT n.tag IN $p0

    # Boolean composition
    (User.age > 18) & (User.active == True)  # AND
    (User.role == "admin") | (User.role == "mod")  # OR
    ~(User.banned == True)  # NOT

Notes
-----
- Operators are overloaded on :class:`~runic.ogm.core.descriptors.FieldDescriptor`,
  the internal backing object returned by class-level attribute access.
- ``__eq__`` is re-mapped to return a ``FilterExpr``; Python identity checks
  (``is``, ``is not``) are unaffected.
- ``FieldDescriptor.__hash__`` is preserved as the default ``object.__hash__``
  so descriptors remain hashable and usable in sets/dicts.
- TypeConverters (e.g. ``VectorConverter``, ``GeoLocationConverter``) are
  respected: the stored parameter value is converted via
  ``converter.to_graph()``; if the converter declares a ``cypher_fn``
  (e.g. ``"vecf32"``, ``"point"``), the Cypher expression wraps the param ref:
  ``vecf32($p0)`` instead of ``$p0``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Expr:
    """Abstract base for all filter/compound/negated expressions.

    Subclass instances are passed to :meth:`QueryBuilder.where`.  They support
    ``&`` (AND), ``|`` (OR), and ``~`` (NOT) to build composite predicates::

        q.where((User.age > 18) & (User.active == True))
    """

    def __and__(self, other: Expr) -> CompoundExpr:
        """Combine *self* and *other* with AND."""
        if isinstance(self, CompoundExpr) and self.op == "AND":
            return CompoundExpr(op="AND", operands=[*self.operands, other])
        return CompoundExpr(op="AND", operands=[self, other])

    def __or__(self, other: Expr) -> CompoundExpr:
        """Combine *self* and *other* with OR."""
        if isinstance(self, CompoundExpr) and self.op == "OR":
            return CompoundExpr(op="OR", operands=[*self.operands, other])
        return CompoundExpr(op="OR", operands=[self, other])

    def __invert__(self) -> NegatedExpr:
        """Negate this expression (NOT)."""
        return NegatedExpr(operand=self)


# ---------------------------------------------------------------------------
# FilterExpr
# ---------------------------------------------------------------------------


@dataclass
class FilterExpr(Expr):
    """A single WHERE predicate: ``alias.prop OP $pN``.

    Created automatically by the FieldDescriptor operator overloads; you do
    not normally instantiate this class directly.

    Attributes
    ----------
    cls:
        The OGM Node or Edge subclass that owns the field.  Used by the
        query builder to look up the Cypher variable (alias) for the class
        in the current query context.
    prop:
        The property name as declared on the OGM class.
    op:
        A Cypher operator string: ``"="``, ``"<>"``, ``">"``, ``">="``,
        ``"<"``, ``"<="``, ``"CONTAINS"``, ``"STARTS WITH"``, ``"=~"``
        (regex), ``"IN"``, ``"IS NULL"``, ``"IS NOT NULL"``.
    value:
        The Python value to compare against.  ``None`` for null-check ops.
        TypeConverter.to_graph() is applied during Cypher compilation if the
        field has a converter; ``cypher_fn`` wraps the param reference.
    alias:
        Optional explicit Cypher variable override (set via ``on=`` in
        :meth:`QueryBuilder.where`).  When ``None``, the builder derives the
        alias from *cls*.
    negate:
        When ``True``, wraps the predicate in ``NOT (...)``.  Used for
        ``not_in_()``; prefer the ``~`` operator for general negation.
    """

    cls: type
    prop: str
    op: str
    value: Any = None
    alias: str | None = None
    negate: bool = False

    def with_alias(self, alias: str) -> FilterExpr:
        """Return a copy of this expression with *alias* as the explicit variable."""
        return FilterExpr(
            cls=self.cls,
            prop=self.prop,
            op=self.op,
            value=self.value,
            alias=alias,
            negate=self.negate,
        )


# ---------------------------------------------------------------------------
# Compound and Negated
# ---------------------------------------------------------------------------


@dataclass
class CompoundExpr(Expr):
    """AND / OR combination of multiple sub-expressions.

    Example::

        (User.age > 18) & (User.active == True)
        # → CompoundExpr(op="AND", operands=[FilterExpr(...), FilterExpr(...)])
    """

    op: Literal["AND", "OR"]
    operands: list[Expr] = field(default_factory=list)


@dataclass
class NegatedExpr(Expr):
    """NOT wrapper around another expression.

    Example::

        ~(User.banned == True)
        # → NegatedExpr(operand=FilterExpr(...))
    """

    operand: Expr


# ---------------------------------------------------------------------------
# OrderExpr
# ---------------------------------------------------------------------------


@dataclass
class OrderExpr:
    """Represents a single ORDER BY term.

    Created by :meth:`QueryBuilder.order_by`; not usually instantiated directly.

    Attributes
    ----------
    alias:
        The Cypher variable (e.g. ``"n"``, ``"u"``).
    prop:
        The property name (e.g. ``"age"``).  ``None`` when *raw* is set.
    raw:
        A raw Cypher expression string (e.g. ``"score ASC"``).  Used when
        the user passes a string directly to ``order_by()``.
    desc:
        ``True`` for descending order; ``False`` (default) for ascending.
    """

    alias: str | None
    prop: str | None
    raw: str | None = None
    desc: bool = False

    def to_cypher(self) -> str:
        """Render to a Cypher ORDER BY term string."""
        if self.raw:
            return self.raw
        direction = "DESC" if self.desc else "ASC"
        return f"{self.alias}.{self.prop} {direction}"


# ---------------------------------------------------------------------------
# AggExpr and helpers
# ---------------------------------------------------------------------------


@dataclass
class AggExpr:
    """An aggregation function expression for use in RETURN clauses.

    Created via the helper functions :func:`count`, :func:`avg`, :func:`sum_`,
    :func:`min_`, :func:`max_`, :func:`collect`.

    Attributes
    ----------
    func:
        Cypher aggregation function name: ``"count"``, ``"avg"``, ``"sum"``,
        ``"min"``, ``"max"``, ``"collect"``.
    field:
        A :class:`~runic.ogm.core.descriptors.FieldDescriptor` or raw string
        (``"*"`` for ``count(*)``).
    result_alias:
        The ``AS name`` alias in the RETURN clause.
    distinct:
        When ``True``, emits ``count(DISTINCT n.prop)`` etc.
    """

    func: str
    field: Any = "*"
    result_alias: str | None = None
    distinct: bool = False

    def as_(self, alias: str) -> AggExpr:
        """Return a copy with a RETURN alias set."""
        return AggExpr(
            func=self.func,
            field=self.field,
            result_alias=alias,
            distinct=self.distinct,
        )

    def to_cypher(self, alias_map: dict[type, str]) -> str:
        """Render to a Cypher aggregation expression string.

        Parameters
        ----------
        alias_map:
            Mapping from OGM class to Cypher variable (provided by the builder
            during compilation).
        """
        from runic.ogm.core.descriptors import FieldDescriptor

        if isinstance(self.field, FieldDescriptor):
            cls_alias = alias_map.get(self.field.owner, "n")
            field_ref = f"{cls_alias}.{self.field.field_name}"
        elif self.field == "*":
            field_ref = "*"
        else:
            field_ref = str(self.field)

        distinct_kw = "DISTINCT " if self.distinct and self.field != "*" else ""
        expr = f"{self.func}({distinct_kw}{field_ref})"

        if self.result_alias:
            return f"{expr} AS {self.result_alias}"
        return expr


def count(field: Any = "*", *, distinct: bool = False) -> AggExpr:
    """Create a ``count(...)`` aggregation expression.

    Parameters
    ----------
    field:
        The field to count, or ``"*"`` (default) for ``count(*)``.
    distinct:
        When ``True``, emits ``count(DISTINCT field)``.

    Examples
    --------
    .. code-block:: python

        q.aggregate(count())  # count(*)
        q.aggregate(count(User.name, distinct=True))  # count(DISTINCT n.name)
    """
    return AggExpr(func="count", field=field, distinct=distinct)


def avg(field: Any) -> AggExpr:
    """Create an ``avg(...)`` aggregation expression.

    Example::

        q.aggregate(avg(User.age).as_("average_age"))
    """
    return AggExpr(func="avg", field=field)


def sum_(field: Any) -> AggExpr:
    """Create a ``sum(...)`` aggregation expression.

    Example::

        q.aggregate(sum_(Order.amount).as_("total"))
    """
    return AggExpr(func="sum", field=field)


def min_(field: Any) -> AggExpr:
    """Create a ``min(...)`` aggregation expression."""
    return AggExpr(func="min", field=field)


def max_(field: Any) -> AggExpr:
    """Create a ``max(...)`` aggregation expression."""
    return AggExpr(func="max", field=field)


def collect(field: Any, *, distinct: bool = False) -> AggExpr:
    """Create a ``collect(...)`` aggregation expression.

    Collects values from multiple rows into a list.

    Example::

        q.aggregate(collect(Post.title).as_("post_titles"))
    """
    return AggExpr(func="collect", field=field, distinct=distinct)
