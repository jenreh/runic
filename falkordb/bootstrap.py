from __future__ import annotations

from typing import Any

from falkordb.client import GraphFactory, connect_to_graph
from falkordb.config import FalkorDBSettings
from falkordb.migration_runner import MigrationRunner
from falkordb.validate import validate_required_constraints


def bootstrap_graph(
    graph: Any,
    poll_interval: float = 0.5,
    max_wait: float = 30.0,
) -> None:
    """Run pending migrations and assert critical schema state."""
    runner = MigrationRunner(graph, poll_interval=poll_interval, max_wait=max_wait)
    runner.run()
    validate_required_constraints(graph)


def main(
    settings: FalkorDBSettings | None = None,
    graph_factory: GraphFactory | None = None,
) -> None:
    active_settings = settings or FalkorDBSettings.from_env()
    graph = connect_to_graph(active_settings, graph_factory)
    bootstrap_graph(
        graph,
        poll_interval=active_settings.index_poll_interval,
        max_wait=active_settings.index_timeout,
    )


if __name__ == "__main__":
    main()
