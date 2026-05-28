from __future__ import annotations

from typing import Any

from falkordb.migration_runner import MigrationRunner
from falkordb.validate import assert_constraint_exists


def bootstrap_graph(graph: Any) -> None:
    """Run pending migrations and assert critical schema state."""
    runner = MigrationRunner(graph)
    runner.run()
    assert_constraint_exists(graph, "Trip", "id")
