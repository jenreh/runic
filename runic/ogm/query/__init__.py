"""runic.ogm.query — fluent query builder for FalkorDB graph queries.

Public API
----------
The preferred entry point for composable, session-independent statements:

- :func:`select` → :class:`QueryBuilder` (session-free, executed via session)

Session/repository bound entry points (backward compatible):

- :meth:`~runic.ogm.session.session.Session.query` → :class:`QueryBuilder`
- :meth:`~runic.ogm.session.session.Session.fulltext_search` → :class:`FulltextQueryBuilder`
- :meth:`~runic.ogm.session.session.Session.vector_search` → :class:`VectorQueryBuilder`
- :meth:`~runic.ogm.repository.repository.Repository.query` → :class:`QueryBuilder`

Expression helpers imported here for convenience::

    from runic.ogm.query import count, avg, sum_, min_, max_, collect

Refer to :mod:`runic.ogm.query.builder` for the full API reference.
"""

from typing import TypeVar

from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
    OrderExpr,
    avg,
    collect,
    count,
    max_,
    min_,
    sum_,
)
from runic.ogm.query.specialised import (
    AsyncQueryBuilder,
    FulltextQueryBuilder,
    VectorQueryBuilder,
)
from runic.ogm.query.traversal import TraversalStep

_T = TypeVar("_T")


def select(cls: type[_T]) -> QueryBuilder[_T]:  # noqa: UP047
    """Create a session-independent query statement for *cls*.

    Mirrors the SQLAlchemy 2.0 ``select()`` pattern — compose the statement
    freely (including conditional filters), then execute via the session::

        from runic.ogm import select

        stmt = select(User).where(User.active == True)
        if min_age > 0:
            stmt = stmt.where(User.age >= min_age)

        users: list[User] = session.scalars(stmt)
        user: User | None = session.scalar(stmt)
        n: int = session.count(stmt)

    The returned :class:`QueryBuilder` is **unbound** — calling terminal
    methods like ``.all()`` directly will raise :exc:`RuntimeError`.  Use the
    session execution methods instead.

    Parameters
    ----------
    cls:
        A registered :class:`~runic.ogm.core.models.Node` subclass.
    """
    return QueryBuilder(session=None, root_cls=cls)


__all__ = [  # noqa: RUF022
    # Statement factory
    "select",
    # Builders
    "AsyncQueryBuilder",
    "FulltextQueryBuilder",
    "QueryBuilder",
    "VectorQueryBuilder",
    # Expression types
    "AggExpr",
    "CompoundExpr",
    "Expr",
    "FilterExpr",
    "NegatedExpr",
    "OrderExpr",
    # Traversal
    "TraversalStep",
    # Aggregation helpers
    "avg",
    "collect",
    "count",
    "max_",
    "min_",
    "sum_",
]
