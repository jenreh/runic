"""Traversal steps for the query builder.

A :class:`TraversalStep` is returned by :meth:`QueryBuilder.traverse` and
:meth:`QueryBuilder.repeat`.  It captures the intent for one hop (or a
variable-length path) along a declared :func:`~runic.ogm.core.descriptors.Relation`
field and provides a fluent ``.alias()`` method to register the traversal and
return to the builder chain.

Typical usage
-------------
.. code-block:: python

    results = (
        session.query(User)
        .alias("u")
        .where(User.id == user_id)
        .traverse(User.friends)  # → TraversalStep
        .alias("f")  # → back to QueryBuilder
        .where(User.age > 25, on="f")
        .all()
    )

    # With edge properties:
    rows = (
        session.query(User)
        .alias("u")
        .traverse(User.rated, edge_alias="r")  # → TraversalStep (edge captured)
        .alias("m")  # Movie is the target
        .where(Rated.score > 4.0, on="r")
        .return_nodes("u", "m")
        .return_edge("r")
        .all_with_edges()  # list[tuple[User, Rated, Movie]]
    )

    # Variable-length (e.g. org chart):
    ancestors = (
        session.query(Employee)
        .alias("e")
        .where(Employee.id == emp_id)
        .repeat(Employee.reports_to, min_hops=1, max_hops=5)
        .alias("anc")
        .all()
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.ogm.query.builder import QueryBuilder

log = logging.getLogger(__name__)


class TraversalStep:
    """Pending traversal hop; returned by :meth:`QueryBuilder.traverse` and
    :meth:`QueryBuilder.repeat`.

    Call :meth:`alias` to complete the step and resume the builder chain.

    Parameters
    ----------
    builder:
        The owning :class:`QueryBuilder` instance.
    field_descriptor:
        The :class:`~runic.ogm.core.descriptors.FieldDescriptor` for the
        ``Relation`` field being traversed.
    source_alias:
        The Cypher variable name of the source node.
    optional:
        When ``True`` (the default), the traversal emits ``OPTIONAL MATCH``
        (left-join: source nodes without the relationship are still returned).
        When ``False``, emits ``MATCH`` (inner-join: drops source nodes that
        have no such relationship).
    edge_alias:
        Optional Cypher variable name for the relationship itself.  When set,
        the generated pattern is ``(src)-[edge_alias:TYPE]->(tgt)`` instead
        of the anonymous ``(src)-[:TYPE]->(tgt)``, enabling edge property
        filtering and retrieval.
    min_hops:
        Minimum number of hops for variable-length paths (default ``1``).
        Values > 1 only take effect when combined with *max_hops* to produce
        a ``*min..max`` quantifier.
    max_hops:
        Maximum number of hops.  ``None`` means unbounded (``*min..``).
        A value of ``1`` with ``min_hops=1`` produces a fixed single-hop pattern.
    """

    def __init__(
        self,
        builder: QueryBuilder[Any],
        field_descriptor: Any,
        source_alias: str,
        *,
        optional: bool = True,
        edge_alias: str | None = None,
        min_hops: int = 1,
        max_hops: int | None = 1,
    ) -> None:
        self._builder = builder
        self._fd = field_descriptor
        self._source_alias = source_alias
        self._optional = optional
        self._edge_alias = edge_alias
        self._min_hops = min_hops
        self._max_hops = max_hops

    # ------------------------------------------------------------------
    # Fluent terminator
    # ------------------------------------------------------------------

    def alias(self, name: str) -> QueryBuilder[Any]:
        """Register the target node alias and append the traversal to the builder.

        Calling this method:

        1. Resolves the target Node class from the Relation field's ``target``.
        2. Appends the appropriate ``(OPTIONAL) MATCH`` clause to the builder.
        3. Registers ``name → target_cls`` in the builder's alias map.
        4. Registers ``edge_alias → Edge class`` if an edge alias was given.
        5. Sets the builder's *last alias* (used as the default ``RETURN``
           target when no explicit ``return_target()`` is called).

        Parameters
        ----------
        name:
            Cypher variable name for the target node (e.g. ``"f"``, ``"m"``).

        Returns
        -------
        QueryBuilder
            The owning builder, ready for continued chaining.
        """
        return self._builder.register_traversal(
            fd=self._fd,
            source_alias=self._source_alias,
            target_alias=name,
            optional=self._optional,
            edge_alias=self._edge_alias,
            min_hops=self._min_hops,
            max_hops=self._max_hops,
        )
