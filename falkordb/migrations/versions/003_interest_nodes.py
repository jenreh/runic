from __future__ import annotations

from falkordb.migrations.base import GraphProtocol, Migration
from falkordb.schema.labels import INTEREST


class InterestNodes(Migration):
    version = "003_interest_nodes"
    description = "Add Interest node indexes and constraints"

    def up(self, graph: GraphProtocol) -> None:
        graph.create_node_range_index(INTEREST, "id")
        graph.create_node_unique_constraint(INTEREST, "id")
        graph.create_node_fulltext_index(INTEREST, "name")
