"""Bulk writes: one statement carrying many rows.

A rebuild writes its output in the tens of thousands.  Doing that one entity at
a time is one round trip per node, and the identity map has to hold every one of
them; ``UNWIND $rows AS row`` sends the lot in a single statement and expands it
in the store.

.. code-block:: python

    from runic.ogm import col, count, encode_rows, param, row, unwind

    MERGE_GROUPS = (
        unwind(param("rows"))
        .merge(Group, key={Group.id: row("id")})
        .set(
            {
                Group.size: row("size"),
                Group.message_count: row("message_count"),
                Group.first_seen: row("first_seen"),
            }
        )
    )

    session.execute_statement(MERGE_GROUPS, {"rows": encode_rows(Group, payload)})

``MERGE`` rather than ``CREATE`` because idempotence is usually the contract: a
derived label carries no unique constraint, so a second run of a ``CREATE`` job
silently produces a second copy of every node, and every edge written afterwards
is written twice.

Edges are attached by matching both endpoints and merging between them:

.. code-block:: python

    MERGE_ABOUT = (
        unwind(param("rows"))
        .match(Message, key={Message.id: row("message_id")}, alias="m")
        .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
        .merge_edge("m", "ABOUT", "t", alias="r")
        .set({About.score: row("score")}, on="r")
    )

``match`` and not ``merge`` on the endpoints: a row naming a node that is not
there is a bug in the caller's ordering, and merging it would paper over that
with an empty node carrying nothing but a key.

Rows and converters
-------------------
Values inside ``$rows`` never pass through the mapper, so a ``datetime`` there
reaches the driver as an object it has no encoding for.  Run the payload through
:func:`~runic.ogm.query.values.encode_rows` first — it applies the same field
converters the mapper would.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar

from runic.cypher import validate_identifier
from runic.ogm.driver import CypherFeature
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.clauses import MatchClause, MergeClause, UnwindClause

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["MutationBuilder", "unwind"]


class MutationBuilder(QueryBuilder[Any]):
    """A statement whose root is an ``UNWIND`` rather than a ``MATCH``.

    Built by :func:`unwind`.  Shares the query builder's clause pipeline,
    parameter binding and expression rendering; only the opening clause and the
    default ``RETURN`` differ — a write reports what it did, or returns nothing
    at all.
    """

    def __init__(self, session: Any, source: Any, variable: str = "row") -> None:
        # No root class: the first match()/merge() introduces one. A private
        # placeholder keeps the alias bookkeeping honest until then.
        super().__init__(session, _NoRoot)
        self._unwind = UnwindClause(source=source, variable=variable)
        self._row_var = variable
        self._alias_counter = 0

    # ------------------------------------------------------------------
    # Pattern clauses
    # ------------------------------------------------------------------

    def match(
        self,
        cls: type,
        *,
        key: Mapping[Any, Any],
        alias: str | None = None,
    ) -> MutationBuilder:
        """Bind an existing node by its key properties.

        Not ``merge``: a row naming a node that is not there is a bug in the
        caller's ordering, and creating one would replace that bug with an empty
        node no import can ever reconcile.
        """
        name = self._register(cls, alias)
        self._pipeline.append(
            MatchClause(self._node_pattern(cls, name, key), optional=False)
        )
        return self

    def merge(
        self,
        cls: type,
        *,
        key: Mapping[Any, Any],
        alias: str | None = None,
    ) -> MutationBuilder:
        """Upsert a node, matched or created on its *key* properties.

        Only the key goes in the pattern; everything else belongs in a following
        :meth:`~runic.ogm.query.builder.QueryBuilder.set`, or a changed property
        value would make ``MERGE`` miss the existing node and create a second.
        """
        name = self._register(cls, alias)
        self._pipeline.append(MergeClause(self._node_pattern(cls, name, key)))
        return self

    def merge_edge(
        self,
        source: str,
        relationship: str,
        target: str,
        *,
        alias: str | None = None,
        edge_model: type | None = None,
        directed: bool = True,
    ) -> MutationBuilder:
        """Upsert an edge between two already-bound variables.

        Parameters
        ----------
        source / target:
            Cypher variables bound by an earlier :meth:`match` or :meth:`merge`.
        relationship:
            The relationship type.
        alias:
            Variable for the edge, needed to ``set()`` properties on it.
        edge_model:
            Edge class, so ``set()`` can resolve its field converters.
        directed:
            ``False`` emits ``(a)-[r:T]-(b)`` with no arrow, so the same pair
            handed in either order finds the same edge instead of growing a
            second one.  Use it when the relationship is symmetric in meaning
            and the stored direction is an accident of which end was written
            first.  **FalkorDB rejects an undirected MERGE**; runic refuses to
            emit one there rather than sending Cypher it cannot parse.
        """
        validate_identifier(source, "source variable")
        validate_identifier(target, "target variable")
        rel_type = validate_identifier(relationship, "relationship type")
        edge_ref = (
            f"{validate_identifier(alias, 'edge alias')}:{rel_type}"
            if alias
            else f":{rel_type}"
        )

        arrow = "->" if directed else "-"
        pattern = f"({source})-[{edge_ref}]{arrow}({target})"

        requires = (
            None
            if directed
            else (CypherFeature.UNDIRECTED_MERGE, "an undirected MERGE ((a)-[r:T]-(b))")
        )
        self._pipeline.append(MergeClause(pattern, requires=requires))

        if alias is not None and edge_model is not None:
            self._set_alias(alias, edge_model)
        if alias is not None:
            self._last_alias = alias
        return self

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    def build(self) -> tuple[str, dict[str, Any]]:
        """Compile to Cypher, opening with the ``UNWIND`` instead of a MATCH."""
        self._param_counter = 0
        self._params = {}
        self._declared_params = set()

        parts: list[str] = [self._unwind.to_cypher(self)]
        self._append_where_and_traversals(parts)

        # A write returns something only when asked; a bare MERGE returns
        # nothing, and inventing a RETURN would change what the statement does.
        if self._returning or self._agg_exprs or self._project_fields:
            parts.append(self._compile_return())

        if self._order:
            parts.append(
                f"ORDER BY {', '.join(o.to_cypher(self) for o in self._order)}"
            )
        parts.extend(self._compile_paging())

        return "\n".join(parts), dict(self._params)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _register(self, cls: type, alias: str | None) -> str:
        """Name a variable for *cls*, generating one when not given."""
        if alias is None:
            self._alias_counter += 1
            alias = f"n{self._alias_counter}"
        validate_identifier(alias, "node alias")
        self._set_alias(alias, cls)
        self._last_alias = alias
        if self._root_cls is _NoRoot:
            self._root_cls = cls
            self._root_alias = alias
        return alias

    def _node_pattern(self, cls: type, alias: str, key: Mapping[Any, Any]) -> str:
        """Render ``(alias:Label {k: row.k, …})`` for a key mapping."""
        meta = self._meta.get_node_meta(cls)
        if meta is None:
            msg = f"Class {cls.__name__!r} is not a registered Node subclass"
            raise ValueError(msg)
        _lc = getattr(self._dialect, "labels_clause", None)
        labels = _lc(meta.labels) if _lc else ":".join(meta.labels)

        entries = []
        for target, value in key.items():
            _, prop = self._resolve_write_target(target, alias)
            entries.append(f"{prop}: {self._render_key_value(alias, prop, value)}")
        return f"({alias}:{labels} {{{', '.join(entries)}}})"

    def _render_key_value(self, alias: str, prop: str, value: Any) -> str:
        """Render one key property's value, binding it unless it is an expression."""
        from runic.ogm.query.values import ValueExpr

        if isinstance(value, ValueExpr):
            rendered = value.to_cypher(self)
        else:
            rendered = f"${self._next_param(self._convert_for(alias, prop, value))}"
        fn = self._cypher_fn_for(alias, prop)
        return f"{fn}({rendered})" if fn else rendered


class _NoRoot:
    """Placeholder root for a statement that opens with UNWIND, not MATCH."""


def unwind(source: Any, *, as_: str = "row") -> MutationBuilder:
    """Open a bulk statement over a list parameter.

    Parameters
    ----------
    source:
        Usually ``param("rows")`` — the list the caller binds.  A plain Python
        list is bound automatically.
    as_:
        Name of the loop variable, referenced by
        :func:`~runic.ogm.query.values.row`.

    Example
    -------
    .. code-block:: python

        from runic.ogm import param, row, unwind

        stmt = (
            unwind(param("rows"))
            .merge(Topic, key={Topic.id: row("id")})
            .set({Topic.label: row("label"), Topic.score: row("score")})
        )
    """
    return MutationBuilder(None, source, as_)
