"""Specialised QueryBuilder subclasses: async, fulltext, and vector variants.

These extend :class:`~runic.ogm.query.builder.QueryBuilder` with either an
async execution model (:class:`AsyncQueryBuilder`) or a specialised root
clause that replaces the standard ``MATCH`` (fulltext ``CALL`` and vector KNN).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, TypeVar

from runic.ogm.core.descriptors import FieldDescriptor
from runic.ogm.driver import CypherFeature, require_feature
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.clauses import CallClause
from runic.ogm.query.protocol import CompilationContext

log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# AsyncQueryBuilder
# ---------------------------------------------------------------------------


class AsyncQueryBuilder(QueryBuilder[T]):  # noqa: UP046
    """Async variant of :class:`QueryBuilder` for use with
    :class:`~runic.ogm.session.async_session.AsyncSession`.

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

    async def all(  # type: ignore[override]  # ty: ignore[invalid-method-override]
        self, params: Mapping[str, Any] | None = None
    ) -> list[T]:
        """Async version of :meth:`~QueryBuilder.all`."""
        cypher, _ = self.build()
        log.debug("AsyncQueryBuilder.all: %s", cypher)
        result = await self._session.execute(cypher, self.bind(params))
        return self._decode_node_result(result)

    async def one(  # type: ignore[override]
        self, params: Mapping[str, Any] | None = None
    ) -> T | None:
        """Async version of :meth:`~QueryBuilder.one`."""
        self.limit(1)
        items = await self.all(params)
        return items[0] if items else None

    async def all_with_edges(  # type: ignore[override]  # ty: ignore[invalid-method-override]
        self, params: Mapping[str, Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """Async version of :meth:`~QueryBuilder.all_with_edges`."""
        cypher, _ = self.build()
        log.debug("AsyncQueryBuilder.all_with_edges: %s", cypher)
        result = await self._session.execute(cypher, self.bind(params))
        return self._decode_edge_result(result)

    async def all_rows(  # type: ignore[override]  # ty: ignore[invalid-method-override]
        self, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Async version of :meth:`~QueryBuilder.all_rows`."""
        cypher, _ = self.build()
        log.debug("AsyncQueryBuilder.all_rows: %s", cypher)
        result = await self._session.execute(cypher, self.bind(params))
        return self._decode_rows_as_dicts(result)

    async def count(  # type: ignore[override]  # ty: ignore[invalid-method-override]
        self, params: Mapping[str, Any] | None = None
    ) -> int:
        """Async version of :meth:`~QueryBuilder.count`."""
        saved_returning = self._returning
        saved_return = self._return_aliases
        saved_project = self._project_fields

        from runic.ogm.query.expressions import count as _count_fn

        self._returning = []
        self._return_aliases = None
        self._project_fields = [_count_fn("*").as_("_count")]

        try:
            cypher, _ = self.build()
            log.debug("AsyncQueryBuilder.count: %s", cypher)
            result = await self._session.execute(cypher, self.bind(params))
        finally:
            # Always restore builder state, even if build()/execute() raises, so
            # the instance stays reusable.
            self._returning = saved_returning
            self._return_aliases = saved_return
            self._project_fields = saved_project

        if result.rows:
            return int(result.rows[0][0])
        return 0

    async def scalar(  # type: ignore[override]
        self, params: Mapping[str, Any] | None = None
    ) -> Any:
        """Async version of :meth:`~QueryBuilder.scalar`."""
        cypher, _ = self.build()
        result = await self._session.execute(cypher, self.bind(params))
        if result.rows and result.rows[0]:
            return result.rows[0][0]
        return None

    async def scalars(  # type: ignore[override]  # ty: ignore[invalid-method-override]
        self, params: Mapping[str, Any] | None = None
    ) -> list[Any]:
        """Async version of :meth:`~QueryBuilder.scalars`."""
        cypher, _ = self.build()
        result = await self._session.execute(cypher, self.bind(params))
        return [row[0] for row in result.rows]


# ---------------------------------------------------------------------------
# FulltextQueryBuilder
# ---------------------------------------------------------------------------


class _ProcedureRootBuilder(QueryBuilder[T]):  # noqa: UP046
    """A query whose opening clause is a procedure call rather than a MATCH.

    Index-backed search is only reachable through a procedure, and a procedure
    **cannot be narrowed before the fact**: a ``MATCH`` above it does not
    restrict what it searches.  Every filter therefore runs *after* the
    ``YIELD``, on rows the index has already paid to produce — which is why
    these searches take a search width separate from the row limit.

    Everything after the opening clause is the ordinary builder: ``where()``,
    ``traverse()``, ``with_()``, ``project()`` and the terminal methods all
    behave exactly as they do on a ``MATCH``-rooted statement.
    """

    _root_clause: CallClause

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher, opening with the procedure call."""
        self._validate_variables()
        self._param_counter = 0
        self.params = dict(self._seed_params())
        self._declared_params = set()

        parts: list[str] = [self._root_clause.to_cypher(self)]
        parts.extend(self._after_root())
        self._append_where_and_traversals(parts)

        if self._wants_return():
            parts.append(self._compile_return())
        if self._order:
            parts.append(
                f"ORDER BY {', '.join(o.to_cypher(self) for o in self._order)}"
            )
        parts.extend(self._compile_paging())

        return "\n".join(parts), dict(self.params)

    def _seed_params(self) -> dict[str, Any]:
        """Auto-bound values this search needs before compilation starts."""
        return {}

    def _after_root(self) -> list[str]:
        """Clauses emitted immediately after the procedure call."""
        return []

    def _resolve_label(self) -> str:
        meta = self._meta.get_node_meta(self._root_cls)
        if meta is None:
            msg = f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            raise ValueError(msg)
        return meta.primary_label


class FulltextQueryBuilder(_ProcedureRootBuilder[T]):  # noqa: UP046
    """Fulltext search over a label's fulltext index.

    Constructed via :meth:`~runic.ogm.session.session.Session.fulltext_search`.
    The index must exist; declare it on the field and create it in a migration::

        class Post(Node, labels=["Post"]):
            title: str = Field(index_type="FULLTEXT")

    The match score is available as ``score()`` and can be projected, filtered
    or sorted on.  It is a **relevance** — higher is better — which is the
    opposite convention to a vector distance.  The two are not comparable and
    must never be merged into one ranking without a stated normalisation.

    Example
    -------
    .. code-block:: python

        from runic.ogm import col, param, score

        posts = session.all_rows(
            session.fulltext_search(Post, query=param("text"))
            .where(Post.published == True)
            .project(col(Post.id).as_("id"), score().as_("relevance"))
            .order_by("relevance", desc=True)
            .limit(param("limit")),
            {"text": tokenised, "limit": 20},
        )

    .. warning::
        The query text is a bound parameter, so no Cypher can be injected
        through it — but it reaches the backend's *own* search syntax, which has
        operators of its own. Tokenise caller input before passing it, all the
        more so when the caller is a model.
    """

    def __init__(
        self,
        session: Any,
        root_cls: type[T] | Any,
        query: Any,
        fields: list[str] | None = None,
    ) -> None:
        super().__init__(session, root_cls)
        self._fts_query = query
        self._fts_fields = fields

    @property
    def _root_clause(self) -> CallClause:  # type: ignore[override]
        raise NotImplementedError  # pragma: no cover - replaced by build()

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher, opening with the fulltext procedure."""
        self._validate_variables()
        self._param_counter = 0
        self.params = {}
        self._declared_params = set()

        query_ref = _bind_or_declare(self, self._fts_query, "__fts_query")
        label = self._resolve_label()
        dialect = self._require_dialect()
        require_feature(
            dialect, CypherFeature.FULLTEXT_SEARCH, "fulltext search from Cypher"
        )
        call = dialect.fulltext_call(label, self.root_alias, query_ref.lstrip("$"))

        parts: list[str] = [call]
        # Bind the yielded score under the same name a vector search uses, so
        # score() means "the score this search produced" either way. It is NOT
        # normalised: a fulltext score is a relevance, higher is better, which
        # is the opposite of a vector distance.
        if getattr(dialect, "fulltext_yields_score", lambda: False)():
            parts.append(f"WITH {self.root_alias}, score AS __score")
        self._append_where_and_traversals(parts)

        if self._wants_return():
            parts.append(self._compile_return())
        if self._order:
            parts.append(
                f"ORDER BY {', '.join(o.to_cypher(self) for o in self._order)}"
            )
        parts.extend(self._compile_paging())

        return "\n".join(parts), dict(self.params)


class VectorQueryBuilder(_ProcedureRootBuilder[T]):  # noqa: UP046
    """Index-backed nearest-neighbour search over a vector field.

    Constructed via :meth:`~runic.ogm.session.session.Session.vector_search`.
    The field must declare ``index_type="VECTOR"`` and the index must have been
    created at the embedder's real dimension.

    **The search width and the row limit are two different numbers.** ``k`` is
    how far into the index the search reaches; ``limit`` is how many rows the
    caller sees.  Because a procedure cannot be filtered before the fact, every
    row dropped by a following ``where()`` has to be paid for by ``k`` — asking
    for ``k == limit`` and then filtering returns a short page that looks
    exactly like a small database.

    ``score()`` is a **distance**: lower is closer, on every backend.  An exact
    match can come back marginally negative, so anything converting it to a
    similarity has to clamp.

    Example
    -------
    .. code-block:: python

        from runic.ogm import col, param, score

        rows = session.all_rows(
            session.vector_search(
                Message,
                field=Message.embedding,
                vector=param("vector"),
                k=param("k"),
            )
            .where(Message.embedding_model == param("model"))
            .project(col(Message.id).as_("id"), score().as_("distance"))
            .order_by("distance")
            .limit(param("limit")),
            {"vector": query_vec, "k": 200, "model": model, "limit": 20},
        )

    .. note::
        A message with no vector is not ranked low — it is absent from the index
        entirely, and nothing in the result says so.  Report coverage alongside
        any semantic answer, or "the embed job is a third done" and "there is
        nothing here" look identical.
    """

    def __init__(
        self,
        session: Any,
        root_cls: type[T] | Any,
        field: FieldDescriptor,
        vector: Any,
        k: Any = 10,
    ) -> None:
        super().__init__(session, root_cls)
        self._knn_field = field
        self._knn_vector = vector
        self._knn_k = k

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher, opening with the vector index procedure."""
        self._validate_variables()
        self._param_counter = 0
        self.params = {}
        self._declared_params = set()

        vec_ref = _bind_or_declare(self, self._knn_vector, "__knn_vec")
        k_ref = _bind_or_declare(self, self._knn_k, "__knn_k")
        label = self._resolve_label()
        dialect = self._require_dialect()
        require_feature(
            dialect, CypherFeature.VECTOR_SEARCH, "vector search from Cypher"
        )

        parts: list[str] = [
            dialect.vector_knn_call(
                self.root_alias,
                label,
                self._knn_field.field_name,
                k_ref,
                vec_ref,
            ),
            # Normalise the backend's own convention to a distance, so a score
            # means the same thing everywhere: lower is closer.
            f"WITH {self.root_alias}, {dialect.vector_score_expr()} AS __score",
        ]
        self._append_where_and_traversals(parts)

        if self._wants_return():
            parts.append(self._compile_return())

        # Closest first, then whatever else the caller asked for.
        knn_order = "ORDER BY __score ASC"
        if self._order:
            user_order = ", ".join(o.to_cypher(self) for o in self._order)
            parts.append(f"{knn_order}, {user_order}")
        else:
            parts.append(knn_order)
        parts.extend(self._compile_paging())

        return "\n".join(parts), dict(self.params)


def _bind_or_declare(
    compiler: CompilationContext, value: Any, fallback_name: str
) -> str:
    """Render *value* as a parameter reference.

    A :func:`~runic.ogm.query.values.param` is declared for the caller to bind;
    anything else is bound now under *fallback_name*.
    """
    from runic.ogm.query.values import ValueExpr

    if isinstance(value, ValueExpr):
        return value.to_cypher(compiler)
    compiler.params[fallback_name] = value
    return f"${fallback_name}"
