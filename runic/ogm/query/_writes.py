"""Procedure calls and write clauses for the query builder.

Split from :mod:`~runic.ogm.query.builder` to keep each module readable; these
are :class:`~runic.ogm.query.builder.QueryBuilder` methods and are documented as
such.  The mixin declares the state it reads so the methods type-check against
the builder's shared attributes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from runic.cypher import validate_reference
from runic.ogm.core.descriptors import FieldDescriptor
from runic.ogm.driver import CypherFeature
from runic.ogm.query.clauses import CallClause, Clause, DeleteClause, SetClause

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)

T = TypeVar("T")


class _WriteMixin:
    """``call()``, ``set()``, ``delete()`` and ``returning()``.

    Mixed into :class:`~runic.ogm.query.builder.QueryBuilder`; the annotations
    below name the builder state these methods use.
    """

    _pipeline: list[Clause]
    _returning: list[Any]
    _root_alias: str
    _last_alias: str

    if TYPE_CHECKING:
        # Provided by the builder; declared here so these methods type-check.
        # Not defined at runtime — a stub would shadow the real implementation,
        # because the mixin comes first in the MRO.
        def _alias_for_cls(self, cls: type) -> str: ...
        def _flush_pending_paging(self) -> None: ...

    # ------------------------------------------------------------------
    # Procedures
    # ------------------------------------------------------------------

    def call(
        self,
        procedure: str,
        *args: Any,
        yields: Sequence[str] = (),
    ) -> Any:
        """Invoke a procedure mid-query, optionally correlated with the match.

        The arguments are ordinary expressions, so a procedure can be driven by
        a value from a node already matched — which is what turns a
        per-row search into one round trip instead of one query per row.

        Parameters
        ----------
        procedure:
            Dotted procedure name. Each segment is validated as an identifier.
        *args:
            Arguments. A plain ``str`` is emitted as a Cypher string literal
            (an index or label name the *model* supplies); everything else is an
            expression or a bound value.
        yields:
            Names to bind from the procedure's output.

        Example
        -------
        Every message's nearest neighbours in one statement, rather than a KNN
        query per message::

            m, node = alias(Message, "m"), alias(Message, "node")
            (
                select(m)
                .where(m.embedding_model == param("model"))
                .call(
                    "db.idx.vector.queryNodes",
                    "Message",
                    "embedding",
                    param("k"),
                    m.embedding,
                    yields=["node", "score"],
                )
                .with_(m, node, var("score"))
                .where(node.id > m.id)
            )

        .. note::
            A procedure cannot be narrowed before the fact: a ``MATCH`` above it
            does not restrict what it searches. Filters after the ``YIELD``
            discard rows the index already paid to find, so the search width has
            to cover them.
        """
        self._pipeline.append(
            CallClause(
                procedure=procedure,
                args=tuple(args),
                yields=tuple(yields),
                requires=(CypherFeature.PROCEDURE_CALL, f"CALL {procedure}"),
            )
        )
        return self

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set(
        self,
        *assignments: Any,
        on: Any = None,
    ) -> Any:
        """Assign properties on matched rows — a bulk ``SET``.

        Takes a mapping of property → value, bare field descriptors, or a mix.
        Mapping keys are field descriptors (or ``"alias.property"`` strings);
        values are Python values, :mod:`~runic.ogm.query.values` expressions,
        or ``None`` to clear the property.

        In an ``UNWIND $rows`` statement a **bare descriptor** assigns from the
        same-named row key — ``set(Group.size)`` means
        ``SET n.size = row.size`` — so a bulk upsert never echoes a name::

            unwind(param("rows"))
            .merge(Group, key=Group.id)
            .set(Group.size, Group.message_count, Group.first_seen)

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
        *assignments:
            Property → value mappings and/or bare field descriptors.
        on:
            Cypher variable (or handle) to assign on, when the property's own
            class is not the one being written (or appears under several
            aliases).
        """
        from runic.ogm.query.builder import _alias_name

        on_name = _alias_name(on, "set on") if on is not None else None
        self._flush_pending_paging()
        triples: list[tuple[str, str, Any]] = []
        for entry in assignments:
            for target, value in self._set_entries(entry):
                alias, prop = self._resolve_write_target(target, on_name)
                triples.append((alias, prop, value))
        self._pipeline.append(SetClause(assignments=tuple(triples)))
        return self

    def _set_entries(self, entry: Any) -> list[tuple[Any, Any]]:
        """Expand one ``set()`` argument into ``(target, value)`` pairs.

        A bare descriptor defaults its value to the same-named key of the
        ``UNWIND`` row variable — only meaningful on a statement that has one.
        """
        if isinstance(entry, Mapping):
            return list(entry.items())
        if isinstance(entry, FieldDescriptor):
            row_var = getattr(self, "_row_var", None)
            if row_var is None:
                msg = (
                    f"set({entry.field_name!r}) without a value only works in "
                    f"an UNWIND statement, where it reads the same-named row "
                    f"key; pass a mapping ({{field: value}}) here"
                )
                raise TypeError(msg)
            from runic.ogm.query.values import RowRef

            return [(entry, RowRef(key=entry.field_name, var=row_var))]
        msg = f"set() takes mappings or field descriptors; got {entry!r}"
        raise TypeError(msg)

    def delete(self, *variables: Any, detach: bool = False) -> Any:
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
                select(Group).limit(param("batch")).delete(detach=True)

                # A batch of derived edges, keeping both endpoints
                r = alias(CoAddressed, "r")
                (
                    select(alias(Address, "a"))
                    .traverse(Address.co_addressed, to="b", edge=r)
                    .with_(r, limit=param("batch"))
                    .delete(r)
                )

        Batching through a ``WITH`` stage keeps one delete from becoming a
        single long stall on a store something else is also reading; loop until
        the returned count is zero.
        """
        from runic.ogm.query.builder import _alias_name

        self._flush_pending_paging()
        targets = tuple(_alias_name(v, "delete target") for v in variables) or (
            self._last_alias,
        )
        self._pipeline.append(DeleteClause(variables=targets, detach=detach))
        return self

    def returning(self, *values: Any) -> Any:
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
