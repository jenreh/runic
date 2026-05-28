from __future__ import annotations

import time
from typing import Any


def wait_for_indexes(graph: Any, poll_interval: float = 0.5) -> None:
    """Block until all indexes are operational."""
    while True:
        indexes = graph.list_indexes()
        if all(getattr(index, "status", "") == "OPERATIONAL" for index in indexes):
            return
        time.sleep(poll_interval)
