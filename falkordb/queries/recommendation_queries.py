from __future__ import annotations


def recommend_locations_query(
    trip_id: str,
    limit: int = 10,
) -> tuple[str, dict[str, int | str]]:
    query = """
    MATCH (:Trip {id: $trip_id})-[:VISITS]->(location:Location)
    RETURN location
    LIMIT $limit
    """
    return query, {"trip_id": trip_id, "limit": limit}
