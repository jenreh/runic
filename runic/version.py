from __future__ import annotations

import logging
from typing import Any

from runic.exceptions import MultipleHeadsError

log = logging.getLogger(__name__)

# Returns both the new list property and the legacy string property so that old
# Phase-0 nodes (which only have v.revision) are transparently migrated on read.
_GET_QUERY = "MATCH (v:_FalkorMigrateVersion) RETURN v.revisions, v.revision"
_SET_LIST_QUERY = (
    "MERGE (v:_FalkorMigrateVersion {singleton: true})"
    " SET v.revisions = $revisions, v.applied_at = timestamp()"
)


class VersionNode:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def get(self) -> list[str]:
        try:
            result = self._graph.ro_query(_GET_QUERY)
        except Exception as exc:
            # Embedded FalkorDB raises on an empty key; treat as "no version yet"
            if "empty key" in str(exc).lower():
                return []
            raise
        rows = result.result_set
        if not rows:
            return []
        row = rows[0]
        col0 = row[0]
        # Guard for single-column mocks (Phase-0 test fixtures pass [["rev"]]).
        col1 = row[1] if len(row) > 1 else None

        if isinstance(col0, list):
            return [r for r in col0 if r is not None]
        # Old mock or single-col result: col0 is already the string revision.
        if isinstance(col0, str):
            return [col0]
        # Real Phase-0 node: v.revisions is null, v.revision holds the string.
        if isinstance(col1, str):
            return [col1]
        return []

    def get_single(self) -> str | None:
        revisions = self.get()
        if not revisions:
            return None
        if len(revisions) > 1:
            raise MultipleHeadsError(
                f"multiple revision heads: {revisions!r} — use get() to retrieve all"
            )
        return revisions[0]

    def set(self, revision: str) -> None:
        log.info("stamping version: %s", revision)
        self.set_multiple([revision])

    def set_multiple(self, revisions: list[str]) -> None:
        log.info("stamping versions: %s", revisions)
        self._graph.query(_SET_LIST_QUERY, {"revisions": revisions})

    def clear(self) -> None:
        log.info("clearing version node")
        self.set_multiple([])
