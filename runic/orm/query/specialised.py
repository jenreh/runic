"""Specialised QueryBuilder subclasses: async, fulltext, and vector variants.

These extend :class:`~runic.orm.query.builder.QueryBuilder` with either an
async execution model (:class:`AsyncQueryBuilder`) or a specialised root
clause that replaces the standard ``MATCH`` (fulltext ``CALL`` and vector KNN).
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from runic.orm.core.descriptors import FieldDescriptor
from runic.orm.query.builder import QueryBuilder
from runic.orm.query.expressions import CompoundExpr

log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# AsyncQueryBuilder
# ---------------------------------------------------------------------------


class AsyncQueryBuilder(QueryBuilder[T]):  # noqa: UP046
    """Async variant of :class:`QueryBuilder` for use with
    :class:`~runic.orm.session.async_session.AsyncSession`.

    All intermediate (chainable) methods are identical to the sync version.
    Only the **terminal** methods are replaced with ``async def`` equivalents.

    Example
    -------
    .. code-block:: python

        async with AsyncSession(graph) as session:
            users = await (
                session.query(User)
                .where(User.active == True)
                .order_by(User.name)
                .limit(50)
                .all()
            )
    """

    async def all(self) -> list[T]:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.all`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_node_result(result)

    async def one(self) -> T | None:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.one`."""
        self.limit(1)
        items = await self.all()
        return items[0] if items else None

    async def all_with_edges(self) -> list[tuple[Any, ...]]:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.all_with_edges`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all_with_edges: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_edge_result(result)

    async def all_rows(self) -> list[dict[str, Any]]:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.all_rows`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all_rows: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_rows_as_dicts(result)

    async def count(self) -> int:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.count`."""
        saved_agg = self._agg_exprs
        saved_group = self._group_by_alias
        saved_return = self._return_aliases
        saved_project = self._project_fields

        from runic.orm.query.expressions import count as _count_fn

        self._agg_exprs = [_count_fn("*").as_("_count")]
        self._group_by_alias = None
        self._return_aliases = None
        self._project_fields = []

        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.count: %s", cypher)
        result = await self._session.execute(cypher, params)

        self._agg_exprs = saved_agg
        self._group_by_alias = saved_group
        self._return_aliases = saved_return
        self._project_fields = saved_project

        if result.rows:
            return int(result.rows[0][0])
        return 0

    async def scalar(self) -> Any:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.scalar`."""
        result = await self._session.execute(*self.build())
        if result.rows and result.rows[0]:
            return result.rows[0][0]
        return None

    async def scalars(self) -> list[Any]:  # type: ignore[override]  # ty: ignore[invalid-method-override]
        """Async version of :meth:`~QueryBuilder.scalars`."""
        result = await self._session.execute(*self.build())
        return [row[0] for row in result.rows]


# ---------------------------------------------------------------------------
# FulltextQueryBuilder
# ---------------------------------------------------------------------------


class FulltextQueryBuilder(QueryBuilder[T]):  # noqa: UP046
    """QueryBuilder variant for FalkorDB fulltext search queries.

    Constructed via :meth:`~runic.orm.session.session.Session.fulltext_search`.
    The root MATCH is replaced with a ``CALL db.idx.fulltext.queryNodes(...)``
    invocation that uses the declared fulltext index.

    The fulltext index must have been created for the node's label, e.g.::

        class Post(Node, labels=["Post"]):
            title: str = Field(index_type="FULLTEXT")

    Example
    -------
    .. code-block:: python

        posts = (
            session.fulltext_search(Post, query="graph databases", fields=["title"])
            .where(Post.published == True)
            .order_by(Post.created_at, desc=True)
            .limit(20)
            .all()
        )

    Cypher emitted::

        CALL db.idx.fulltext.queryNodes('Post', $__fts_query) YIELD node AS n
        WHERE n.published = $p0
        RETURN n
        ORDER BY n.created_at DESC
        LIMIT 20
    """

    def __init__(
        self,
        session: Any,
        root_cls: type[T],
        query: str,
        fields: list[str] | None = None,
    ) -> None:
        super().__init__(session, root_cls)
        self._fts_query = query
        self._fts_fields = fields

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher, replacing MATCH with CALL fulltext procedure."""
        self._param_counter = 0
        self._params = {"__fts_query": self._fts_query}

        root_meta = self._meta.get_node_meta(self._root_cls)
        if root_meta is None:
            raise ValueError(
                f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            )

        alias = self._root_alias
        label = root_meta.primary_label
        parts: list[str] = [self._dialect.fulltext_call(label, alias, "__fts_query")]

        # Extra OPTIONAL MATCHes for traversals (root WHERE + WITH go first)
        if self._where_exprs and self._match_clauses:
            root_exprs, post_exprs = self._split_where_exprs()
        else:
            root_exprs = []
            post_exprs = self._where_exprs

        if root_exprs:
            cond = self._compile_expr(
                root_exprs[0]
                if len(root_exprs) == 1
                else CompoundExpr(op="AND", operands=root_exprs)
            )
            parts.append(f"WHERE {cond}")

        if self._with_vars:
            parts.append(f"WITH {', '.join(self._with_vars)}")

        parts.extend(mc.to_cypher() for mc in self._match_clauses)

        if post_exprs:
            cond = self._compile_expr(
                post_exprs[0]
                if len(post_exprs) == 1
                else CompoundExpr(op="AND", operands=post_exprs)
            )
            parts.append(f"WHERE {cond}")

        parts.append(self._compile_return())

        if self._order:
            parts.append(f"ORDER BY {', '.join(o.to_cypher() for o in self._order)}")
        if self._skip_val is not None:
            parts.append(f"SKIP {self._skip_val}")
        if self._limit_val is not None:
            parts.append(f"LIMIT {self._limit_val}")

        return "\n".join(parts), dict(self._params)


