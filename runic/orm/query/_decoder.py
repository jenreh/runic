"""Result decoding for the runic query builder.

:class:`_ResultDecoder` is the root of the :class:`~runic.orm.query.builder.QueryBuilder`
inheritance chain.  It owns the single responsibility of turning a driver
``GraphResult`` into ORM entities / tuples / dicts, registering decoded nodes in
the session identity map.  It is internal — construct queries via
:func:`~runic.orm.query.select` or :meth:`Session.query`.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from runic.orm.core.metadata import MetaData

T = TypeVar("T")


class _ResultDecoder(Generic[T]):  # noqa: UP046
    """Decode driver results into ORM entities.

    The query-spec attributes are populated by
    :meth:`QueryBuilder.__init__`; they are declared here so the decode methods
    type-check against the shared builder state.
    """

    _session: Any
    _root_cls: type[T]
    _meta: MetaData
    _alias_map: dict[str, type]
    _last_alias: str
    _return_aliases: list[str] | None
    _edge_alias_for_result: str | None

    # ------------------------------------------------------------------
    # Internal: result decoding
    # ------------------------------------------------------------------

    def _decode_node_result(self, result: Any) -> list[T]:
        """Decode a single-column node result into ORM entities."""
        decode_register = self._session.decode_and_register_node

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
            entities.append(decode_register(val, target_cls))
        return entities

    def _decode_edge_result(self, result: Any) -> list[tuple[Any, ...]]:
        """Decode multi-column result into (NodeA, EdgeModel, NodeB) tuples."""
        mapper = self._session.mapper
        decode_register = self._session.decode_and_register_node

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
                    decoded_row.append(decode_register(val, node_cls))
            tuples.append(tuple(decoded_row))
        return tuples

    def _decode_rows_as_dicts(self, result: Any) -> list[dict[str, Any]]:
        """Decode a multi-column result into column-keyed dicts."""
        mapper = self._session.mapper
        decode_register = self._session.decode_and_register_node
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
                        val = decode_register(val, cls)
                    elif edge_meta is not None:
                        val = mapper.decode_edge(val, cls)
                d[col_name] = val
            rows.append(d)
        return rows
