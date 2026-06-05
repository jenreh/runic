"""link traveler nationality to country

Revision ID: b04e8693b2c0
Revises: b97ff97c0e80
Create Date: 2026-05-31 08:22:38.969953+00:00
"""

from datetime import datetime
from typing import Any

message = "link traveler nationality to country"
create_date = datetime.fromisoformat("2026-05-31T08:22:38.969953+00:00")

revision = "b04e8693b2c0"
down_revision = "b97ff97c0e80"
branch_labels: list[str] = []
depends_on: list[str] = []
irreversible = False
snapshot = False

# nationality adjective → (country name, continent) — continent only needed for
# countries not already present as Destination country nodes.
_NATIONALITY_MAP = [
    ("Chinese", "China", "Asia"),
    ("Italian", "Italy", None),
    ("Spanish", "Spain", None),
    ("British", "United Kingdom", "Europe"),
    ("Japanese", "Japan", None),
]


def upgrade(op: Any) -> None:
    for demonym, country_name, continent in _NATIONALITY_MAP:
        # Ensure the Country node exists; set continent only for new ones.
        if continent:
            op.run_cypher(
                "MERGE (c:Country {name: $name}) "
                "ON CREATE SET c.continent = $continent",
                {"name": country_name, "continent": continent},
            )
        # Store the demonym on the Country so downgrade can reconstruct nationality.
        op.run_cypher(
            "MATCH (c:Country {name: $name}) SET c.demonym = $demonym",
            {"name": country_name, "demonym": demonym},
        )
        # Link each Traveler whose nationality matches to the Country node.
        op.run_cypher(
            "MATCH (t:Traveler {nationality: $demonym}), (c:Country {name: $name}) "
            "MERGE (t)-[:FROM]->(c)",
            {"demonym": demonym, "name": country_name},
        )

    # Remove the now-redundant nationality property from all Traveler nodes.
    op.run_cypher("MATCH (t:Traveler) REMOVE t.nationality")


def downgrade(op: Any) -> None:
    # Restore nationality from the Country's demonym, then drop the relationship.
    op.run_cypher(
        "MATCH (t:Traveler)-[:FROM]->(c:Country) SET t.nationality = c.demonym"
    )
    op.run_cypher("MATCH ()-[r:FROM]->() DELETE r")

    # Remove the demonym property we added to Country nodes.
    op.run_cypher("MATCH (c:Country) REMOVE c.demonym")

    # Delete Country nodes that were created solely for this migration.
    op.run_cypher("MATCH (c:Country) WHERE NOT (c)<-[:IN_COUNTRY]-() DELETE c")
