from __future__ import annotations

from falkordb.migrations.base import GraphProtocol, Migration
from falkordb.schema.labels import LOCATION, TRIP, USER


class InitialSchema(Migration):
    version = "001_initial_schema"
    description = "Create initial Voyager graph schema"

    def up(self, graph: GraphProtocol) -> None:
        graph.create_node_range_index(USER, "auth_user_id")
        graph.create_node_unique_constraint(USER, "auth_user_id")

        graph.create_node_range_index(TRIP, "id")
        graph.create_node_unique_constraint(TRIP, "id")

        graph.create_node_range_index(LOCATION, "geo")
        graph.create_node_fulltext_index(LOCATION, "title", "description")
        graph.create_node_unique_constraint(LOCATION, "id")
