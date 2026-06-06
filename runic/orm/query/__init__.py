"""runic.orm.query — fluent query builder for FalkorDB graph queries.

Public API
----------
The recommended entry points are the session/repository methods:

- :meth:`~runic.orm.session.session.Session.query` → :class:`QueryBuilder`
- :meth:`~runic.orm.session.session.Session.fulltext_search` → :class:`FulltextQueryBuilder`
- :meth:`~runic.orm.session.session.Session.vector_search` → :class:`VectorQueryBuilder`
- :meth:`~runic.orm.repository.repository.Repository.query` → :class:`QueryBuilder`

Expression helpers imported here for convenience::

    from runic.orm.query import count, avg, sum_, min_, max_, collect

Refer to :mod:`runic.orm.query.builder` for the full API reference.
"""

from runic.orm.query.builder import (
    AsyncQueryBuilder,
    FulltextQueryBuilder,
    QueryBuilder,
    VectorQueryBuilder,
)
from runic.orm.query.expressions import (
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
from runic.orm.query.traversal import TraversalStep

__all__ = [  # noqa: RUF022
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
