"""test graph step 2

Revision ID: b97ff97c0e80
Revises: 172990dfd7c2
Create Date: 2026-05-31 08:18:08.107168+00:00
"""

from datetime import datetime
from typing import Any

message = "test graph step 2"
create_date = datetime.fromisoformat("2026-05-31T08:18:08.107168+00:00")

revision = "b97ff97c0e80"
down_revision = "172990dfd7c2"
branch_labels: list[str] = []
depends_on: list[str] = []
irreversible = False
snapshot = False


def upgrade(op: Any) -> None:
    # Index for the new Country node
    op.create_range_index("Country", "name")

    # Create one Country node per distinct country, carrying continent over
    op.run_cypher(
        "MATCH (d:Destination) "
        "MERGE (c:Country {name: d.country}) "
        "SET c.continent = d.continent"
    )

    # Link each Destination to its Country, then strip the redundant props
    op.run_cypher(
        "MATCH (d:Destination) "
        "MATCH (c:Country {name: d.country}) "
        "MERGE (d)-[:IN_COUNTRY]->(c) "
        "REMOVE d.country, d.continent"
    )


def downgrade(op: Any) -> None:
    # Restore country and continent onto Destination, drop the relationship
    op.run_cypher(
        "MATCH (d:Destination)-[:IN_COUNTRY]->(c:Country) "
        "SET d.country = c.name, d.continent = c.continent"
    )
    op.run_cypher("MATCH ()-[r:IN_COUNTRY]->() DELETE r")
    op.run_cypher("MATCH (c:Country) DETACH DELETE c")

    op.drop_range_index("Country", "name")
