from __future__ import annotations

import time
from typing import Any


class IndexWaitTimeoutError(RuntimeError):
    """Raised when FalkorDB indexes never reach OPERATIONAL state."""


def wait_for_indexes(
    graph: Any,
    poll_interval: float = 0.5,
    max_wait: float = 30.0,
) -> None:
    """Block until all indexes are operational."""
    deadline = time.monotonic() + max_wait
    while True:
        indexes = graph.list_indexes()
        if all(getattr(index, "status", "") == "OPERATIONAL" for index in indexes):
            return
        if time.monotonic() >= deadline:
            msg = "Timed out while waiting for FalkorDB indexes to become operational."
            raise IndexWaitTimeoutError(msg)
        time.sleep(poll_interval)
