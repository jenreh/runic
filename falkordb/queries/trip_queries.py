from __future__ import annotations


def get_trip_by_id_query(trip_id: str) -> tuple[str, dict[str, str]]:
    query = """
    MATCH (t:Trip {id: $trip_id})
    RETURN t
    """
    return query, {"trip_id": trip_id}
