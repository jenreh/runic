"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision}
Create Date: ${create_date}
"""
from runic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
irreversible = False
snapshot = False


def upgrade(op) -> None:
    pass


def downgrade(op) -> None:
    pass
