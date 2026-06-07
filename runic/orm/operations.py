from __future__ import annotations

import logging
from typing import Any, Protocol

from runic.orm.driver import GraphResult

log = logging.getLogger(__name__)


class _Executor(Protocol):
    def execute(self, cypher: str, params: dict[str, Any]) -> GraphResult: ...


class DataOperations:
    """Generic graph data-manipulation operations backed by any query executor.

    Suitable for use outside migration scripts — any code that holds a
    :class:`~runic.orm.driver.GraphDriver` can construct this directly.

    Preview mode logs each operation without touching the database.
    """

    def __init__(self, executor: _Executor, *, preview: bool = False) -> None:
        self._executor = executor
        self._preview = preview
        self.preview_log: list[str] = []

    def _log_preview(self, description: str) -> None:
        self.preview_log.append(description)
        log.info("[preview] %s", description)

    def run_cypher(self, query: str, params: dict | None = None) -> Any:
        if self._preview:
            self._log_preview(f"CYPHER: {query} params={params}")
            return None
        return self._executor.execute(query, params or {})

    def rename_property(
        self, label: str, old: str, new: str, batch: int = 10_000
    ) -> None:
        if self._preview:
            self._log_preview(f"RENAME PROPERTY: {label}.{old} → {new} batch={batch}")
            return
        query = (
            f"MATCH (n:{label}) WHERE n.`{old}` IS NOT NULL AND n.`{new}` IS NULL "
            f"WITH n LIMIT $batch "
            f"SET n.`{new}` = n.`{old}` REMOVE n.`{old}` "
            f"RETURN count(n) AS affected"
        )
        log.info("renaming property %s.%s to %s", label, old, new)
        while True:
            result = self._executor.execute(query, {"batch": batch})
            affected = result.rows[0][0] if result.rows else 0
            if affected == 0:
                break

    def relabel_nodes(self, old: str, new: str, batch: int = 10_000) -> None:
        if not getattr(self._executor, "supports_multi_label", True):
            raise NotImplementedError(
                f"relabel_nodes() requires multi-label Cypher support "
                f"(SET n:{new} REMOVE n:{old}). "
                f"The current backend does not support assigning multiple labels "
                f"to a single vertex (e.g. Apache AGE, ArcadeDB)."
            )
        if self._preview:
            self._log_preview(f"RELABEL NODES: {old} → {new} batch={batch}")
            return
        query = (
            f"MATCH (n:{old}) WHERE NOT n:{new} "
            f"WITH n LIMIT $batch "
            f"SET n:{new} REMOVE n:{old} "
            f"RETURN count(n) AS affected"
        )
        log.info("relabelling nodes %s to %s", old, new)
        while True:
            result = self._executor.execute(query, {"batch": batch})
            affected = result.rows[0][0] if result.rows else 0
            if affected == 0:
                break

    def seed(self, merge_query: str, rows: list[dict]) -> None:
        if self._preview:
            self._log_preview(f"SEED: {len(rows)} rows via {merge_query}")
            return
        query = f"UNWIND $rows AS row {merge_query}"
        log.info("seeding %d rows", len(rows))
        self._executor.execute(query, {"rows": rows})
