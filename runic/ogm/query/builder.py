"""Fluent query builder for the runic ORM.

See :doc:`/query_builder` for the full API reference and examples.

:class:`QueryBuilder` is the core builder; specialised subclasses
(:class:`~runic.ogm.query.specialised.AsyncQueryBuilder`,
:class:`~runic.ogm.query.specialised.FulltextQueryBuilder`,
:class:`~runic.ogm.query.specialised.VectorQueryBuilder`) live in
:mod:`runic.ogm.query.specialised`.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar

from runic.cypher import validate_identifier, validate_order_term, validate_reference
from runic.ogm.core.descriptors import FieldDescriptor
from runic.ogm.core.metadata import metadata as _global_metadata
from runic.ogm.driver import CypherFeature
from runic.ogm.query._compiler import _CypherCompiler
from runic.ogm.query.clauses import (
    Clause,
    DeleteClause,
    MatchClause,
    SetClause,
    WithClause,
)
from runic.ogm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    OrderExpr,
)
from runic.ogm.query.traversal import TraversalStep
from runic.ogm.query.values import ValueExpr

log = logging.getLogger(__name__)

T = TypeVar("T")


def _validate_projection(expr: str) -> None:
    """Reject a raw-string projection that is not a plain property reference.

    Thin wrapper over :func:`~runic.cypher.validate_reference`, kept as a named
    function because it is part of this module's tested surface.
    """
    validate_reference(expr, "projection")


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------


class QueryBuilder(_CypherCompiler[T]):  # noqa: UP046
    """Fluent Cypher query builder for a single root Node class.

    Construct via :meth:`Session.query`::

        q = session.query(User)

    All non-terminal methods return ``self`` so calls can be chained::

        users = session.query(User).where(User.active == True).limit(10).all()

    Parameters
    ----------
    session:
        The :class:`~runic.ogm.session.session.Session` (or
        :class:`~runic.ogm.session.async_session.AsyncSession`) this builder
        is bound to.
    root_cls:
        The root Node subclass to query.
    """

    def __init__(self, session: Any | None, root_cls: type[T]) -> None:
        from runic.ogm.core.metadata import MetaData

        self._session: Any = session  # None when unbound (created via select())
        self._root_cls: type[T] = root_cls
        _mapper = getattr(session, "mapper", None)
        self._meta: MetaData = getattr(_mapper, "meta", _global_metadata)

        # Alias tracking -------------------------------------------------
        # alias → OGM class (Node or Edge)
        self._alias_map: dict[str, type] = {}
        # OGM class → list of aliases (inverse lookup)
        self._cls_aliases: dict[type, list[str]] = {}
        # The most recently registered target alias (default RETURN target)
        self._last_alias: str = "n"
        # The root node alias
        self._root_alias: str = "n"

        # Register root
        self._set_alias("n", root_cls)

        # Query parts ----------------------------------------------------
        # Clauses between the opening MATCH and the RETURN, in call order —
        # WITH before a traversal means something different from WITH after it.
        self._pipeline: list[Clause] = []
        self._where_exprs: list[Expr] = []
        self._order: list[OrderExpr] = []
        self._distinct: bool = False
        self._limit_val: int | None = None
        self._skip_val: int | None = None

        # Return specification -------------------------------------------
        # None → auto (last alias or root alias)
        # list of str → explicit aliases / Cypher expressions to return
        self._return_aliases: list[str] | None = None
        # Edge alias to include in .all_with_edges() output
        self._edge_alias_for_result: str | None = None
        # Aggregation specs
        self._agg_exprs: list[AggExpr] = []
        self._group_by_alias: str | None = None
        # Scalar projection (for .project())
        self._project_fields: list[FieldDescriptor | ValueExpr | str] = []
        # Explicit RETURN expressions, set by returning()
        self._returning: list[Any] = []

        # Parameters -------------------------------------------------------
        # Auto-bound values ($p0, $p1, …) allocated during compilation.
        self._param_counter: int = 0
        self._params: dict[str, Any] = {}
        # Names declared via param(), supplied by the caller at execution.
        self._declared_params: set[str] = set()

    # ------------------------------------------------------------------
    # Unbound-statement guard
    # ------------------------------------------------------------------

    def _check_bound(self) -> None:
        if self._session is None:
            raise RuntimeError(
                "This statement is not bound to a session. "
                "Use session.scalars(stmt), session.scalar(stmt), "
                "session.all_rows(stmt), session.all_with_edges(stmt), "
                "or session.count(stmt) to execute it."
            )

    @contextmanager
    def _bound_to(self, session: Any) -> Generator[QueryBuilder[T]]:
        """Temporarily bind this statement to *session* for execution.

        Used by :class:`~runic.ogm.session.session.Session` execution methods
        so that :meth:`build` has access to the dialect and the identity map is
        populated correctly.  The binding is restored after the ``with`` block,
        leaving the statement reusable.
        """
        old = self._session
        self._session = session
        try:
            yield self
        finally:
            self._session = old

    # ------------------------------------------------------------------
    # Alias management
    # ------------------------------------------------------------------

    def alias(self, name: str) -> QueryBuilder[T]:
        """Set the Cypher variable for the root (most recent) node.

        Call immediately after :meth:`Session.query` to name the root
        variable, or after :meth:`TraversalStep.alias` has already been
        called to rename the last registered target.

        Example::

            session.query(User).alias("u").where(User.active == True, on="u")
        """
        old_alias = self._last_alias
        old_cls = self._alias_map.get(old_alias)
        if old_cls is not None:
            # Remove old mapping
            self._alias_map.pop(old_alias, None)
            if old_cls in self._cls_aliases and old_alias in self._cls_aliases[old_cls]:
                self._cls_aliases[old_cls].remove(old_alias)

        self._set_alias(name, old_cls or self._root_cls)
        self._last_alias = name

        # Update root alias if renaming the root
        if old_alias == self._root_alias:
            self._root_alias = name

        return self

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def where(
        self,
        expr: Expr,
        *,
        on: str | None = None,
    ) -> QueryBuilder[T]:
        """Add a WHERE predicate.

        Parameters
        ----------
        expr:
            A :class:`~runic.ogm.query.expressions.FilterExpr`,
            :class:`~runic.ogm.query.expressions.CompoundExpr`, or
            :class:`~runic.ogm.query.expressions.NegatedExpr`.
            Created via field descriptor operators::

                User.name == "Alice"
                (User.age > 18) & (User.active == True)

        on:
            Override the Cypher variable for this predicate.  Useful when the
            same Node class appears under multiple aliases, or when filtering
            on edge properties::

                .where(Rated.score > 4.0, on="r")

        Notes
        -----
        Multiple ``.where()`` calls are combined with ``AND``.  To express
        ``OR``, use the ``|`` operator on the expressions before passing::

            .where((User.role == "admin") | (User.role == "mod"))
        """
        if on is not None and isinstance(expr, FilterExpr):
            expr = expr.with_alias(on)
        self._where_exprs.append(expr)
        return self

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def traverse(
        self,
        relation_field: FieldDescriptor,
        *,
        edge_alias: str | None = None,
        optional: bool = True,
        from_: str | None = None,
        types: Sequence[str] | None = None,
        direction: str | None = None,
    ) -> TraversalStep:
        """Traverse a declared :func:`~runic.ogm.core.descriptors.Relation` field.

        Returns a :class:`~runic.ogm.query.traversal.TraversalStep`; call
        ``.alias("f")`` on it to name the target node and return to the builder.

        Parameters
        ----------
        relation_field:
            The ``Relation``-backed field descriptor accessed at class level::

                User.friends  # list[User] = Relation(...)
                User.rated  # list[Movie] = Relation(edge_model=Rated)

        edge_alias:
            When given, a named relationship variable is emitted in the pattern::

                (u)-[r:RATED]->(m)

            This enables filtering on edge properties via
            ``.where(Rated.score > 4, on="r")`` and retrieving edge instances
            via ``.all_with_edges()``.

        optional:
            ``True`` (default) → ``OPTIONAL MATCH`` (left-join; keeps source
            nodes that have no such relationship).
            ``False`` → ``MATCH`` (inner join; drops source nodes without a
            matching relationship).

        from_:
            Traverse out of this Cypher variable instead of the most recently
            registered one.  Without it each traversal continues from where the
            previous one landed, which walks a chain; with it several traversals
            can fan out from the same node::

                q = session.query(Message).alias("m")
                q = q.traverse(Message.sent_from, from_="m").alias("s")
                q = q.traverse(Message.sent_to, from_="m").alias("r")

            Reading a node's relationships in one query means fanning out, and
            the alternative — one query per relationship — reads the same node
            once per edge type.

        types:
            Match an alternation of relationship types (``[:A|B]``) instead of
            the single type the Relation declares.  Use when the relationship
            you mean is defined as the walk over more than one type; two
            separate patterns would double-count anything matching both.

        direction:
            Override the Relation's declared direction for this pattern.  A
            relation declared ``BOTH`` is undirected in meaning, but when both
            endpoints carry the same label a directed pattern still matches
            every edge — exactly once, where the undirected form matches it
            from each end and doubles a count.

        Returns
        -------
        TraversalStep
            Call ``.alias("name")`` on the return value to complete the step.

        Examples
        --------
        .. code-block:: python

            # Basic traversal
            q = session.query(User).alias("u")
            q = q.traverse(User.friends).alias("f")

            # Traversal with edge properties
            q = session.query(User).alias("u")
            q = q.traverse(User.rated, edge_alias="r").alias("m")
            q = q.where(Rated.score >= 4.0, on="r")
        """
        return TraversalStep(
            builder=self,
            field_descriptor=relation_field,
            source_alias=from_ or self._last_alias,
            optional=optional,
            edge_alias=edge_alias,
            min_hops=1,
            max_hops=1,
            types=types,
            direction=direction,
        )

    def repeat(
        self,
        relation_field: FieldDescriptor,
        *,
        min_hops: int = 1,
        max_hops: int | None = None,
        optional: bool = False,
        from_: str | None = None,
    ) -> TraversalStep:
        """Traverse a relation with variable-length path quantifier ``*min..max``.

        Generates a Cypher pattern like::

            (p)-[:PARENT*1..5]->(ancestor:Person)

        Parameters
        ----------
        relation_field:
            The ``Relation`` field to traverse repeatedly.
        min_hops:
            Minimum number of hops (default ``1``).
        max_hops:
            Maximum number of hops.  ``None`` means unbounded (``*min..``).
        optional:
            ``False`` (default for repeat) — required traversal.
            ``True`` → ``OPTIONAL MATCH``.

        Returns
        -------
        TraversalStep
            Call ``.alias("name")`` to complete the step.

        Examples
        --------
        .. code-block:: python

            # All ancestors up to depth 5
            ancestors = (
                session.query(Person)
                .alias("p")
                .where(Person.id == start_id)
                .repeat(Person.parent, min_hops=1, max_hops=5)
                .alias("anc")
                .all()
            )

            # All reachable nodes (unbounded)
            reachable = (
                session.query(Node)
                .alias("s")
                .repeat(Node.connected_to)
                .alias("t")
                .all()
            )
        """
        return TraversalStep(
            builder=self,
            field_descriptor=relation_field,
            source_alias=from_ or self._last_alias,
            optional=optional,
            edge_alias=None,
            min_hops=min_hops,
            max_hops=max_hops,
        )

    # ------------------------------------------------------------------
    # WITH (multi-stage pipelining)
    # ------------------------------------------------------------------

    def with_(
        self,
        *variables: Any,
        order_by: Any = None,
        desc: bool = False,
        limit: Any = None,
        skip: Any = None,
        where: Expr | Sequence[Expr] | None = None,
        distinct: bool = False,
    ) -> QueryBuilder[T]:
        """Insert a ``WITH`` stage, carrying *variables* into what follows.

        Repeatable: each call adds a stage, and stages interleave with
        traversals in the order they were written.

        Parameters
        ----------
        *variables:
            Cypher variables to carry forward (``"m"``), or value expressions
            when a stage needs to compute something (``count("*").as_("n")``).
        order_by / desc:
            Sort the rows entering the next stage. Required whenever *limit* is
            used: paging without an order is undefined, and two runs may return
            different pages.
        limit / skip:
            Bound the rows entering the next stage. Accepts an integer or a
            :func:`~runic.ogm.query.values.param` reference.
        where:
            Predicates applied after the stage — Cypher's equivalent of
            ``HAVING``, and the only way to filter on an aggregated value.
        distinct:
            Emit ``WITH DISTINCT``.

        Cutting a page here rather than at the end is the difference between
        paying for one page's expansions and paying for the whole graph's::

            (
                session.query(Message)
                .alias("m")
                .where(Message.id > param("after"))
                .with_("m", order_by=Message.id, limit=param("limit"))
                .traverse(Message.sent_to, from_="m")
                .alias("r")
                .aggregate(
                    collect(col("r", Address.id), distinct=True).as_("addressed"),
                    group_by=col("m", Message.id).as_("id"),
                )
            )

        A trailing ``LIMIT`` would instead expand every message in the archive
        and then discard all but the page.
        """
        order_terms: list[OrderExpr] = []
        if order_by is not None:
            order_terms = [self._order_term(order_by, desc=desc)]

        predicates: tuple[Expr, ...]
        if where is None:
            predicates = ()
        elif isinstance(where, (list, tuple)):
            predicates = tuple(where)
        else:
            predicates = (where,)  # ty: ignore[invalid-assignment]

        self._pipeline.append(
            WithClause(
                variables=tuple(variables),
                order_by=order_terms,
                limit=limit,
                skip=skip,
                where=predicates,
                distinct=distinct,
            )
        )
        return self

    # ------------------------------------------------------------------
    # Ordering / pagination
    # ------------------------------------------------------------------

    def order_by(
        self,
        field: FieldDescriptor | ValueExpr | str,
        *,
        desc: bool = False,
    ) -> QueryBuilder[T]:
        """Add an ``ORDER BY`` term.

        Parameters
        ----------
        field:
            A field descriptor (``User.name``) or a raw Cypher expression
            string (``"n.created_at DESC"``).
        desc:
            ``True`` for descending order (default ``False``).

        Examples
        --------
        .. code-block:: python

            q.order_by(User.age)  # ORDER BY n.age ASC
            q.order_by(User.created_at, desc=True)  # ORDER BY n.created_at DESC
            q.order_by("score ASC")  # raw string
        """
        self._order.append(self._order_term(field, desc=desc))
        return self

    def _order_term(
        self, field: FieldDescriptor | ValueExpr | str, *, desc: bool
    ) -> OrderExpr:
        """Build one ORDER BY term from a descriptor, expression, or raw string."""
        if isinstance(field, ValueExpr):
            return OrderExpr(alias=None, prop=None, expr=field, desc=desc)
        if isinstance(field, FieldDescriptor):
            alias = (
                self._alias_for_cls(field.owner) if field.owner else self._root_alias
            )
            return OrderExpr(alias=alias, prop=field.field_name, desc=desc)
        raw = validate_order_term(str(field), "order_by term")
        return OrderExpr(alias=None, prop=None, raw=raw, desc=desc)

    def limit(self, n: int | ValueExpr) -> QueryBuilder[T]:
        """Set ``LIMIT`` on the query.

        Accepts an integer, or a :func:`~runic.ogm.query.values.param` reference
        so the ceiling is bound by the caller rather than baked into the
        statement::

            select(Message).limit(param("limit"))  # LIMIT $limit
        """
        self._limit_val = n
        return self

    def skip(self, n: int | ValueExpr) -> QueryBuilder[T]:
        """Set ``SKIP`` (offset) on the query.

        Accepts an integer or a :func:`~runic.ogm.query.values.param` reference.

        Prefer a cursor (``where(Model.id > param("after"))``) over an offset for
        paging: ``SKIP`` re-matches and re-sorts every preceding row, so walking
        a whole label in pages costs ``O(n²/page)``.
        """
        self._skip_val = n
        return self

    def distinct(self) -> QueryBuilder[T]:
        """Add ``DISTINCT`` to the ``RETURN`` clause."""
        self._distinct = True
        return self

    # ------------------------------------------------------------------
    # Return specification
    # ------------------------------------------------------------------

    def return_target(self, alias: str) -> QueryBuilder[T]:
        """Set the single alias to return decoded Node instances from.

        When a traversal is involved, this selects which alias's nodes
        constitute the result of ``.all()``::

            q.return_target("f")  # returns f-nodes as list[FriendType]
        """
        self._return_aliases = [alias]
        return self

    def return_nodes(self, *aliases: str) -> QueryBuilder[T]:
        """Declare multiple node aliases to include in the ``RETURN`` clause.

        Used with :meth:`return_edge` and :meth:`all_with_edges` to return
        structured tuples::

            q.return_nodes("u", "m").return_edge("r").all_with_edges()
        """
        self._return_aliases = list(aliases)
        return self

    def return_edge(self, alias: str) -> QueryBuilder[T]:
        """Declare an edge alias to include in the ``RETURN`` clause.

        Requires that the traversal was created with ``edge_alias=alias``.
        The edge is decoded via :meth:`~runic.ogm.mapper.mapper.Mapper.decode_edge`
        and included as the middle element of tuples returned by
        :meth:`all_with_edges`.
        """
        self._edge_alias_for_result = alias
        return self

    def project(self, *fields: FieldDescriptor | ValueExpr | str) -> QueryBuilder[T]:
        """Return only specific values (scalar projection).

        Terminal method ``.scalars()`` returns the projected values as a flat
        list; ``.all_rows()`` returns a list of dicts::

            # Scalar list
            names = session.query(User).project(User.name).scalars()

            # Dict list
            rows = session.query(User).project(User.name, User.age).all_rows()

        Accepts field descriptors, raw ``alias.property`` strings, and
        :mod:`~runic.ogm.query.values` expressions — which is how a column gets
        a stable name, or is computed in the store::

            from runic.ogm.query import col, left, param

            session.query(Message).project(
                col(Message.id).as_("id"),
                left(col(Message.body_clean), param("max_chars")).as_("body"),
            )
            # RETURN n.id AS id, left(n.body_clean, $max_chars) AS body

        Naming columns matters for more than tidiness: ``all_rows()`` keys its
        dicts by the column names the store reports, so an unaliased projection
        yields keys like ``"n.body_clean"``.
        """
        for f in fields:
            if isinstance(f, str):
                _validate_projection(f)
        self._project_fields = list(fields)
        return self

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set(
        self,
        assignments: Mapping[Any, Any],
        *,
        on: str | None = None,
    ) -> QueryBuilder[T]:
        """Assign properties on matched rows — a bulk ``SET``.

        Keys are field descriptors (or ``"alias.property"`` strings); values are
        Python values, :mod:`~runic.ogm.query.values` expressions, or ``None``
        to clear the property.

        Field converters and the dialect's wrapping functions (``vecf32``,
        ``point``, ``intern``) are applied, so a value written this way is
        stored the same way the mapper would store it::

            (
                select(Message)
                .where(Message.embedding.is_not_null())
                .set({Message.embedding: None, Message.embedding_model: None})
                .returning(count("n").as_("cleared"))
            )

        Parameters
        ----------
        assignments:
            Property → value mapping.
        on:
            Cypher variable to assign on, when the property's own class is not
            the one being written (or appears under several aliases).
        """
        triples: list[tuple[str, str, Any]] = []
        for target, value in assignments.items():
            alias, prop = self._resolve_write_target(target, on)
            triples.append((alias, prop, value))
        self._pipeline.append(SetClause(assignments=tuple(triples)))
        return self

    def delete(self, *variables: str, detach: bool = False) -> QueryBuilder[T]:
        """Delete the named variables, defaulting to the current target.

        Parameters
        ----------
        *variables:
            Cypher variables to delete. Defaults to the most recent alias.
        detach:
            Also remove the edges incident to the deleted nodes.  Required to
            delete a node that has any: Cypher refuses otherwise.

            Do **not** set it when deleting an *edge*.  Detaching there takes
            the endpoints down too, which for a derived edge between two
            ground-truth nodes means destroying real data to clean up a
            computed one::

                # A batch of derived nodes, and the edges that hang off them
                select(Group).with_("n", limit=param("batch")).delete(detach=True)

                # A batch of derived edges, keeping both endpoints
                (
                    select(Address)
                    .alias("a")
                    .traverse(Address.co_addressed, edge_alias="r", optional=False)
                    .alias("b")
                    .with_("r", limit=param("batch"))
                    .delete("r")
                )

        Batching through a ``WITH`` stage keeps one delete from becoming a
        single long stall on a store something else is also reading; loop until
        the returned count is zero.
        """
        targets = variables or (self._last_alias,)
        self._pipeline.append(DeleteClause(variables=tuple(targets), detach=detach))
        return self

    def returning(self, *values: Any) -> QueryBuilder[T]:
        """Set an explicit ``RETURN`` list of expressions.

        Used after a write to report what it did::

            .delete(detach=True).returning(count("n").as_("removed"))
        """
        self._returning = list(values)
        return self

    def _resolve_write_target(self, target: Any, on: str | None) -> tuple[str, str]:
        """Resolve a SET key to ``(alias, property)``."""
        if isinstance(target, FieldDescriptor):
            alias = on or (
                self._alias_for_cls(target.owner) if target.owner else self._root_alias
            )
            return alias, target.field_name
        text = validate_reference(str(target), "assignment target")
        if "." in text:
            alias, prop = text.split(".", 1)
            return alias, prop
        return on or self._last_alias, text

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        *agg_exprs: AggExpr,
        group_by: str | ValueExpr | Sequence[str | ValueExpr] | None = None,
    ) -> QueryBuilder[T]:
        """Add aggregation expressions to the ``RETURN`` clause.

        Parameters
        ----------
        *agg_exprs:
            One or more :class:`~runic.ogm.query.expressions.AggExpr` instances
            created by the helper functions
            :func:`~runic.ogm.query.expressions.count`,
            :func:`~runic.ogm.query.expressions.avg`, etc.
        group_by:
            Alias to keep in the ``RETURN`` clause alongside the aggregations
            (Cypher grouping is implicit — any non-aggregated return term acts
            as a GROUP BY key)::

                .aggregate(count("*").as_("friend_count"), group_by="u")
                # RETURN u, count(*) AS friend_count

        Examples
        --------
        .. code-block:: python

            from runic.ogm.query import count, avg

            result = (
                session.query(User)
                .alias("u")
                .traverse(User.friends)
                .aggregate(count("*").as_("friend_count"), group_by="u")
                .all_rows()  # list[dict] with {"u": ..., "friend_count": int}
            )

            avg_age = (
                session.query(User).aggregate(avg(User.age).as_("average_age")).scalar()
            )
        """
        for key in group_by if isinstance(group_by, (list, tuple)) else [group_by]:
            if isinstance(key, str):
                validate_reference(key, "group_by key")
        self._agg_exprs = list(agg_exprs)
        self._group_by_alias = group_by
        return self

    # ------------------------------------------------------------------
    # Build (compile to Cypher)
    # ------------------------------------------------------------------

    def _append_where_and_traversals(self, parts: list[str]) -> None:
        """Append root WHERE, WITH pipeline, traversals, and post-traversal WHERE.

        Shared by :meth:`build` and the fulltext/vector builders so the Cypher
        clause ordering stays consistent across all three. Root conditions must
        precede any OPTIONAL MATCH (FalkorDB applies WHERE to the preceding
        clause), so they are split from traversal-target conditions here.
        """
        if self._where_exprs and self._pipeline:
            root_exprs, post_exprs = self._split_where_exprs()
        else:
            root_exprs = []
            post_exprs = self._where_exprs

        if root_exprs:
            parts.append(f"WHERE {self._compile_and(root_exprs)}")
        parts.extend(clause.to_cypher(self) for clause in self._pipeline)
        if post_exprs:
            parts.append(f"WHERE {self._compile_and(post_exprs)}")

    def _wants_return(self) -> bool:
        """Whether this statement should emit a RETURN clause at all."""
        asked = bool(
            self._returning
            or self._agg_exprs
            or self._project_fields
            or self._return_aliases
        )
        if asked:
            return True
        return not any(
            isinstance(clause, (SetClause, DeleteClause)) for clause in self._pipeline
        )

    def _compile_and(self, exprs: list[Expr]) -> str:
        """Compile one or more expressions into a single (AND-joined) condition."""
        expr = exprs[0] if len(exprs) == 1 else CompoundExpr(op="AND", operands=exprs)
        return self._compile_expr(expr)

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile the accumulated builder state to a ``(cypher, params)`` pair.

        This is the core compilation step; all terminal methods call it
        internally.  You can also call it directly for debugging or to
        integrate with custom execution logic::

            cypher, params = session.query(User).where(User.active == True).build()
            print(cypher)
            # MATCH (n:User)
            # WHERE n.active = $p0
            # RETURN n

        Returns
        -------
        tuple[str, dict[str, Any]]
            A ``(cypher_string, params_dict)`` pair ready to pass to
            :meth:`~runic.ogm.session.session.Session.execute`.
        """
        # Reset params for each build call so multiple .all() calls are clean.
        self._param_counter = 0
        self._params = {}
        self._declared_params = set()

        parts: list[str] = []

        # ── Root MATCH ──────────────────────────────────────────────────
        root_meta = self._meta.get_node_meta(self._root_cls)
        if root_meta is None:
            raise ValueError(
                f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            )
        _lc = getattr(self._dialect, "labels_clause", None)
        labels_str = _lc(root_meta.labels) if _lc else ":".join(root_meta.labels)
        _sw = getattr(self._dialect, "subtype_where", None)
        subtype_filter = _sw(self._root_alias, root_meta.labels) if _sw else None
        parts.append(f"MATCH ({self._root_alias}:{labels_str})")
        if subtype_filter:
            parts.append(f"WHERE {subtype_filter}")

        # ── WHERE (root conditions) + WITH + Traversal + WHERE (post)
        #
        # Correct Cypher ordering when traversals are present:
        #   MATCH (root)
        #   WHERE <root conditions>   ← must precede OPTIONAL MATCH
        #   [WITH ...]                ← pipelining, precedes traversal
        #   OPTIONAL MATCH ...
        #   WHERE <traversal-target conditions>
        #
        # Without this split, WHERE would apply to the OPTIONAL MATCH clause
        # and turn root filters into null-producing predicates for non-matching
        # root nodes (FalkorDB applies WHERE to the preceding clause).
        # ─────────────────────────────────────────────────────────────────
        self._append_where_and_traversals(parts)

        # ── RETURN ────────────────────────────────────────────────────────
        # A statement that writes returns nothing unless asked. The default
        # RETURN names the matched variable, which after a DELETE names a node
        # that no longer exists, and after a bulk SET would ship every row the
        # write touched back to the caller.
        if self._wants_return():
            parts.append(self._compile_return())

        # ── ORDER BY ─────────────────────────────────────────────────────
        if self._order:
            order_str = ", ".join(o.to_cypher(self) for o in self._order)
            parts.append(f"ORDER BY {order_str}")

        # ── SKIP / LIMIT ─────────────────────────────────────────────────
        parts.extend(self._compile_paging())

        cypher = "\n".join(parts)
        return cypher, dict(self._params)

    def parameter_names(self) -> tuple[str, ...]:
        """The caller-bound parameter names this statement declares, sorted.

        Read off the compiled statement rather than maintained beside it, so it
        cannot drift: a statement that gains a ``LIMIT $limit`` reports it
        immediately.  This is what lets a statement catalogue be checked —
        enumerate the statements, bind each one's parameters, run the lot.

        Example
        -------
        .. code-block:: python

            stmt = (
                select(Message).where(Message.id > param("after")).limit(param("limit"))
            )
            stmt.parameter_names()  # ('after', 'limit')
        """
        self.build()
        return tuple(sorted(self._declared_params))

    def bind(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Compile, then merge caller-supplied values over the auto-bound ones.

        Raises if the statement declares a parameter the caller did not supply —
        a missing ``$parameter`` is otherwise a silent null in Cypher, which
        matches nothing and looks exactly like an empty archive.
        """
        supplied = dict(params or {})
        missing = sorted(self._declared_params - supplied.keys())
        if missing:
            msg = (
                f"statement is missing values for declared parameter(s): "
                f"{', '.join(missing)}"
            )
            raise ValueError(msg)
        unknown = sorted(supplied.keys() - self._declared_params)
        if unknown:
            log.debug("extra parameters supplied and ignored: %s", ", ".join(unknown))
        return {**self._params, **supplied}

    # ------------------------------------------------------------------
    # Terminal methods (sync)
    # ------------------------------------------------------------------

    def all(self, params: Mapping[str, Any] | None = None) -> list[T]:
        """Execute and return all matching Node instances.

        The return type is the root class (or the alias set by
        :meth:`return_target`).  Results are decoded and registered in the
        session identity map.

        Returns
        -------
        list[T]
            Decoded Node instances of the root type (or target type when
            ``return_target()`` was called).
        """
        self._check_bound()
        cypher, _ = self.build()
        log.debug("QueryBuilder.all: %s", cypher)
        result = self._session.execute(cypher, self.bind(params))
        return self._decode_node_result(result)

    def one(self, params: Mapping[str, Any] | None = None) -> T | None:
        """Execute and return the first matching Node instance, or ``None``.

        Internally calls ``.limit(1).all()`` and returns the first element.
        """
        self.limit(1)
        items = self.all(params)
        return items[0] if items else None

    def all_with_edges(
        self, params: Mapping[str, Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """Execute and return tuples of ``(NodeA, EdgeModel, NodeB)``.

        Requires :meth:`return_nodes` to specify node aliases and
        :meth:`return_edge` to specify the edge alias.  The edge is decoded
        via :meth:`~runic.ogm.mapper.mapper.Mapper.decode_edge`.

        Returns
        -------
        list[tuple]
            Each element is a tuple whose order matches the aliases given to
            ``return_nodes()`` with the edge inserted at its position in
            ``return_edge()``.

        Example
        -------
        .. code-block:: python

            rows = (
                session.query(User)
                .alias("u")
                .traverse(User.rated, edge_alias="r")
                .alias("m")
                .return_nodes("u", "m")
                .return_edge("r")
                .all_with_edges()
            )
            for user, rated_edge, movie in rows:
                print(f"{user.name} rated {movie.title} with {rated_edge.score}")
        """
        self._check_bound()
        cypher, _ = self.build()
        log.debug("QueryBuilder.all_with_edges: %s", cypher)
        result = self._session.execute(cypher, self.bind(params))
        return self._decode_edge_result(result)

    def all_rows(self, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute and return raw column-keyed dicts.

        Useful for multi-alias returns, aggregations, or scalar projections
        where mixed types are in the result set::

            rows = q.aggregate(count("*").as_("n"), group_by="u").all_rows()
            # [{"u": <User>, "n": 5}, ...]
        """
        self._check_bound()
        cypher, _ = self.build()
        log.debug("QueryBuilder.all_rows: %s", cypher)
        result = self._session.execute(cypher, self.bind(params))
        return self._decode_rows_as_dicts(result)

    def count(self, params: Mapping[str, Any] | None = None) -> int:
        """Execute a ``count(*)`` variant and return the integer count.

        Overrides any existing RETURN spec to emit ``RETURN count(*)``.
        Ignores :meth:`limit` and :meth:`skip`.
        """
        self._check_bound()
        saved_agg = self._agg_exprs
        saved_group = self._group_by_alias
        saved_return = self._return_aliases
        saved_project = self._project_fields

        from runic.ogm.query.expressions import count as _count_fn

        self._agg_exprs = [_count_fn("*").as_("_count")]
        self._group_by_alias = None
        self._return_aliases = None
        self._project_fields = []

        try:
            cypher, _ = self.build()
            log.debug("QueryBuilder.count: %s", cypher)
            result = self._session.execute(cypher, self.bind(params))
        finally:
            # Always restore builder state, even if build()/execute() raises, so
            # the instance stays reusable.
            self._agg_exprs = saved_agg
            self._group_by_alias = saved_group
            self._return_aliases = saved_return
            self._project_fields = saved_project

        if result.rows:
            return int(result.rows[0][0])
        return 0

    def scalar(self, params: Mapping[str, Any] | None = None) -> Any:
        """Execute and return the first column of the first row, or ``None``."""
        self._check_bound()
        cypher, _ = self.build()
        result = self._session.execute(cypher, self.bind(params))
        if result.rows and result.rows[0]:
            return result.rows[0][0]
        return None

    def scalars(self, params: Mapping[str, Any] | None = None) -> list[Any]:
        """Execute and return the first column of every row as a flat list."""
        self._check_bound()
        cypher, _ = self.build()
        result = self._session.execute(cypher, self.bind(params))
        return [row[0] for row in result.rows]

    # ------------------------------------------------------------------
    # Internal: traversal registration (called by TraversalStep.alias)
    # ------------------------------------------------------------------

    def register_traversal(
        self,
        fd: FieldDescriptor,
        source_alias: str,
        target_alias: str,
        *,
        optional: bool,
        edge_alias: str | None,
        min_hops: int,
        max_hops: int | None,
        types: Sequence[str] | None = None,
        direction: str | None = None,
    ) -> QueryBuilder[T]:
        """Append a MATCH clause for one traversal step and register aliases.

        Called by :meth:`TraversalStep.alias` to complete a traversal step.
        """
        # Resolve target class and label
        raw_target = fd.target
        target_cls = (
            self._meta.resolve_target(raw_target)
            if isinstance(raw_target, str)
            else raw_target
        )
        if target_cls is None:
            target_label = str(raw_target) if raw_target else "Node"
        else:
            node_meta = self._meta.get_node_meta(target_cls)
            target_label = node_meta.primary_label if node_meta else target_cls.__name__

        # Build the relationship part of the pattern. An alternation matches
        # each edge once even when several of its types would apply, which two
        # separate patterns would not.
        requires: tuple[str, str] | None = None
        if types:
            requires = (
                CypherFeature.RELATIONSHIP_ALTERNATION,
                "relationship type alternation ([:A|B])",
            )
            rel_type = "|".join(
                validate_identifier(t, "relationship type") for t in types
            )
        else:
            rel_type = fd.relationship or "REL"
        edge_direction = direction or fd.direction or "OUTGOING"

        if min_hops == 1 and max_hops == 1:
            hop_str = ""
        elif max_hops is None:
            hop_str = f"*{min_hops}.."
        else:
            hop_str = f"*{min_hops}..{max_hops}"

        if edge_alias:
            rel_part = f"[{edge_alias}:{rel_type}{hop_str}]"
        else:
            rel_part = f"[:{rel_type}{hop_str}]"

        target_part = f"({target_alias}:{target_label})"

        if edge_direction == "OUTGOING":
            pattern = f"({source_alias})-{rel_part}->{target_part}"
        elif edge_direction == "INCOMING":
            pattern = f"({source_alias})<-{rel_part}-{target_part}"
        else:
            pattern = f"({source_alias})-{rel_part}-{target_part}"

        self._pipeline.append(
            MatchClause(pattern, optional=optional, requires=requires)
        )

        # Register target node alias
        if target_cls is not None:
            self._set_alias(target_alias, target_cls)

        # Register edge alias
        if edge_alias is not None:
            edge_cls = fd.edge_model
            if isinstance(edge_cls, str):
                edge_cls = self._meta.resolve_target(edge_cls)
            if edge_cls is not None:
                self._set_alias(edge_alias, edge_cls)

        self._last_alias = target_alias
        return self

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _set_alias(self, alias: str, cls: type) -> None:
        self._alias_map[alias] = cls
        self._cls_aliases.setdefault(cls, [])
        if alias not in self._cls_aliases[cls]:
            self._cls_aliases[cls].append(alias)
