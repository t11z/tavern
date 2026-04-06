"""add event_log JSONB to turns

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB  # migrations run on PostgreSQL only

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("event_log", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("turns", "event_log")
