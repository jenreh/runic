from __future__ import annotations

from falkordb.migrations.base import GraphProtocol, Migration
from falkordb.schema.labels import TRIP, USER


class TripAccessConstraints(Migration):
    version = "005_trip_access_constraints"
    description = "Add trip ownership and access control indexes"

    def up(self, graph: GraphProtocol) -> None:
        graph.create_node_range_index(USER, "id")
        graph.create_node_unique_constraint(USER, "id")
        graph.create_node_range_index(TRIP, "created_at")
