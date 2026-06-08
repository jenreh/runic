"""Shared state and row decoding for Repository / AsyncRepository.

Both repositories construct identically and decode already-fetched result rows
with the same (synchronous) logic; only the query *execution* differs by
``await``.  :class:`_RepositoryBase` holds that shared part so the concrete
repositories carry only their backend-specific read methods.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class _RepositoryBase[T]:
    """Shared constructor and row-decoding helpers for the repositories."""

    _session: Any
    _cls: type[T]

    def __init__(self, session: Any, entity_class: type[T]) -> None:
        self._session = session
        self._cls = entity_class

    def _decode_rows(self, result: Any) -> list[T]:
        """Decode plain MATCH rows (single node per row), registered in identity map."""
        return [
            self._session.decode_and_register_node(row[0], self._cls)
            for row in result.rows
        ]

    def _decode_rows_with_fetch(
        self,
        result: Any,
        fetch_meta: list[tuple[str, Any]],
    ) -> list[T]:
        """Decode rows that include eager-loaded relationship columns."""
        entities: list[T] = []
        for row in result.rows:
            registered = self._session.decode_and_register_node(row[0], self._cls)
            related = self._session.rel_loader.decode_eager_columns(
                row, registered, fetch_meta
            )
            for rel_entity in related:
                self._session.register_or_get(rel_entity)
            entities.append(registered)
        return entities
