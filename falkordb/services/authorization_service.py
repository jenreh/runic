from __future__ import annotations

from typing import Any


class AuthorizationService:
    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def user_can_access_trip(self, auth_user_id: str, trip_id: str) -> bool:
        query = """
        MATCH (user:User {auth_user_id: $auth_user_id})-[:CAN_ACCESS]->
              (trip:Trip {id: $trip_id})
        RETURN COUNT(trip) > 0 AS allowed
        """
        result = self.graph.ro_query(
            query,
            {"auth_user_id": auth_user_id, "trip_id": trip_id},
        )
        return bool(result.result_set and result.result_set[0][0])
