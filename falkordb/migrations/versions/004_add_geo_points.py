from __future__ import annotations

from falkordb.migrations.base import GraphProtocol, Migration
from falkordb.schema.labels import LOCATION


class AddGeoPoints(Migration):
    version = "004_add_geo_points"
    description = "Add geo point indexes for proximity queries"

    def up(self, graph: GraphProtocol) -> None:
        graph.create_node_range_index(LOCATION, "latitude")
        graph.create_node_range_index(LOCATION, "longitude")
