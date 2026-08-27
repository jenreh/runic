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

from runic.cypher import escape_order_term, validate_identifier, validate_reference
from runic.ogm.core.descriptors import FieldDescriptor
from runic.ogm.core.metadata import metadata as _global_metadata
from runic.ogm.driver import CypherFeature
from runic.ogm.query._compiler import _CypherCompiler
from runic.ogm.query._terminals import _TerminalMixin
from runic.ogm.query._writes import _WriteMixin
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
    NegatedExpr,
    OrderExpr,
)
from runic.ogm.query.values import Alias, AliasedExpr, ValueExpr

log = logging.getLogger(__name__)

T = TypeVar("T")


def _validate_projection(expr: str) -> None:
    """Reject a raw-string projection that is not a plain property reference.

    Thin wrapper over :func:`~runic.cypher.validate_reference`, kept as a named
    function because it is part of this module's tested surface.
    """
    validate_reference(expr, "projection")


def _alias_name(value: Alias | str, purpose: str) -> str:
    """Resolve an alias argument — a handle or a raw name — to its name."""
    if isinstance(value, Alias):
        return value._name  # noqa: SLF001
    return validate_identifier(str(value), purpose)


# ---------------------------------------------------------------------------
# QueryBuilder
# ---------------------------------------------------------------------------


