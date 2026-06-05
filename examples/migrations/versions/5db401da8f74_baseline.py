"""baseline

Revision ID: 5db401da8f74
Revises: None
Create Date: 2026-06-01 12:15:27.394935+00:00
"""

from datetime import datetime
from typing import Any

message = "baseline"
create_date = datetime.fromisoformat("2026-06-01T12:15:27.394935+00:00")

revision = "5db401da8f74"
down_revision = None
branch_labels: list[str] = []
depends_on: list[str] = []
irreversible = False  # set True to block `runic downgrade` unless --force is passed
snapshot = False  # set True to GRAPH.COPY before upgrade and auto-restore on failure


def upgrade(op: Any) -> None:
    pass


def downgrade(op: Any) -> None:
    pass