# ---------------------------------------------------------------------------
# VectorQueryBuilder
# ---------------------------------------------------------------------------


class VectorQueryBuilder(QueryBuilder[T]):  # noqa: UP046
    """QueryBuilder variant for vector KNN search.

    Constructed via :meth:`~runic.orm.session.session.Session.vector_search`.
    Appends a KNN distance expression to the ORDER BY and RETURN clauses.

    The field must have ``index_type="VECTOR"`` and an HNSW vector index
    must be created via :meth:`~runic.migrate.schema.SchemaManager`::

        class Document(Node, labels=["Document"]):
            embedding: Vector = Field(index_type="VECTOR")

    Example
    -------
    .. code-block:: python

        similar = (
            session.vector_search(
                Document,
                field=Document.embedding,
                vector=[0.1, 0.2, 0.3],
                k=10,
            )
            .where(Document.active == True)
            .all()
        )

    Cypher emitted (FalkorDB KNN syntax)::

        MATCH (n:Document)
        WHERE n.active = $p0
        RETURN n, vecf32(n.embedding) <-> vecf32($__knn_vec) AS __score
        ORDER BY __score ASC
        LIMIT 10
    """

    def __init__(
        self,
        session: Any,
        root_cls: type[T],
        field: FieldDescriptor,
        vector: list[float],
        k: int,
    ) -> None:
        super().__init__(session, root_cls)
        self._knn_field = field
        self._knn_vector = vector
        self._knn_k = k

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher with KNN ORDER BY."""
        self._param_counter = 0
        self._params = {"__knn_vec": list(self._knn_vector)}

        root_meta = self._meta.get_node_meta(self._root_cls)
        if root_meta is None:
            raise ValueError(
                f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            )

        _lc = getattr(self._dialect, "labels_clause", None)
        labels_str = _lc(root_meta.labels) if _lc else ":".join(root_meta.labels)
        alias = self._root_alias
        field_alias = (
            self._alias_for_cls(self._knn_field.owner)
            if self._knn_field.owner
            else self._root_alias
        )
        field_name = self._knn_field.field_name
        type_name = root_meta.primary_label

        self._params["__knn_k"] = self._knn_k
        parts: list[str] = [
            self._dialect.vector_knn_start(alias, labels_str, type_name, field_name)
        ]

        if self._where_exprs and self._match_clauses:
            root_exprs, post_exprs = self._split_where_exprs()
        else:
            root_exprs = []
            post_exprs = self._where_exprs

        if root_exprs:
            cond = self._compile_expr(
                root_exprs[0]
                if len(root_exprs) == 1
                else CompoundExpr(op="AND", operands=root_exprs)
            )
            parts.append(f"WHERE {cond}")

        if self._with_vars:
            parts.append(f"WITH {', '.join(self._with_vars)}")

        parts.extend(mc.to_cypher() for mc in self._match_clauses)

        if post_exprs:
            cond = self._compile_expr(
                post_exprs[0]
                if len(post_exprs) == 1
                else CompoundExpr(op="AND", operands=post_exprs)
            )
            parts.append(f"WHERE {cond}")

        # KNN return includes the distance score
        return_part = self._compile_return()
        if "RETURN" in return_part and "__score" not in return_part:
            score_expr = self._dialect.vector_knn_score_expr(field_alias, field_name)
            return_part = return_part + f", {score_expr}"
        parts.append(return_part)

        # KNN ordering: always by score ASC, then any user orders
        knn_order = "ORDER BY __score ASC"
        if self._order:
            user_order = ", ".join(o.to_cypher() for o in self._order)
            parts.append(f"{knn_order}, {user_order}")
        else:
            parts.append(knn_order)

        if self._skip_val is not None:
            parts.append(f"SKIP {self._skip_val}")
        # k overrides limit if no explicit limit was set
        effective_limit = (
            self._limit_val if self._limit_val is not None else self._knn_k
        )
        parts.append(f"LIMIT {effective_limit}")

        return "\n".join(parts), dict(self._params)
