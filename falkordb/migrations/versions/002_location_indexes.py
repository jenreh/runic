from __future__ import annotations

from falkordb.migrations.base import GraphProtocol, Migration
from falkordb.schema.labels import LOCATION


class LocationIndexes(Migration):
    version = "002_location_indexes"
    description = "Add location property indexes for country and category"

    def up(self, graph: GraphProtocol) -> None:
        graph.create_node_range_index(LOCATION, "country")
        graph.create_node_range_index(LOCATION, "category")
