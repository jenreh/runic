from __future__ import annotations

from typing import Any

from falkordb.queries.trip_queries import get_trip_by_id_query


class TripGraphService:
    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def get_trip(self, trip_id: str) -> Any:
        query, params = get_trip_by_id_query(trip_id)
        return self.graph.ro_query(query, params)
