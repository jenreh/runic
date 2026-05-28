from __future__ import annotations

from typing import Any

from falkordb.queries.location_queries import search_locations_query
from falkordb.queries.recommendation_queries import recommend_locations_query


class LocationGraphService:
    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def search(self, search_text: str) -> Any:
        query, params = search_locations_query(search_text)
        return self.graph.ro_query(query, params)

    def recommend_for_trip(self, trip_id: str, limit: int = 10) -> Any:
        query, params = recommend_locations_query(trip_id, limit)
        return self.graph.ro_query(query, params)
