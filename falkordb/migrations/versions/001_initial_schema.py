from __future__ import annotations

from typing import Any

from falkordb.migrations.base import Migration


class InitialSchema(Migration):
    version = "001_initial_schema"
    description = "Create initial Voyager graph schema"

    def up(self, graph: Any) -> None:
        graph.create_node_range_index("User", "auth_user_id")
        graph.create_node_unique_constraint("User", "auth_user_id")

        graph.create_node_range_index("Trip", "id")
        graph.create_node_unique_constraint("Trip", "id")

        graph.create_node_range_index("Location", "geo")
        graph.create_node_fulltext_index("Location", "title", "description")
        graph.create_node_unique_constraint("Location", "id")
