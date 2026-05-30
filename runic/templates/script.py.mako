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
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
irreversible = False
snapshot = False


def upgrade(op: Any) -> None:
${upgrade_body}


def downgrade(op: Any) -> None:
${downgrade_body}
