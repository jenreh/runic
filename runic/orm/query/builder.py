"""Fluent query builder for the runic ORM.

The :class:`QueryBuilder` (and its async twin :class:`AsyncQueryBuilder`)
provide a chainable API for constructing graph queries against FalkorDB without
writing raw Cypher.  Queries are compiled lazily—Cypher + parameters are only
generated when a terminal method is called (``all()``, ``one()``, ``count()``,
etc.).

Architecture
------------
- :meth:`~Session.query` is the entry point; it returns a ``QueryBuilder[T]``
  bound to the session and the root Node class.
- All intermediate methods (``where``, ``traverse``, ``alias``, etc.) mutate
  the builder **in-place** and return ``self`` for chaining.
- :meth:`build` compiles the accumulated state to ``(cypher_str, params_dict)``.
- Terminal methods call :meth:`build`, execute via the session, and decode
  results using the existing ``Mapper`` / ``map_cypher_result`` machinery.

Quick reference
---------------

.. code-block:: python

    # ── Simple filter ─────────────────────────────────────────────────────
    users = (
        session.query(User)
        .where(User.name == "Alice")
        .where(User.age > 18)
        .order_by(User.age, desc=True)
        .limit(20)
        .all()
    )

    # ── Single-hop traversal (OPTIONAL MATCH by default) ──────────────────
    friends = (
        session.query(User)
        .alias("u")
        .where(User.id == uid)
        .traverse(User.friends)
        .alias("f")
        .where(User.age > 25, on="f")
        .return_target("f")
        .all()
    )

    # ── Traversal with edge properties ────────────────────────────────────
    rows = (
        session.query(User)
        .alias("u")
        .traverse(User.rated, edge_alias="r")
        .alias("m")
        .where(Rated.score > 4.0, on="r")
        .return_nodes("u", "m")
        .return_edge("r")
        .all_with_edges()  # list[tuple[User, Rated, Movie]]
    )

    # ── Multi-hop traversal ───────────────────────────────────────────────
    posts = (
        session.query(User)
        .alias("u")
        .traverse(User.friends)
        .alias("f")
        .traverse(User.authored_posts)
        .alias("p")
        .where(Post.title.contains("graph"), on="p")
        .return_target("p")
        .all()
    )

    # ── Variable-length paths ─────────────────────────────────────────────
    ancestors = (
        session.query(Person)
        .alias("p")
        .where(Person.id == start_id)
        .repeat(Person.parent, min_hops=1, max_hops=5)
        .alias("anc")
        .all()
    )

    # ── Aggregation ───────────────────────────────────────────────────────
    from runic.orm.query import count, avg

    result = (
        session.query(User)
        .alias("u")
        .traverse(User.friends)
        .aggregate(count("*").as_("friend_count"), group_by="u")
        .all_rows()  # list[dict] with {"u": User, "friend_count": int}
    )

    # ── FalkorDB fulltext search ──────────────────────────────────────────
    posts = (
        session.fulltext_search(Post, query="graph databases", fields=["title"])
        .where(Post.published == True)
        .all()
    )

    # ── FalkorDB vector KNN search ────────────────────────────────────────
    similar = (
        session.vector_search(Document, field=Document.embedding, vector=my_vec, k=10)
        .where(Document.active == True)
        .all()
    )

    # ── Raw escape hatch (still typed via Repository.cypher) ─────────────
    repo.cypher("MATCH (n:User) WHERE n.score > 0 RETURN n", returns=User)

Cypher generation rules
-----------------------
1. ``MATCH (root_alias:Label)`` is emitted for the root class.
2. Each :meth:`traverse` / :meth:`repeat` appends an ``OPTIONAL MATCH`` (or
   ``MATCH``) clause: ``(src)-[:TYPE]->(tgt:Label)`` or
   ``(src)-[edge:TYPE]->(tgt:Label)`` when an edge alias was given.
3. Variable-length paths use the ``*min..max`` quantifier:
   ``(src)-[:TYPE*1..5]->(tgt:Label)``.
4. :meth:`where` conditions are collected and emitted as a single ``WHERE``
   clause joined by ``AND``.
5. ``RETURN`` emits the last traversal target alias (or root alias) by
   default; use :meth:`return_target`, :meth:`return_nodes`, or
   :meth:`project` to override.
6. TypeConverters are respected: if a field has a ``cypher_fn``
   (e.g. ``"vecf32"``, ``"point"``), the parameter reference is wrapped:
   ``vecf32($p0)`` instead of ``$p0``.
7. All user-supplied values are bound as numbered parameters ``$p0``,
   ``$p1``, … to prevent injection.
"""

