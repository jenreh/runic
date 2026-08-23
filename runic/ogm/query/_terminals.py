"""Terminal methods for the query builder — the calls that execute a statement.

Split from :mod:`~runic.ogm.query.builder` to keep each module readable; these
are :class:`~runic.ogm.query.builder.QueryBuilder` methods and are documented as
such.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

T = TypeVar("T")


class _TerminalMixin:
    """``all()``, ``one()``, ``count()`` and the rest.

    Each takes an optional mapping of caller bindings, merged over the
    auto-bound values by :meth:`~runic.ogm.query.builder.QueryBuilder.bind`.
    """

    if TYPE_CHECKING:
        # Provided by the builder and the compiler; declared so these methods
        # type-check. Not defined at runtime — a stub would shadow the real
        # implementation, because the mixin comes first in the MRO.
        _session: Any
        _agg_exprs: list[Any]
        _group_by_alias: Any
        _return_aliases: list[str] | None
        _project_fields: list[Any]
        _limit_val: Any

        def _check_bound(self) -> None: ...
        def build(self) -> tuple[str, dict[str, Any]]: ...
        def bind(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]: ...
        def limit(self, n: Any) -> Any: ...
        def _decode_node_result(self, result: Any) -> Any: ...
        def _decode_edge_result(self, result: Any) -> Any: ...
        def _decode_rows_as_dicts(self, result: Any) -> Any: ...

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
