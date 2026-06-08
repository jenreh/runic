"""Fluent query builder for the runic ORM.

See :doc:`/query_builder` for the full API reference and examples.

:class:`QueryBuilder` is the core builder; specialised subclasses
(:class:`~runic.orm.query.specialised.AsyncQueryBuilder`,
:class:`~runic.orm.query.specialised.FulltextQueryBuilder`,
:class:`~runic.orm.query.specialised.VectorQueryBuilder`) live in
:mod:`runic.orm.query.specialised`.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, TypeVar

from runic.orm.core.descriptors import FieldDescriptor
from runic.orm.core.metadata import metadata as _global_metadata
from runic.orm.query._compiler import _CypherCompiler
from runic.orm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
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


class QueryBuilder(_CypherCompiler[T]):  # noqa: UP046
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

    def __init__(self, session: Any | None, root_cls: type[T]) -> None:
        from runic.orm.core.metadata import MetaData

        self._session: Any = session  # None when unbound (created via select())
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

        Used by :class:`~runic.orm.session.session.Session` execution methods
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
        self._check_bound()
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
        self._check_bound()
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
        self._check_bound()
        cypher, params = self.build()
        log.debug("QueryBuilder.all_rows: %s", cypher)
        result = self._session.execute(cypher, params)
        return self._decode_rows_as_dicts(result)

    def count(self) -> int:
        """Execute a ``count(*)`` variant and return the integer count.

        Overrides any existing RETURN spec to emit ``RETURN count(*)``.
        Ignores :meth:`limit` and :meth:`skip`.
        """
        self._check_bound()
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
        self._check_bound()
        result = self._session.execute(*self.build())
        if result.rows and result.rows[0]:
            return result.rows[0][0]
        return None

    def scalars(self) -> list[Any]:
        """Execute and return the first column of every row as a flat list."""
        self._check_bound()
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
    # Internal: helpers
    # ------------------------------------------------------------------

    def _set_alias(self, alias: str, cls: type) -> None:
        self._alias_map[alias] = cls
        self._cls_aliases.setdefault(cls, [])
        if alias not in self._cls_aliases[cls]:
            self._cls_aliases[cls].append(alias)
