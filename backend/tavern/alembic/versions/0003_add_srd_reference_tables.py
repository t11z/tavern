"""add SRD reference tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "srd_species",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("darkvision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full species record per species.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full class record per class.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full feature record per class_feature.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full subclass record per subclass.json schema",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_name", "name", name="uq_subclasses_class_name"),
    )
    op.create_index("ix_srd_subclasses_name", "srd_subclasses", ["name"])
    op.create_index("ix_srd_subclasses_class_name", "srd_subclasses", ["class_name"])

    op.create_table(
        "srd_backgrounds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full background record per background.json schema",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_backgrounds_name", "srd_backgrounds", ["name"])

    op.create_table(
        "srd_feats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full feat record per feat.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full weapon record per weapon.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full armor record per armor.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full equipment record per equipment.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full spell record per spell.json schema",
        ),
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
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full monster record per monster.json schema",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_srd_monsters_name", "srd_monsters", ["name"])
    op.create_index("ix_srd_monsters_type", "srd_monsters", ["type"])
    op.create_index("ix_srd_monsters_cr", "srd_monsters", ["cr"])

    op.create_table(
        "srd_monster_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("monster_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full action record per monster_action.json schema",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("monster_name", "name", name="uq_monster_actions_monster_name"),
    )
    op.create_index("ix_srd_monster_actions_monster_name", "srd_monster_actions", ["monster_name"])
    op.create_index("ix_srd_monster_actions_name", "srd_monster_actions", ["name"])

    op.create_table(
        "srd_conditions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full condition record per condition.json schema",
        ),
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
        sa.Column(
            "requires_attunement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full magic item record per magic_item.json schema",
        ),
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
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Table data; structure varies per table — see rules_table.json schema",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_name"),
    )
    op.create_index("ix_srd_rules_tables_table_name", "srd_rules_tables", ["table_name"])


def downgrade() -> None:
    op.drop_table("srd_rules_tables")
    op.drop_table("srd_magic_items")
    op.drop_table("srd_conditions")
    op.drop_table("srd_monster_actions")
    op.drop_table("srd_monsters")
    op.drop_table("srd_spells")
    op.drop_table("srd_equipment")
    op.drop_table("srd_armor")
    op.drop_table("srd_weapons")
    op.drop_table("srd_feats")
    op.drop_table("srd_backgrounds")
    op.drop_table("srd_subclasses")
    op.drop_table("srd_class_features")
    op.drop_table("srd_classes")
    op.drop_table("srd_species")
