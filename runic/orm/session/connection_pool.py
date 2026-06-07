"""ConnectionManager: thin wrapper for sync and async FalkorDB connections."""

from __future__ import annotations

import logging
from typing import Any

from runic.orm.driver.falkordb import AsyncFalkorDBDriver, FalkorDBDriver

log = logging.getLogger(__name__)


class ConnectionManager:
    """Manages a FalkorDB connection for use with Session.

    Holds the db client and graph name; ``acquire()`` returns a ``FalkorDBDriver``.
    """

    def __init__(self, db: Any, graph_name: str) -> None:
        self._db = db
        self._graph_name = graph_name

    def acquire(self) -> FalkorDBDriver:
        """Return a :class:`~runic.orm.driver.falkordb.FalkorDBDriver` for the configured graph."""
        graph = self._db.select_graph(self._graph_name)
        log.debug("Acquired graph handle: %s", self._graph_name)
        return FalkorDBDriver(graph)

    def release(self, driver: FalkorDBDriver) -> None:  # noqa: ARG002
        """Release a driver back to the pool (no-op in current impl)."""

    @property
    def graph_name(self) -> str:
        """The configured graph name."""
        return self._graph_name


class AsyncConnectionManager:
    """Async variant of :class:`ConnectionManager` for AsyncFalkorDB clients."""

    def __init__(self, db: Any, graph_name: str) -> None:
        self._db = db
        self._graph_name = graph_name

    def acquire(self) -> AsyncFalkorDBDriver:
        """Return an :class:`~runic.orm.driver.falkordb.AsyncFalkorDBDriver` for the configured graph."""
        graph = self._db.select_graph(self._graph_name)
        log.debug("Acquired async graph handle: %s", self._graph_name)
        return AsyncFalkorDBDriver(graph)

    async def release(self, driver: AsyncFalkorDBDriver) -> None:  # noqa: ARG002
        """Release an async driver (no-op in current impl)."""

    @property
    def graph_name(self) -> str:
        """The configured graph name."""
        return self._graph_name