class QueryBuilder(_TerminalMixin, _WriteMixin, _CypherCompiler[T]):  # noqa: UP046
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

    def __init__(
        self,
        session: Any | None,
        root_cls: type[T] | Alias,
        name: str | None = None,
    ) -> None:
        from runic.ogm.core.metadata import MetaData

        # The root variable is named where it is introduced: a handle
        # (select(alias(Message, "m"))) or a plain name (select(Message, "m")).
        # Unnamed, it defaults to "n".
        if isinstance(root_cls, Alias):
            if name is not None:
                msg = (
                    "the handle already names the root variable "
                    f"({root_cls._name!r}); drop the extra name argument"  # noqa: SLF001
                )
                raise TypeError(msg)
            root_name = root_cls._name  # noqa: SLF001
            # The handle's class is untyped (plain ``type``); trust it as T.
            root_type: type[T] = root_cls._cls  # noqa: SLF001  # ty: ignore[invalid-assignment]
        else:
            root_name = (
                validate_identifier(name, "root alias") if name is not None else "n"
            )
            root_type = root_cls

        self._session: Any = session  # None when unbound (created via select())
        self._root_cls: type[T] = root_type
        _mapper = getattr(session, "mapper", None)
        self._meta: MetaData = getattr(_mapper, "meta", _global_metadata)

        # Alias tracking -------------------------------------------------
        # alias → OGM class (Node or Edge)
        self._alias_map: dict[str, type] = {}
        # OGM class → list of aliases (inverse lookup)
        self._cls_aliases: dict[type, list[str]] = {}
        # The most recently registered target alias (default RETURN target)
        self._last_alias: str = root_name
        # The root node alias
        self.root_alias: str = root_name
        # Counter for auto-generated traversal-target names
        self._auto_alias_counter: int = 0

        # Register root
        self._set_alias(root_name, root_type)

        # Query parts ----------------------------------------------------
        # Clauses between the opening MATCH and the RETURN, in call order —
        # WITH before a traversal means something different from WITH after it.
        self._pipeline: list[Clause] = []
        self._where_exprs: list[Expr] = []
        self._order: list[OrderExpr] = []
        self._distinct: bool = False
        self._limit_val: int | ValueExpr | None = None
        self._skip_val: int | ValueExpr | None = None

        # Return specification -------------------------------------------
        # None → auto (last alias or root alias)
        # list of str → explicit aliases / Cypher expressions to return
        self._return_aliases: list[str] | None = None
        # Edge alias to include in .all_with_edges() output
        self._edge_alias_for_result: str | None = None
        # Projection (for .project()) — values, aggregates, or both
        self._project_fields: list[FieldDescriptor | ValueExpr | AggExpr | str] = []
        # Explicit RETURN expressions, set by returning()
        self._returning: list[Any] = []

        # Parameters -------------------------------------------------------
        # Auto-bound values ($p0, $p1, …) allocated during compilation.
        self._param_counter: int = 0
        self.params: dict[str, Any] = {}
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
    # Filtering
    # ------------------------------------------------------------------

    def where(
        self,
        expr: Expr,
        *,
        on: str | Alias | None = None,
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

            With an :func:`~runic.ogm.query.values.alias` handle, prefer
            referencing its properties directly — ``.where(r.score > 4.0)`` —
            over ``on=``.

        Notes
        -----
        Multiple ``.where()`` calls are combined with ``AND``.  To express
        ``OR``, use the ``|`` operator on the expressions before passing::

            .where((User.role == "admin") | (User.role == "mod"))
        """
        if on is not None:
            expr = self._apply_on(expr, _alias_name(on, "where on"))
        self._where_exprs.append(expr)
        return self

    @classmethod
    def _apply_on(cls, expr: Expr, name: str) -> Expr:
        """Pin every filter in *expr* to the Cypher variable *name*.

        Recurses through compound and negated expressions so ``on=`` means the
        same thing for ``(A.x == 1) & (A.y == 2)`` as for a single filter.
        """
        if isinstance(expr, FilterExpr):
            return expr.with_alias(name)
        if isinstance(expr, CompoundExpr):
            return CompoundExpr(
                op=expr.op,
                operands=[cls._apply_on(op, name) for op in expr.operands],
            )
        if isinstance(expr, NegatedExpr):
            return NegatedExpr(operand=cls._apply_on(expr.operand, name))
        return expr

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def traverse(
        self,
        relation_field: Any,
        *,
        to: str | Alias | None = None,
        edge: str | Alias | None = None,
        optional: bool = False,
        from_: str | Alias | None = None,
        types: Sequence[str] | None = None,
        direction: str | None = None,
        hops: int | tuple[int, int | None] | None = None,
    ) -> QueryBuilder[T]:
        """Traverse a declared :func:`~runic.ogm.core.descriptors.Relation` field.

        One call is one Cypher pattern — ``MATCH (u)-[r:RATED]->(m)`` is
        ``.traverse(User.rated, to=m, edge=r)``, and a variable-length walk is
        the same pattern with a quantifier: ``hops=(1, 5)`` → ``[:RATED*1..5]``.

        Parameters
        ----------
        relation_field:
            The ``Relation``-backed field descriptor accessed at class level::

                User.friends  # list[User] = Relation(...)
                User.rated  # list[Movie] = Relation(edge_model=Rated)

            An :func:`~runic.ogm.query.values.alias` handle's attribute works
            too: ``a.co_addressed``.

        to:
            Name for the target node — an :func:`~runic.ogm.query.values.alias`
            handle or a string.  Omitted, a name is generated; name it whenever
            anything later references the target.

        edge:
            When given, a named relationship variable is emitted in the
            pattern (``(u)-[r:RATED]->(m)``), enabling edge-property filters
            (``.where(r.score > 4)``) and :meth:`all_with_edges`.

        optional:
            ``False`` (default) → ``MATCH``, like Cypher's own unmarked case:
            source nodes without the relationship are dropped.
            ``True`` → ``OPTIONAL MATCH`` (left join; sources without the
            relationship survive, carrying nulls).  Note that a ``WHERE`` on
            an optional traversal nullifies rows rather than dropping them.

        from_:
            Traverse out of this variable instead of the cursor.

            The builder keeps a **cursor** — the variable the most recent step
            bound.  Each traversal leaves from it and then advances it to its
            own target, so consecutive calls walk a chain the way a Cypher
            pattern reads: ``(n)-->(f)-->(p)``.  A traversal's source is
            resolved in this order:

            1. ``from_``, when given;
            2. the relation's own handle — ``f.authored_posts`` leaves from
               ``f``, whatever the cursor says;
            3. the cursor — where the previous step landed (the root to begin
               with).

            ``from_`` is the fan-out lever: several traversals leaving the
            same node instead of chaining::

                m = alias(Message, "m")
                q = select(m)
                q = q.traverse(Message.sent_from, from_=m, to="s")
                q = q.traverse(Message.sent_to, from_=m, to="r")  # from m, not s

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

        hops:
            Variable-length quantifier, spelled the way Cypher spells it:

            * ``hops=(1, 5)`` → ``*1..5``
            * ``hops=(2, None)`` → ``*2..`` (unbounded — expensive on dense
              graphs; set an upper bound unless depth is known to be bounded)
            * ``hops=3`` → ``*3..3`` (exactly three)

            Omitted, the pattern is a single fixed hop.  An ``edge`` variable
            cannot be combined with ``hops``: on a variable-length pattern it
            would bind a *list* of relationships, which the mapper does not
            decode — match the path without it, or drop to a raw fragment.

        Examples
        --------
        .. code-block:: python

            u, f = alias(User, "u"), alias(User, "f")
            q = select(u).traverse(User.friends, to=f).where(f.age > 25)

            r = alias(Rated, "r")
            q = select(u).traverse(User.rated, to="m", edge=r).where(r.score >= 4)

            # All ancestors up to depth 5: (e)-[:REPORTS_TO*1..5]->(anc)
            e = alias(Employee, "e")
            q = select(e).traverse(Employee.reports_to, to="anc", hops=(1, 5))
        """
        min_hops, max_hops = self._hop_range(hops)
        if edge is not None and (min_hops, max_hops) != (1, 1):
            msg = (
                "an edge variable on a variable-length pattern binds a list "
                "of relationships, which cannot be decoded — drop edge= or "
                "the hops= quantifier"
            )
            raise TypeError(msg)
        self._flush_pending_paging()
        fd, source = self._traversal_parts(relation_field, from_)
        return self._register_traversal(
            fd=fd,
            source_alias=source,
            target_alias=self._target_name(to),
            optional=optional,
            edge_alias=_alias_name(edge, "edge alias") if edge is not None else None,
            min_hops=min_hops,
            max_hops=max_hops,
            types=types,
            direction=direction,
        )

    @staticmethod
    def _hop_range(hops: int | tuple[int, int | None] | None) -> tuple[int, int | None]:
        """Normalise a ``hops`` argument to ``(min, max)``.

        ``None`` is a single fixed hop; an int is an exact depth; a tuple is
        Cypher's ``*min..max`` with ``None`` for an open upper bound.
        """
        if hops is None:
            return 1, 1
        if isinstance(hops, int):
            min_hops, max_hops = hops, hops
        else:
            min_hops, max_hops = hops
        if min_hops < 0:
            msg = f"hops: minimum must be >= 0, got {min_hops}"
            raise ValueError(msg)
        if max_hops is not None and max_hops < min_hops:
            msg = f"hops: maximum {max_hops} is below minimum {min_hops}"
            raise ValueError(msg)
        return min_hops, max_hops

    def _traversal_parts(
        self, relation_field: Any, from_: str | Alias | None
    ) -> tuple[FieldDescriptor, str]:
        """Resolve the relation descriptor and the source variable name.

        A relation reached through a handle (``a.co_addressed``) names its own
        source; an explicit ``from_`` overrides, and a bare descriptor falls
        back to the most recently registered variable.
        """
        from runic.ogm.query.values import _DEFERRED_ALIAS, PropertyRef

        inferred: str | None = None
        fd = relation_field
        if isinstance(fd, PropertyRef):
            if fd.owner is None:
                msg = f"{fd.prop!r} is not bound to a model class"
                raise TypeError(msg)
            if fd.alias != _DEFERRED_ALIAS:
                inferred = fd.alias
            fd = getattr(fd.owner, fd.prop)
        if not isinstance(fd, FieldDescriptor):
            msg = (
                "traverse() takes a Relation field (User.friends or a handle's "
                f"attribute); got {relation_field!r}"
            )
            raise TypeError(msg)
        if from_ is not None:
            source = _alias_name(from_, "traversal source")
        else:
            source = inferred or self._last_alias
        return fd, source

    def _target_name(self, to: str | Alias | None) -> str:
        """Resolve the traversal-target name, generating one when unnamed."""
        if to is not None:
            return _alias_name(to, "traversal target")
        self._auto_alias_counter += 1
        return f"_t{self._auto_alias_counter}"

    def _flush_pending_paging(self) -> None:
        """Compile pending ORDER BY / SKIP / LIMIT into a ``WITH`` stage.

        The builder compiles in the order it is called: paging written before
        a traversal (or a write) pages *before* it, which in Cypher means a
        ``WITH`` stage carrying the variables bound so far.
        """
        if not (
            self._order or self._limit_val is not None or self._skip_val is not None
        ):
            return
        self._pipeline.append(
            WithClause(
                variables=tuple(self._alias_map.keys()),
                order_by=tuple(self._order),
                limit=self._limit_val,
                skip=self._skip_val,
            )
        )
        self._order = []
        self._limit_val = None
        self._skip_val = None

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

        For the common "page, then expand" shape no explicit ``WITH`` is
        needed: paging calls written before a traversal compile into one
        automatically (the builder compiles in call order)::

            m, r = alias(Message, "m"), alias(Address, "r")
            (
                select(m)
                .where(m.id > param("after"))
                .order_by(m.id)
                .limit(param("limit"))  # pages before the traverse
                .traverse(Message.sent_to, from_=m, to=r, optional=True)
                .project(m.id, collect(r.id, distinct=True).as_("addressed"))
            )

        Reach for ``with_()`` explicitly when a stage computes something —
        ``with_(m, count("*").as_("cnt"))`` — or filters on an aggregate via
        ``where=`` (Cypher's ``HAVING``).
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

    def order_by(self, field: Any, *, desc: bool = False) -> QueryBuilder[T]:
        """Add an ``ORDER BY`` term.

        Parameters
        ----------
        field:
            A field descriptor (``User.name``), a named result column — the
            same ``.as_()`` expression the projection uses — or a raw string.
        desc:
            ``True`` for descending order (default ``False``).

        Examples
        --------
        .. code-block:: python

            q.order_by(User.age)  # ORDER BY n.age ASC
            q.order_by(User.created_at, desc=True)  # ORDER BY n.created_at DESC

            # Bind a result column once, reference it twice
            total = count("*").as_("total")
            q.project(User.city, total).order_by(total, desc=True)
        """
        self._order.append(self._order_term(field, desc=desc))
        return self

    def _order_term(
        self, field: FieldDescriptor | ValueExpr | AggExpr | str, *, desc: bool
    ) -> OrderExpr:
        """Build one ORDER BY term from a descriptor, expression, or raw string.

        A named expression — ``.as_()`` on a value or an aggregate — orders by
        its *result column*: the projection introduced the name, the ORDER BY
        reuses it.
        """
        if isinstance(field, AliasedExpr):
            return OrderExpr(alias=None, prop=None, raw=field.result_name, desc=desc)
        if isinstance(field, AggExpr):
            if not field.result_alias:
                msg = (
                    "order_by() on an aggregate needs a result name; "
                    "give it one with .as_()"
                )
                raise ValueError(msg)
            column = validate_identifier(field.result_alias, "order_by column")
            return OrderExpr(alias=None, prop=None, raw=column, desc=desc)
        if isinstance(field, ValueExpr):
            return OrderExpr(alias=None, prop=None, expr=field, desc=desc)
        if isinstance(field, FieldDescriptor):
            alias = self.alias_for_cls(field.owner) if field.owner else self.root_alias
            return OrderExpr(alias=alias, prop=field.field_name, desc=desc)
        raw = escape_order_term(str(field), "order_by term")
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

    def return_target(self, alias: str | Alias) -> QueryBuilder[T]:
        """Set the single alias to return decoded Node instances from.

        When a traversal is involved, this selects which alias's nodes
        constitute the result of ``.all()``::

            q.return_target(f)  # returns f-nodes as list[FriendType]
        """
        self._return_aliases = [_alias_name(alias, "return target")]
        return self

    def return_nodes(self, *aliases: str | Alias) -> QueryBuilder[T]:
        """Declare multiple node aliases to include in the ``RETURN`` clause.

        Used with :meth:`return_edge` and :meth:`all_with_edges` to return
        structured tuples::

            q.return_nodes(u, m).return_edge(r).all_with_edges()
        """
        self._return_aliases = [_alias_name(a, "return node") for a in aliases]
        return self

    def return_edge(self, alias: str | Alias) -> QueryBuilder[T]:
        """Declare an edge alias to include in the ``RETURN`` clause.

        Requires that the traversal was created with ``edge=alias``.
        The edge is decoded via :meth:`~runic.ogm.mapper.mapper.Mapper.decode_edge`
        and included as the middle element of tuples returned by
        :meth:`all_with_edges`.
        """
        self._edge_alias_for_result = _alias_name(alias, "return edge")
        return self

    def project(self, *fields: Any) -> QueryBuilder[T]:
        """Shape the ``RETURN`` line: values, aggregates, or both.

        Bare fields are auto-named after themselves, so result rows are keyed
        by field name; ``.as_()`` renames, and computed expressions need it::

            select(Message).project(
                Message.id,
                left(Message.body_clean, param("max_chars")).as_("body"),
            )
            # RETURN n.id AS id, left(n.body_clean, $max_chars) AS body

        Cypher has no ``GROUP BY`` — every non-aggregated item *is* a grouping
        key — so a projection mixing values and aggregates is the grouped
        query::

            u, t = alias(User, "u"), alias(Tag, "t")
            select(u).traverse(User.tags, to=t).project(u, collect(t).as_("tags"))
            # RETURN u, collect(t) AS tags

        Terminal method ``.scalars()`` returns a single projected column as a
        flat list; ``.all_rows()`` returns a list of dicts keyed by column
        name.
        """
        for f in fields:
            if isinstance(f, str):
                _validate_projection(f)
        self._project_fields = list(fields)
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
            parts.append(f"WHERE {self.compile_and(root_exprs)}")
        parts.extend(clause.to_cypher(self) for clause in self._pipeline)
        if post_exprs:
            parts.append(f"WHERE {self.compile_and(post_exprs)}")

    def _wants_return(self) -> bool:
        """Whether this statement should emit a RETURN clause at all."""
        asked = bool(self._returning or self._project_fields or self._return_aliases)
        if asked:
            return True
        return not any(
            isinstance(clause, (SetClause, DeleteClause)) for clause in self._pipeline
        )

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
        self._validate_variables()
        # Reset params for each build call so multiple .all() calls are clean.
        self._param_counter = 0
        self.params = {}
        self._declared_params = set()

        parts: list[str] = []

        # ── Root MATCH ──────────────────────────────────────────────────
        root_meta = self._meta.get_node_meta(self._root_cls)
        if root_meta is None:
            raise ValueError(
                f"Class {self._root_cls.__name__!r} is not a registered Node subclass"
            )
        _lc = getattr(self.dialect, "labels_clause", None)
        labels_str = _lc(root_meta.labels) if _lc else ":".join(root_meta.labels)
        _sw = getattr(self.dialect, "subtype_where", None)
        subtype_filter = _sw(self.root_alias, root_meta.labels) if _sw else None
        parts.append(f"MATCH ({self.root_alias}:{labels_str})")
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
        return cypher, dict(self.params)

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
        return {**self.params, **supplied}

    # ------------------------------------------------------------------
    # Internal: traversal registration (called by TraversalStep.alias)
    # ------------------------------------------------------------------

    def _register_traversal(
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
        """Append a MATCH clause for one traversal step and register aliases."""
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
