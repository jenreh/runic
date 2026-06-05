"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision}
Create Date: ${create_date}
"""

from datetime import UTC, datetime
from typing import Any

message = ${repr(message)}
create_date = datetime.fromisoformat(${repr(create_date.isoformat())})

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels: list[str] = ${repr(branch_labels)}
depends_on: list[str] = ${repr(depends_on)}
irreversible = False  # set True to block `runic downgrade` unless --force is passed
snapshot = False      # set True to GRAPH.COPY before upgrade and auto-restore on failure


def upgrade(op: Any) -> None:
${upgrade_body}


def downgrade(op: Any) -> None:
${downgrade_body}
