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

A custom clause or value expression renders against
:class:`~runic.ogm.query.protocol.CompilationContext` — the interface the
compiler publishes to the objects it compiles.
"""

from typing import Any, TypeVar

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
from runic.ogm.query.mutation import MutationBuilder, unwind
from runic.ogm.query.protocol import CompilationContext
from runic.ogm.query.values import (
    Alias,
    AliasedExpr,
    CaseExpr,
    FnCall,
    LiteralValue,
    ParamRef,
    PropertyRef,
    RowRef,
    ValueExpr,
    alias,
    coalesce,
    col,
    encode_rows,
    fn,
    left,
    literal,
    param,
    row,
    score,
    to_lower,
    to_upper,
    var,
    when,
)

_T = TypeVar("_T")


def select(cls: type[_T] | Alias, name: str | None = None) -> QueryBuilder[_T]:  # noqa: UP047
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

    The root variable defaults to ``n``. Name it explicitly — a second
    argument, or an :func:`~runic.ogm.query.values.alias` handle when later
    calls want to reference it::

        stmt = select(Message, "m")  # MATCH (m:Message)

        m = alias(Message, "m")
        stmt = select(m).where(m.id > param("after"))  # MATCH (m:Message)

    The returned :class:`QueryBuilder` is **unbound** — calling terminal
    methods like ``.all()`` directly will raise :exc:`RuntimeError`.  Use the
    session execution methods instead.

    Parameters
    ----------
    cls:
        A registered :class:`~runic.ogm.core.models.Node` subclass, or a
        handle created by :func:`~runic.ogm.query.values.alias`.
    name:
        Cypher variable for the root node (default ``n``). Redundant — and
        rejected — when *cls* is already a handle.
    """
    return QueryBuilder(session=None, root_cls=cls, name=name)


def vector_search(field: Any, *, vector: Any, k: Any = 10) -> VectorQueryBuilder[Any]:
    """Create a session-independent KNN statement over a vector field.

    The search-side counterpart of :func:`select`: unbound, executed through
    the session.  The field descriptor knows its owner, so the class is not
    repeated::

        KNN = (
            vector_search(Message.embedding, vector=param("vector"), k=param("k"))
            .where(Message.embedding_model == param("model"))
            .project(Message.id, score().as_("distance"))
            .limit(param("limit"))
        )
        rows = session.all_rows(KNN, {"vector": vec, "k": 200, ...})

    ``k`` is how wide the index search goes; ``limit`` is what the caller
    sees — a filtered KNN must over-fetch, so keep them separate parameters.

    A handle's attribute names the yielded variable at the same time::

        node = alias(Message, "node")
        vector_search(node.embedding, vector=param("vector"), k=param("k"))
        # CALL ... YIELD node ...
    """
    from runic.ogm.core.descriptors import FieldDescriptor
    from runic.ogm.query.values import PropertyRef

    root: type | Alias | None = None
    if isinstance(field, PropertyRef) and field.owner is not None:
        root = Alias(field.alias, field.owner)
        field = getattr(field.owner, field.prop)
    if isinstance(field, FieldDescriptor) and field.owner is not None:
        return VectorQueryBuilder(
            None, root or field.owner, field=field, vector=vector, k=k
        )
    msg = (
        "vector_search() takes a vector field declared on a Node class — "
        "vector_search(Message.embedding, ...) or a handle's attribute "
        "(node.embedding)"
    )
    raise TypeError(msg)


def fulltext_search(  # noqa: UP047
    cls: type[_T] | Alias, *, query: Any, fields: list[str] | None = None
) -> FulltextQueryBuilder[_T]:
    """Create a session-independent fulltext-search statement for *cls*.

    Unbound, executed through the session; ``score()`` is the match relevance
    (higher is better — the opposite convention to a vector distance)::

        SEARCH = (
            fulltext_search(Message, query=param("text"))
            .project(Message.id, score().as_("relevance"))
            .order_by(score().as_("relevance"), desc=True)
            .limit(param("limit"))
        )
    """
    return FulltextQueryBuilder(None, cls, query=query, fields=fields)


__all__ = [  # noqa: RUF022
    # Statement factories
    "select",
    "vector_search",
    "fulltext_search",
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
    # Aggregation helpers
    "avg",
    "collect",
    "count",
    "max_",
    "min_",
    "sum_",
    # Value expressions
    "Alias",
    "AliasedExpr",
    "CaseExpr",
    "FnCall",
    "LiteralValue",
    "ParamRef",
    "PropertyRef",
    "RowRef",
    "ValueExpr",
    # Value constructors
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
    # Bulk writes
    "MutationBuilder",
    "unwind",
    # Compilation interface, for custom clauses / value expressions
    "CompilationContext",
]
