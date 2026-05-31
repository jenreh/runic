"""test graph

Revision ID: 172990dfd7c2
Revises: None
Create Date: 2026-05-31 07:54:26.288817+00:00
"""

from datetime import datetime
from typing import Any

message = "test graph"
create_date = datetime.fromisoformat("2026-05-31T07:54:26.288817+00:00")

revision = "172990dfd7c2"
down_revision = None
branch_labels: list[str] = []
depends_on: list[str] = []
irreversible = False  # set True to block `runic downgrade` unless --force is passed
snapshot = False  # set True to GRAPH.COPY before upgrade and auto-restore on failure

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_TRAVELERS = [
    {"name": "Alice Chen", "nationality": "Chinese", "passport": "CN-001"},
    {"name": "Marco Rossi", "nationality": "Italian", "passport": "IT-002"},
    {"name": "Sofia García", "nationality": "Spanish", "passport": "ES-003"},
    {"name": "James Wright", "nationality": "British", "passport": "GB-004"},
    {"name": "Yuki Tanaka", "nationality": "Japanese", "passport": "JP-005"},
]

_DESTINATIONS = [
    {"city": "Kyoto", "country": "Japan", "continent": "Asia"},
    {"city": "Barcelona", "country": "Spain", "continent": "Europe"},
    {"city": "Rome", "country": "Italy", "continent": "Europe"},
    {"city": "Cape Town", "country": "South Africa", "continent": "Africa"},
    {"city": "Queenstown", "country": "New Zealand", "continent": "Oceania"},
]

_TRIPS = [
    {
        "trip_id": "T-001",
        "departure": "2026-06-10",
        "duration_days": 7,
        "budget_usd": 2000,
    },
    {
        "trip_id": "T-002",
        "departure": "2026-07-15",
        "duration_days": 5,
        "budget_usd": 1500,
    },
    {
        "trip_id": "T-003",
        "departure": "2026-08-20",
        "duration_days": 4,
        "budget_usd": 1200,
    },
    {
        "trip_id": "T-004",
        "departure": "2026-09-05",
        "duration_days": 10,
        "budget_usd": 3500,
    },
    {
        "trip_id": "T-005",
        "departure": "2026-10-12",
        "duration_days": 6,
        "budget_usd": 2800,
    },
]

# (traveler.passport, trip.trip_id, destination.city)
_ITINERARIES = [
    ("CN-001", "T-001", "Kyoto"),
    ("IT-002", "T-002", "Barcelona"),
    ("ES-003", "T-003", "Rome"),
    ("GB-004", "T-004", "Cape Town"),
    ("JP-005", "T-005", "Queenstown"),
]


def upgrade(op: Any) -> None:
    # Indexes
    op.create_range_index("Traveler", "passport")
    op.create_range_index("Destination", "city")
    op.create_range_index("Trip", "trip_id")

    # Nodes
    op.seed(
        "MERGE (n:Traveler {passport: row.passport})"
        " SET n.name = row.name, n.nationality = row.nationality",
        _TRAVELERS,
    )
    op.seed(
        "MERGE (n:Destination {city: row.city})"
        " SET n.country = row.country, n.continent = row.continent",
        _DESTINATIONS,
    )
    op.seed(
        "MERGE (n:Trip {trip_id: row.trip_id})"
        " SET n.departure = row.departure,"
        "     n.duration_days = row.duration_days,"
        "     n.budget_usd = row.budget_usd",
        _TRIPS,
    )

    # Relations: Traveler -[:PLANNED]-> Trip -[:GOES_TO]-> Destination
    for passport, trip_id, city in _ITINERARIES:
        op.run_cypher(
            "MATCH (t:Traveler {passport: $p}), (tr:Trip {trip_id: $tid})"
            " MERGE (t)-[:PLANNED]->(tr)",
            {"p": passport, "tid": trip_id},
        )
        op.run_cypher(
            "MATCH (tr:Trip {trip_id: $tid}), (d:Destination {city: $city})"
            " MERGE (tr)-[:GOES_TO]->(d)",
            {"tid": trip_id, "city": city},
        )


def downgrade(op: Any) -> None:
    op.run_cypher("MATCH (n:Trip) DETACH DELETE n")
    op.run_cypher("MATCH (n:Traveler) DETACH DELETE n")
    op.run_cypher("MATCH (n:Destination) DETACH DELETE n")

    op.drop_range_index("Trip", "trip_id")
    op.drop_range_index("Destination", "city")
    op.drop_range_index("Traveler", "passport")
