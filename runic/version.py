import logging
from typing import Any

log = logging.getLogger(__name__)

_GET_QUERY = "MATCH (v:_FalkorMigrateVersion) RETURN v.revision"
_SET_QUERY = (
    "MERGE (v:_FalkorMigrateVersion {singleton: true})"
    " SET v.revision = $rev, v.applied_at = timestamp()"
)


class VersionNode:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def get(self) -> str | None:
        result = self._graph.ro_query(_GET_QUERY)
        rows = result.result_set
        if not rows:
            return None
        return rows[0][0]

    def set(self, revision: str | None) -> None:
        log.info("stamping version: %s", revision)
        self._graph.query(_SET_QUERY, {"rev": revision})

    def clear(self) -> None:
        log.info("clearing version node")
        self.set(None)
