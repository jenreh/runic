"""ConnectionManager: thin wrapper for sync and async FalkorDB graph handles."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a FalkorDB connection for use with Session.

    Holds the db client and graph name; ``acquire()`` returns a graph handle.
    Full connection pooling can be added in a later phase without changing the API.
    """

    def __init__(self, db: Any, graph_name: str) -> None:
        self._db = db
        self._graph_name = graph_name

    def acquire(self) -> Any:
        """Return a graph handle for the configured graph name."""
        graph = self._db.select_graph(self._graph_name)
        log.debug("Acquired graph handle: %s", self._graph_name)
        return graph

    def release(self, graph: Any) -> None:  # noqa: ARG002
        """Release a graph handle back to the pool (no-op in current impl)."""

    @property
    def graph_name(self) -> str:
        """The configured graph name."""
        return self._graph_name


class AsyncConnectionManager:
    """Async variant of :class:`ConnectionManager` for AsyncFalkorDB clients."""

    def __init__(self, db: Any, graph_name: str) -> None:
        self._db = db
        self._graph_name = graph_name

    def acquire(self) -> Any:
        """Return an async graph handle for the configured graph name."""
        graph = self._db.select_graph(self._graph_name)
        log.debug("Acquired async graph handle: %s", self._graph_name)
        return graph

    async def release(self, graph: Any) -> None:  # noqa: ARG002
        """Release an async graph handle (no-op in current impl)."""

    @property
    def graph_name(self) -> str:
        """The configured graph name."""
        return self._graph_name
