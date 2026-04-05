"""add mechanical_results JSONB to turns

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("mechanical_results", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("turns", "mechanical_results")
