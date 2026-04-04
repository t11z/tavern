"""drop SRD reference tables

SRD data is now served from the 5e-bits/5e-database MongoDB container
via core/srd_data.py.  The PostgreSQL SRD tables added in migration 0003
are no longer written or read by the application.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables introduced in migration 0003, in dependency order (children first).
_SRD_TABLES = [
    "srd_monster_actions",
    "srd_monsters",
    "srd_spells",
    "srd_equipment",
    "srd_armor",
    "srd_weapons",
    "srd_feats",
    "srd_backgrounds",
    "srd_subclasses",
    "srd_class_features",
    "srd_classes",
    "srd_conditions",
    "srd_magic_items",
    "srd_rules_tables",
    "srd_species",
]


def upgrade() -> None:
    for table in _SRD_TABLES:
        op.drop_table(table)


def downgrade() -> None:
    """Re-create the SRD reference tables (empty — data must be re-imported)."""

    op.create_table(
        "srd_species",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("darkvision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_species_name", "srd_species", ["name"])

    op.create_table(
        "srd_classes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hit_die", sa.Integer(), nullable=False),
        sa.Column("subclass_level", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_classes_name", "srd_classes", ["name"])

    op.create_table(
        "srd_class_features",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_name", "name", name="uq_class_features_class_name"),
    )
    op.create_index("ix_srd_class_features_name", "srd_class_features", ["name"])
    op.create_index("ix_srd_class_features_class_name", "srd_class_features", ["class_name"])

    op.create_table(
        "srd_subclasses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_name", "name", name="uq_subclasses_class_name"),
    )
    op.create_index("ix_srd_subclasses_name", "srd_subclasses", ["name"])
    op.create_index("ix_srd_subclasses_class_name", "srd_subclasses", ["class_name"])

    op.create_table(
        "srd_backgrounds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_backgrounds_name", "srd_backgrounds", ["name"])

    op.create_table(
        "srd_feats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_feats_name", "srd_feats", ["name"])
    op.create_index("ix_srd_feats_category", "srd_feats", ["category"])

    op.create_table(
        "srd_weapons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("damage_dice", sa.String(), nullable=False),
        sa.Column("damage_type", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_weapons_name", "srd_weapons", ["name"])
    op.create_index("ix_srd_weapons_category", "srd_weapons", ["category"])

    op.create_table(
        "srd_armor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("base_ac", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_armor_name", "srd_armor", ["name"])
    op.create_index("ix_srd_armor_type", "srd_armor", ["type"])

    op.create_table(
        "srd_equipment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_equipment_name", "srd_equipment", ["name"])
    op.create_index("ix_srd_equipment_category", "srd_equipment", ["category"])

    op.create_table(
        "srd_spells",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("school", sa.String(), nullable=False),
        sa.Column(
            "requires_concentration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("ritual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_spells_name", "srd_spells", ["name"])
    op.create_index("ix_srd_spells_level", "srd_spells", ["level"])
    op.create_index("ix_srd_spells_school", "srd_spells", ["school"])

    op.create_table(
        "srd_monsters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("cr", sa.Float(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_monsters_name", "srd_monsters", ["name"])
    op.create_index("ix_srd_monsters_type", "srd_monsters", ["type"])
    op.create_index("ix_srd_monsters_cr", "srd_monsters", ["cr"])

    op.create_table(
        "srd_monster_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("monster_name", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("monster_name", "name", name="uq_monster_actions_monster_name"),
    )
    op.create_index("ix_srd_monster_actions_monster_name", "srd_monster_actions", ["monster_name"])

    op.create_table(
        "srd_conditions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_conditions_name", "srd_conditions", ["name"])

    op.create_table(
        "srd_magic_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("rarity", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_magic_items_name", "srd_magic_items", ["name"])
    op.create_index("ix_srd_magic_items_type", "srd_magic_items", ["type"])
    op.create_index("ix_srd_magic_items_rarity", "srd_magic_items", ["rarity"])

    op.create_table(
        "srd_rules_tables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_name", sa.String(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_name"),
    )
    op.create_index("ix_srd_rules_tables_table_name", "srd_rules_tables", ["table_name"])