from __future__ import annotations

import logging
from typing import Any, Generic, TypeVar

from runic.orm.core.descriptors import FieldDescriptor, FieldInfo
from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
    OrderExpr,
)
from runic.orm.query.traversal import TraversalStep

log = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Internal: compiled match clause
# ---------------------------------------------------------------------------


class _MatchClause:
    """One MATCH or OPTIONAL MATCH clause, plus any WITH pipelining."""

    def __init__(
        self,
        pattern: str,
        *,
        optional: bool = True,
        is_call: bool = False,
    ) -> None:
        self.pattern = pattern
        self.optional = optional
        self.is_call = is_call

    def to_cypher(self) -> str:
        if self.is_call:
            return self.pattern
        prefix = "OPTIONAL MATCH" if self.optional else "MATCH"
        return f"{prefix} {self.pattern}"


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------


class QueryBuilder(Generic[T]):  # noqa: UP046
    """Fluent Cypher query builder for a single root Node class.

    Construct via :meth:`Session.query`::

        q = session.query(User)

    All non-terminal methods return ``self`` so calls can be chained::

        users = session.query(User).where(User.active == True).limit(10).all()

    Parameters
    ----------
    session:
        The :class:`~runic.orm.session.session.Session` (or
        :class:`~runic.orm.session.async_session.AsyncSession`) this builder
        is bound to.
    root_cls:
        The root Node subclass to query.
    """

    def __init__(self, session: Any, root_cls: type[T]) -> None:
        from runic.orm.core.metadata import MetaData

        self._session = session
        self._root_cls: type[T] = root_cls
        _mapper = getattr(session, "mapper", None)
        self._meta: MetaData = getattr(_mapper, "meta", _global_metadata)

        # Alias tracking -------------------------------------------------
        # alias → ORM class (Node or Edge)
        self._alias_map: dict[str, type] = {}
        # ORM class → list of aliases (inverse lookup)
        self._cls_aliases: dict[type, list[str]] = {}
        # The most recently registered target alias (default RETURN target)
        self._last_alias: str = "n"
        # The root node alias
        self._root_alias: str = "n"

        # Register root
        self._set_alias("n", root_cls)

        # Query parts ----------------------------------------------------
        self._match_clauses: list[_MatchClause] = []
        self._with_vars: list[str] | None = None
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
        self._project_fields: list[FieldDescriptor | str] = []

        # Parameter counter ----------------------------------------------
        self._param_counter: int = 0
        self._params: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Dialect access
    # ------------------------------------------------------------------

    @property
    def _dialect(self) -> Any:
        return self._session.mapper.dialect

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
            A :class:`~runic.orm.query.expressions.FilterExpr`,
            :class:`~runic.orm.query.expressions.CompoundExpr`, or
            :class:`~runic.orm.query.expressions.NegatedExpr`.
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
    ) -> TraversalStep:
        """Traverse a declared :func:`~runic.orm.core.descriptors.Relation` field.

        Returns a :class:`~runic.orm.query.traversal.TraversalStep`; call
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
            source_alias=self._last_alias,
            optional=optional,
            edge_alias=edge_alias,
            min_hops=1,
            max_hops=1,
        )

    def repeat(
        self,
        relation_field: FieldDescriptor,
        *,
        min_hops: int = 1,
        max_hops: int | None = None,
        optional: bool = False,
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
            source_alias=self._last_alias,
            optional=optional,
            edge_alias=None,
            min_hops=min_hops,
            max_hops=max_hops,
        )

    # ------------------------------------------------------------------
    # WITH (multi-stage pipelining)
    # ------------------------------------------------------------------

    def with_(self, *aliases: str) -> QueryBuilder[T]:
        """Insert a ``WITH`` clause to pipeline results between query stages.

        Use when you want to filter/aggregate in one stage before continuing
        a traversal in the next::

            (
                session.query(User)
                .alias("u")
                .where(User.active == True)
                .with_("u")  # WITH u
                .traverse(User.posts)
                .alias("p")
                .return_target("p")
                .all()
            )

        Parameters
        ----------
        *aliases:
            Cypher variable names to carry forward (e.g. ``"u"``, ``"f"``).
        """
        self._with_vars = list(aliases)
        return self

    # ------------------------------------------------------------------
    # Ordering / pagination
    # ------------------------------------------------------------------

    def order_by(
        self,
        field: FieldDescriptor | str,
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
        if isinstance(field, FieldDescriptor):
            alias = (
                self._alias_for_cls(field.owner) if field.owner else self._root_alias
            )
            self._order.append(OrderExpr(alias=alias, prop=field.field_name, desc=desc))
        else:
            self._order.append(
                OrderExpr(alias=None, prop=None, raw=str(field), desc=desc)
            )
        return self

    def limit(self, n: int) -> QueryBuilder[T]:
        """Set ``LIMIT n`` on the query."""
        self._limit_val = n
        return self

    def skip(self, n: int) -> QueryBuilder[T]:
        """Set ``SKIP n`` (offset) on the query."""
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
        The edge is decoded via :meth:`~runic.orm.mapper.mapper.Mapper.decode_edge`
        and included as the middle element of tuples returned by
        :meth:`all_with_edges`.
        """
        self._edge_alias_for_result = alias
        return self

    def project(self, *fields: FieldDescriptor | str) -> QueryBuilder[T]:
        """Return only specific property values (scalar projection).

        Terminal method ``.scalars()`` returns the projected values as a flat
        list; ``.all_rows()`` returns a list of dicts::

            # Scalar list
            names = session.query(User).project(User.name).scalars()

            # Dict list
            rows = session.query(User).project(User.name, User.age).all_rows()
        """
        self._project_fields = list(fields)
        return self

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        *agg_exprs: AggExpr,
        group_by: str | None = None,
    ) -> QueryBuilder[T]:
        """Add aggregation expressions to the ``RETURN`` clause.

        Parameters
        ----------
        *agg_exprs:
            One or more :class:`~runic.orm.query.expressions.AggExpr` instances
            created by the helper functions
            :func:`~runic.orm.query.expressions.count`,
            :func:`~runic.orm.query.expressions.avg`, etc.
        group_by:
            Alias to keep in the ``RETURN`` clause alongside the aggregations
            (Cypher grouping is implicit — any non-aggregated return term acts
            as a GROUP BY key)::

                .aggregate(count("*").as_("friend_count"), group_by="u")
                # RETURN u, count(*) AS friend_count

        Examples
        --------
        .. code-block:: python

            from runic.orm.query import count, avg

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
        self._agg_exprs = list(agg_exprs)
        self._group_by_alias = group_by
        return self

    # ------------------------------------------------------------------
    # Build (compile to Cypher)
    # ------------------------------------------------------------------

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
            :meth:`~runic.orm.session.session.Session.execute`.
        """
        # Reset params for each build call so multiple .all() calls are clean.
        self._param_counter = 0
        self._params = {}

        parts: list[str] = []

        # ── Root MATCH ──────────────────────────────────────────────────
        root_meta = self._meta.get_node_meta(self._root_cls)
        if root_meta is None:
            raise ValueError(
                f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            )
        labels_str = ":".join(root_meta.labels)
        parts.append(f"MATCH ({self._root_alias}:{labels_str})")

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

        # ── WITH (pipeline — emitted before traversals) ──────────────────
        if self._with_vars:
            parts.append(f"WITH {', '.join(self._with_vars)}")

        # ── Traversal clauses ────────────────────────────────────────────
        parts.extend(mc.to_cypher() for mc in self._match_clauses)

        # ── WHERE (post-traversal conditions on traversal targets / edges)
        if post_exprs:
            cond = self._compile_expr(
                post_exprs[0]
                if len(post_exprs) == 1
                else CompoundExpr(op="AND", operands=post_exprs)
            )
            parts.append(f"WHERE {cond}")

        # ── RETURN ────────────────────────────────────────────────────────
        parts.append(self._compile_return())

        # ── ORDER BY ─────────────────────────────────────────────────────
        if self._order:
            order_str = ", ".join(o.to_cypher() for o in self._order)
            parts.append(f"ORDER BY {order_str}")

        # ── SKIP / LIMIT ─────────────────────────────────────────────────
        if self._skip_val is not None:
            parts.append(f"SKIP {self._skip_val}")
        if self._limit_val is not None:
            parts.append(f"LIMIT {self._limit_val}")

        cypher = "\n".join(parts)
        return cypher, dict(self._params)

    # ------------------------------------------------------------------
    # Terminal methods (sync)
    # ------------------------------------------------------------------

    def all(self) -> list[T]:
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
        cypher, params = self.build()
        log.debug("QueryBuilder.all: %s", cypher)
        result = self._session.execute(cypher, params)
        return self._decode_node_result(result)

    def one(self) -> T | None:
        """Execute and return the first matching Node instance, or ``None``.

        Internally calls ``.limit(1).all()`` and returns the first element.
        """
        self.limit(1)
        items = self.all()
        return items[0] if items else None

    def all_with_edges(self) -> list[tuple[Any, ...]]:
        """Execute and return tuples of ``(NodeA, EdgeModel, NodeB)``.

        Requires :meth:`return_nodes` to specify node aliases and
        :meth:`return_edge` to specify the edge alias.  The edge is decoded
        via :meth:`~runic.orm.mapper.mapper.Mapper.decode_edge`.

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
        cypher, params = self.build()
        log.debug("QueryBuilder.all_with_edges: %s", cypher)
        result = self._session.execute(cypher, params)
        return self._decode_edge_result(result)

    def all_rows(self) -> list[dict[str, Any]]:
        """Execute and return raw column-keyed dicts.

        Useful for multi-alias returns, aggregations, or scalar projections
        where mixed types are in the result set::

            rows = q.aggregate(count("*").as_("n"), group_by="u").all_rows()
            # [{"u": <User>, "n": 5}, ...]
        """
        cypher, params = self.build()
        log.debug("QueryBuilder.all_rows: %s", cypher)
        result = self._session.execute(cypher, params)
        return self._decode_rows_as_dicts(result)

    def count(self) -> int:
        """Execute a ``count(*)`` variant and return the integer count.

        Overrides any existing RETURN spec to emit ``RETURN count(*)``.
        Ignores :meth:`limit` and :meth:`skip`.
        """
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
        log.debug("QueryBuilder.count: %s", cypher)
        result = self._session.execute(cypher, params)

        # Restore
        self._agg_exprs = saved_agg
        self._group_by_alias = saved_group
        self._return_aliases = saved_return
        self._project_fields = saved_project

        if result.rows:
            return int(result.rows[0][0])
        return 0

    def scalar(self) -> Any:
        """Execute and return the first column of the first row, or ``None``."""
        result = self._session.execute(*self.build())
        if result.rows and result.rows[0]:
            return result.rows[0][0]
        return None

    def scalars(self) -> list[Any]:
        """Execute and return the first column of every row as a flat list."""
        result = self._session.execute(*self.build())
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

        # Build the relationship part of the pattern
        rel_type = fd.relationship or "REL"
        direction = fd.direction or "OUTGOING"

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

        if direction == "OUTGOING":
            pattern = f"({source_alias})-{rel_part}->{target_part}"
        elif direction == "INCOMING":
            pattern = f"({source_alias})<-{rel_part}-{target_part}"
        else:
            pattern = f"({source_alias})-{rel_part}-{target_part}"

        self._match_clauses.append(_MatchClause(pattern, optional=optional))

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
    # Internal: Cypher expression compilation
    # ------------------------------------------------------------------

    def _compile_expr(self, expr: Expr) -> str:
        """Recursively compile an Expr tree to a Cypher predicate string."""
        if isinstance(expr, FilterExpr):
            return self._compile_filter(expr)
        if isinstance(expr, CompoundExpr):
            parts = [f"({self._compile_expr(op)})" for op in expr.operands]
            return f" {expr.op} ".join(parts)
        if isinstance(expr, NegatedExpr):
            return f"NOT ({self._compile_expr(expr.operand)})"
        raise TypeError(f"Unsupported expression type: {type(expr)!r}")

    def _compile_filter(self, expr: FilterExpr) -> str:
        """Compile a single FilterExpr to a Cypher condition string."""
        alias = expr.alias or self._alias_for_cls(expr.cls)

        # Null checks have no parameter
        if expr.op == "IS NULL":
            return f"{alias}.{expr.prop} IS NULL"
        if expr.op == "IS NOT NULL":
            return f"{alias}.{expr.prop} IS NOT NULL"

        # Look up converter for this field
        fi = self._find_field_info(expr.cls, expr.prop)
        converter = fi.field.converter if fi is not None else None

        # Convert value to graph representation
        param_value = expr.value
        if converter is not None and param_value is not None:
            param_value = converter.to_graph(param_value)

        param_name = self._next_param(param_value)

        # Wrap param ref with cypher_fn if needed (dialect-aware)
        cypher_fn = self._dialect.cypher_fn_for_field(fi) if fi is not None else None
        param_ref = f"{cypher_fn}(${param_name})" if cypher_fn else f"${param_name}"

        if expr.op in ("IN", "NOT IN"):
            prefix = "NOT " if (expr.negate or expr.op == "NOT IN") else ""
            return f"{prefix}{alias}.{expr.prop} IN ${param_name}"

        if expr.negate:
            return f"NOT ({alias}.{expr.prop} {expr.op} {param_ref})"
        return f"{alias}.{expr.prop} {expr.op} {param_ref}"

    def _compile_return(self) -> str:
        """Compile the RETURN clause."""
        distinct_kw = "DISTINCT " if self._distinct else ""

        # Aggregation mode
        if self._agg_exprs:
            cls_to_alias: dict[type, str] = {
                cls: aliases[0] for cls, aliases in self._cls_aliases.items() if aliases
            }
            agg_parts = [e.to_cypher(cls_to_alias) for e in self._agg_exprs]
            if self._group_by_alias:
                return f"RETURN {distinct_kw}{self._group_by_alias}, {', '.join(agg_parts)}"
            return f"RETURN {distinct_kw}{', '.join(agg_parts)}"

        # Scalar projection
        if self._project_fields:
            proj_parts: list[str] = []
            for f in self._project_fields:
                if isinstance(f, FieldDescriptor):
                    alias = (
                        self._alias_for_cls(f.owner) if f.owner else self._root_alias
                    )
                    proj_parts.append(f"{alias}.{f.field_name}")
                else:
                    proj_parts.append(str(f))
            return f"RETURN {distinct_kw}{', '.join(proj_parts)}"

        # Explicit return aliases
        if self._return_aliases:
            extra = []
            if self._edge_alias_for_result:
                extra.append(self._edge_alias_for_result)
            all_parts = list(self._return_aliases)
            if (
                self._edge_alias_for_result
                and self._edge_alias_for_result not in all_parts
            ):
                # Insert edge between the two node aliases
                all_parts.insert(1, self._edge_alias_for_result)
            return f"RETURN {distinct_kw}{', '.join(all_parts)}"

        # Default: return last alias
        return f"RETURN {distinct_kw}{self._last_alias}"

    # ------------------------------------------------------------------
    # Internal: result decoding
    # ------------------------------------------------------------------

    def _decode_node_result(self, result: Any) -> list[T]:
        """Decode a single-column node result into ORM entities."""
        mapper = self._session.mapper
        register = self._session.register_or_get

        # Determine the target class for decoding
        return_alias = (
            self._return_aliases[0] if self._return_aliases else self._last_alias
        )
        target_cls = self._alias_map.get(return_alias, self._root_cls)

        entities: list[T] = []
        for row in result.rows:
            val = row[0]
            if val is None:
                continue
            decoded = mapper.decode_node(val, target_cls)
            entities.append(register(decoded))
        return entities

    def _decode_edge_result(self, result: Any) -> list[tuple[Any, ...]]:
        """Decode multi-column result into (NodeA, EdgeModel, NodeB) tuples."""
        mapper = self._session.mapper
        register = self._session.register_or_get

        # Column order: return_aliases[0], edge_alias, return_aliases[1]
        edge_alias = self._edge_alias_for_result

        # Build ordered column list matching the RETURN clause
        columns: list[tuple[str, bool]] = []
        if self._return_aliases:
            for i, a in enumerate(self._return_aliases):
                if i == 1 and edge_alias and edge_alias not in self._return_aliases:
                    columns.append((edge_alias, True))
                columns.append((a, False))
        if not columns:
            columns = [(self._last_alias, False)]

        tuples: list[tuple[Any, ...]] = []
        for row in result.rows:
            decoded_row: list[Any] = []
            for col_idx, (col_alias, is_edge) in enumerate(columns):
                val = row[col_idx] if col_idx < len(row) else None
                if val is None:
                    decoded_row.append(None)
                    continue
                if is_edge:
                    edge_cls = self._alias_map.get(col_alias)
                    decoded_row.append(mapper.decode_edge(val, edge_cls))
                else:
                    node_cls = self._alias_map.get(col_alias, self._root_cls)
                    decoded = mapper.decode_node(val, node_cls)
                    decoded_row.append(register(decoded))
            tuples.append(tuple(decoded_row))
        return tuples

    def _decode_rows_as_dicts(self, result: Any) -> list[dict[str, Any]]:
        """Decode a multi-column result into column-keyed dicts."""
        mapper = self._session.mapper
        register = self._session.register_or_get
        header = result.columns

        rows: list[dict[str, Any]] = []
        for row in result.rows:
            d: dict[str, Any] = {}
            for i, val in enumerate(row):
                col_name = header[i] if i < len(header) else str(i)
                alias = col_name
                cls = self._alias_map.get(alias)
                if cls is not None and val is not None:
                    # Check if this is a Node class (has NodeMeta)
                    node_meta = self._meta.get_node_meta(cls)
                    edge_meta = self._meta.get_edge_meta(cls)
                    if node_meta is not None:
                        val = register(mapper.decode_node(val, cls))
                    elif edge_meta is not None:
                        val = mapper.decode_edge(val, cls)
                d[col_name] = val
            rows.append(d)
        return rows

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _set_alias(self, alias: str, cls: type) -> None:
        self._alias_map[alias] = cls
        self._cls_aliases.setdefault(cls, [])
        if alias not in self._cls_aliases[cls]:
            self._cls_aliases[cls].append(alias)

    def _alias_for_cls(self, cls: type) -> str:
        """Return the first registered Cypher alias for *cls*, or root alias."""
        aliases = self._cls_aliases.get(cls)
        if aliases:
            return aliases[0]
        # Fallback: if cls is the root, return root alias
        if cls is self._root_cls:
            return self._root_alias
        return self._last_alias

    def _next_param(self, value: Any) -> str:
        """Allocate a new positional parameter, store value, return name."""
        name = f"p{self._param_counter}"
        self._param_counter += 1
        self._params[name] = value
        return name

    def _find_field_info(self, cls: type, prop: str) -> FieldInfo | None:
        """Look up a FieldInfo by class and property name."""
        node_meta = self._meta.get_node_meta(cls)
        if node_meta:
            return next((fi for fi in node_meta.fields if fi.name == prop), None)
        edge_meta = self._meta.get_edge_meta(cls)
        if edge_meta:
            return next((fi for fi in edge_meta.fields if fi.name == prop), None)
        return None

    def _split_where_exprs(self) -> tuple[list[Expr], list[Expr]]:
        """Split WHERE expressions into root-targeting and post-traversal groups.

        Root expressions reference only the root alias (or its class) and are
        safe to emit between the root MATCH and any OPTIONAL MATCH clauses.
        Post-traversal expressions reference traversal targets or edges and must
        come after all MATCH/OPTIONAL MATCH clauses.
        """
        root: list[Expr] = []
        post: list[Expr] = []
        for expr in self._where_exprs:
            if self._expr_targets_root_only(expr):
                root.append(expr)
            else:
                post.append(expr)
        return root, post

    def _expr_targets_root_only(self, expr: Expr) -> bool:
        """Return True if *expr* references only the root Cypher alias."""
        if isinstance(expr, FilterExpr):
            if expr.alias is not None:
                return expr.alias == self._root_alias
            # No explicit alias: resolve via class lookup
            resolved = self._alias_for_cls(expr.cls)
            return resolved == self._root_alias
        if isinstance(expr, CompoundExpr):
            return all(self._expr_targets_root_only(op) for op in expr.operands)
        if isinstance(expr, NegatedExpr):
            return self._expr_targets_root_only(expr.operand)
        return False


# ---------------------------------------------------------------------------
# AsyncQueryBuilder
# ---------------------------------------------------------------------------


class AsyncQueryBuilder(QueryBuilder[T]):
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

    async def all(self) -> list[T]:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.all`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_node_result(result)

    async def one(self) -> T | None:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.one`."""
        self.limit(1)
        items = await self.all()
        return items[0] if items else None

    async def all_with_edges(self) -> list[tuple[Any, ...]]:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.all_with_edges`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all_with_edges: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_edge_result(result)

    async def all_rows(self) -> list[dict[str, Any]]:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.all_rows`."""
        cypher, params = self.build()
        log.debug("AsyncQueryBuilder.all_rows: %s", cypher)
        result = await self._session.execute(cypher, params)
        return self._decode_rows_as_dicts(result)

    async def count(self) -> int:  # type: ignore[override]
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

    async def scalars(self) -> list[Any]:  # type: ignore[override]
        """Async version of :meth:`~QueryBuilder.scalars`."""
        result = await self._session.execute(*self.build())
        return [row[0] for row in result.rows]


# ---------------------------------------------------------------------------
# FulltextQueryBuilder
# ---------------------------------------------------------------------------


class FulltextQueryBuilder(QueryBuilder[T]):
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


class VectorQueryBuilder(QueryBuilder[T]):
    """QueryBuilder variant for FalkorDB vector KNN search.

    Constructed via :meth:`~runic.orm.session.session.Session.vector_search`.
    Appends a KNN distance expression to the ORDER BY and RETURN clauses.

    The field must have ``index_type="VECTOR"`` and an HNSW vector index
    must be created via :meth:`~runic.orm.schema.schema_manager.SchemaManager`::

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

    Note
    ----
    The exact FalkorDB KNN Cypher syntax may vary by version.  If the above
    pattern does not work, use ``repo.cypher()`` with a hand-written query.
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

        labels_str = ":".join(root_meta.labels)
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
