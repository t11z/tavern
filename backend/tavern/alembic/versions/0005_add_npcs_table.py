"""add npcs table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "npcs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("species", sa.String(), nullable=True),
        sa.Column("appearance", sa.Text(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'alive'")),
        sa.Column(
            "plot_significant", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("motivation", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column("hp_current", sa.Integer(), nullable=True),
        sa.Column("hp_max", sa.Integer(), nullable=True),
        sa.Column("ac", sa.Integer(), nullable=True),
        sa.Column("creature_type", sa.String(), nullable=True),
        sa.Column("stat_block_ref", sa.String(), nullable=True),
        sa.Column("first_appeared_turn", sa.Integer(), nullable=True),
        sa.Column("last_seen_turn", sa.Integer(), nullable=True),
        sa.Column("scene_location", sa.String(), nullable=True),
        sa.CheckConstraint(
            "origin IN ('predefined', 'narrator_spawned')",
            name="ck_npcs_origin",
        ),
        sa.CheckConstraint(
            "status IN ('alive', 'dead', 'fled', 'unknown')",
            name="ck_npcs_status",
        ),
        sa.CheckConstraint(
            "disposition IN ('friendly', 'neutral', 'hostile', 'unknown')",
            name="ck_npcs_disposition",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_npcs_campaign_id", "npcs", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_npcs_campaign_id", table_name="npcs")
    op.drop_table("npcs")
