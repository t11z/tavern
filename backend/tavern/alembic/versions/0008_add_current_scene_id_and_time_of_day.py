"""add current_scene_id and time_of_day to campaign_state

ADR-0019: Exploration State Signals — promotes party location from
world_state["location"] (JSONB key) to a dedicated TEXT column and adds
time_of_day as a dedicated column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_TIMES = (
    "dawn",
    "morning",
    "midday",
    "afternoon",
    "dusk",
    "evening",
    "night",
    "late_night",
)


def upgrade() -> None:
    # Add columns with defaults so the NOT NULL constraint is satisfied
    op.add_column(
        "campaign_states",
        sa.Column("current_scene_id", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "campaign_states",
        sa.Column("time_of_day", sa.String(), nullable=False, server_default="morning"),
    )

    # Populate current_scene_id from world_state->>'location', applying
    # normalise_scene_id() logic in SQL.  Steps mirror the Python implementation:
    #   1. TRIM + LOWER
    #   2. Replace runs of spaces/hyphens with underscore
    #   3. Strip non-conforming chars (keep a-z, 0-9, _)
    #   4. Collapse consecutive underscores
    #   5. Strip leading/trailing underscores (LEFT(TRIM))
    #   6. Truncate to 64 chars
    #   7. Fallback to 'unknown' if empty
    op.execute(
        """
        UPDATE campaign_states
        SET current_scene_id = COALESCE(
            NULLIF(
                LEFT(
                    TRIM('_' FROM
                        REGEXP_REPLACE(
                            REGEXP_REPLACE(
                                REGEXP_REPLACE(
                                    LOWER(TRIM(COALESCE(world_state->>'location', ''))),
                                    '[\\s\\-]+', '_', 'g'
                                ),
                                '[^a-z0-9_]', '', 'g'
                            ),
                            '_+', '_', 'g'
                        )
                    ),
                    64
                ),
                ''
            ),
            'unknown'
        )
        """
    )

    # Populate time_of_day from world_state->>'time_of_day', validating against
    # the enum.  Fall back to 'morning' for any unrecognised or absent value.
    valid_times_literal = ", ".join(f"'{v}'" for v in _VALID_TIMES)
    op.execute(
        f"""
        UPDATE campaign_states
        SET time_of_day = CASE
            WHEN world_state->>'time_of_day' IN ({valid_times_literal})
            THEN world_state->>'time_of_day'
            ELSE 'morning'
        END
        """
    )

    # Add CHECK constraint after data is populated
    op.create_check_constraint(
        "ck_campaign_states_time_of_day",
        "campaign_states",
        f"time_of_day IN ({valid_times_literal})",
    )

    # Remove server defaults now that existing rows are populated
    op.alter_column("campaign_states", "current_scene_id", server_default=None)
    op.alter_column("campaign_states", "time_of_day", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_campaign_states_time_of_day", "campaign_states", type_="check")
    op.drop_column("campaign_states", "time_of_day")
    op.drop_column("campaign_states", "current_scene_id")
