"""Bulk writes: one statement carrying many rows.

A rebuild writes its output in the tens of thousands.  Doing that one entity at
a time is one round trip per node, and the identity map has to hold every one of
them; ``UNWIND $rows AS row`` sends the lot in a single statement and expands it
in the store.

.. code-block:: python

    from runic.ogm import count, encode_rows, param, row, unwind

    MERGE_GROUPS = (
        unwind(param("rows"))
        .merge(Group, key=Group.id)
        .set(Group.size, Group.message_count, Group.first_seen)
    )

    session.all_rows(MERGE_GROUPS, {"rows": encode_rows(Group, payload)})

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
        .merge_edge("m", About, "t", alias="r")
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
from collections.abc import Mapping
from typing import Any, TypeVar

from runic.cypher import escape_identifier, validate_identifier
from runic.ogm.driver import CypherFeature
from runic.ogm.query.builder import QueryBuilder
from runic.ogm.query.clauses import MatchClause, MergeClause, UnwindClause

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
        key: Any,
        alias: str | None = None,
    ) -> MutationBuilder:
        """Bind an existing node by its key properties.

        *key* is a mapping of field → value, or — when the row key carries the
        field's own name — just the bare descriptor(s)::

            .match(Message, key=Message.id)                       # {id: row.id}
            .match(Message, key={Message.id: row("message_id")})  # renamed key

        Not ``merge``: a row naming a node that is not there is a bug in the
        caller's ordering, and creating one would replace that bug with an empty
        node no import can ever reconcile.
        """
        name = self._register(cls, alias)
        self._pipeline.append(
            MatchClause(
                self._node_pattern(cls, name, self._key_mapping(key)),
                optional=False,
            )
        )
        return self

    def merge(
        self,
        cls: type,
        *,
        key: Any,
        alias: str | None = None,
    ) -> MutationBuilder:
        """Upsert a node, matched or created on its *key* properties.

        *key* takes the same forms as :meth:`match` — a mapping, or bare
        descriptor(s) reading the same-named row key::

            .merge(Group, key=Group.id)   # MERGE (n:Group {id: row.id})

        Only the key goes in the pattern; everything else belongs in a following
        :meth:`~runic.ogm.query.builder.QueryBuilder.set`, or a changed property
        value would make ``MERGE`` miss the existing node and create a second.
        """
        name = self._register(cls, alias)
        self._pipeline.append(
            MergeClause(self._node_pattern(cls, name, self._key_mapping(key)))
        )
        return self

    def _key_mapping(self, key: Any) -> Mapping[Any, Any]:
        """Normalise a ``key=`` argument to a field → value mapping.

        A bare descriptor (or sequence of them) reads the same-named key of
        the ``UNWIND`` row variable.
        """
        from runic.ogm.core.descriptors import FieldDescriptor
        from runic.ogm.query.values import RowRef

        if isinstance(key, Mapping):
            return key
        entries = key if isinstance(key, (list, tuple)) else (key,)
        mapping: dict[Any, Any] = {}
        for entry in entries:
            if not isinstance(entry, FieldDescriptor):
                msg = (
                    "key= takes a mapping ({field: value}) or bare field "
                    f"descriptor(s); got {entry!r}"
                )
                raise TypeError(msg)
            mapping[entry] = RowRef(key=entry.field_name, var=self._row_var)
        return mapping

    def merge_edge(
        self,
        source: Any,
        relationship: Any,
        target: Any,
        *,
        alias: str | None = None,
        edge_model: type | None = None,
        directed: bool = True,
    ) -> MutationBuilder:
        """Upsert an edge between two already-bound variables.

        Parameters
        ----------
        source / target:
            Cypher variables (names or handles) bound by an earlier
            :meth:`match` or :meth:`merge`.
        relationship:
            The relationship type — an Edge class (``About``), a ``Relation``
            field (``Message.about``), or a raw type string. A class or field
            carries the type *and* the edge model, so neither is repeated::

                .merge_edge("m", About, "t", alias="r")
                # MERGE (m)-[r:ABOUT]->(t)
        alias:
            Variable for the edge, needed to ``set()`` properties on it.
        edge_model:
            Edge class, so ``set()`` can resolve its field converters. Derived
            automatically when *relationship* is a class or a Relation field.
        directed:
            ``False`` emits ``(a)-[r:T]-(b)`` with no arrow, so the same pair
            handed in either order finds the same edge instead of growing a
            second one.  Use it when the relationship is symmetric in meaning
            and the stored direction is an accident of which end was written
            first.  **FalkorDB rejects an undirected MERGE**; runic refuses to
            emit one there rather than sending Cypher it cannot parse.
        """
        from runic.ogm.query.builder import _alias_name

        source = _alias_name(source, "source variable")
        target = _alias_name(target, "target variable")
        rel_name, derived_model = self._edge_type(relationship)
        rel_type = validate_identifier(rel_name, "relationship type")
        if edge_model is None:
            edge_model = derived_model
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
        self._validate_variables()
        self._param_counter = 0
        self.params = {}
        self._declared_params = set()

        parts: list[str] = [self._unwind.to_cypher(self)]
        self._append_where_and_traversals(parts)

        # A write returns something only when asked; a bare MERGE returns
        # nothing, and inventing a RETURN would change what the statement does.
        if self._returning or self._project_fields:
            parts.append(self._compile_return())

        if self._order:
            parts.append(
                f"ORDER BY {', '.join(o.to_cypher(self) for o in self._order)}"
            )
        parts.extend(self._compile_paging())

        return "\n".join(parts), dict(self.params)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _edge_type(self, relationship: Any) -> tuple[str, type | None]:
        """Resolve a relationship argument to ``(type_name, edge_model)``.

        An Edge class knows its own type; a ``Relation`` field knows both the
        type and the edge model it declared; a string is taken verbatim.
        """
        from runic.ogm.core.descriptors import FieldDescriptor

        if isinstance(relationship, str):
            return relationship, None
        if isinstance(relationship, FieldDescriptor):
            rel = relationship.relationship
            if not rel:
                msg = f"{relationship.field_name!r} declares no relationship type"
                raise TypeError(msg)
            edge_cls = relationship.edge_model
            if isinstance(edge_cls, str):
                edge_cls = self._meta.resolve_target(edge_cls)
            return rel, edge_cls
        if isinstance(relationship, type):
            edge_meta = self._meta.get_edge_meta(relationship)
            if edge_meta is None:
                msg = f"{relationship.__name__!r} is not a registered Edge subclass"
                raise TypeError(msg)
            return edge_meta.edge_type, relationship
        msg = (
            "relationship must be an Edge class, a Relation field, or a type "
            f"string; got {relationship!r}"
        )
        raise TypeError(msg)

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
            self.root_alias = alias
        return alias

    def _node_pattern(self, cls: type, alias: str, key: Mapping[Any, Any]) -> str:
        """Render ``(alias:Label {k: row.k, …})`` for a key mapping."""
        meta = self._meta.get_node_meta(cls)
        if meta is None:
            msg = f"Class {cls.__name__!r} is not a registered Node subclass"
            raise ValueError(msg)
        _lc = getattr(self.dialect, "labels_clause", None)
        labels = _lc(meta.labels) if _lc else ":".join(meta.labels)

        entries = []
        for target, value in key.items():
            _, prop = self._resolve_write_target(target, alias)
            entries.append(
                f"{escape_identifier(prop)}: "
                f"{self._render_key_value(alias, prop, value)}"
            )
        return f"({alias}:{labels} {{{', '.join(entries)}}})"

    def _render_key_value(self, alias: str, prop: str, value: Any) -> str:
        """Render one key property's value, binding it unless it is an expression."""
        from runic.ogm.query.values import ValueExpr

        if isinstance(value, ValueExpr):
            rendered = value.to_cypher(self)
        else:
            rendered = f"${self.bind_param(self.convert_for(alias, prop, value))}"
        fn = self.cypher_fn_for(alias, prop)
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
            .merge(Topic, key=Topic.id)
            .set(Topic.label, Topic.score)
        )
    """
    return MutationBuilder(None, source, as_)
