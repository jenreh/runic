from __future__ import annotations

from collections.abc import Callable
from typing import Any

from falkordb.config import FalkorDBSettings

GraphFactory = Callable[[FalkorDBSettings], Any]


def connect_to_graph(
    settings: FalkorDBSettings | None = None,
    graph_factory: GraphFactory | None = None,
) -> Any:
    active_settings = settings or FalkorDBSettings.from_env()
    if graph_factory is None:
        msg = (
            "A graph_factory is required to create a FalkorDB graph in this "
            "repository."
        )
        raise RuntimeError(msg)
    return graph_factory(active_settings)
