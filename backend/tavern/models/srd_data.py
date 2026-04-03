"""SRD reference data models — read-heavy, write-once tables seeded by scripts/srd_import/.

All tables carry the full extracted record in a ``data`` JSONB column so that
the engine can read any field without schema migrations for every new field.
The indexed columns (name, class_name, level, etc.) exist for efficient
lookups by the Rules Engine and API layer.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tavern.models.base import JSONB, Base


class SrdSpecies(Base):
    """Species (race) definitions — size, speed, traits, subspecies."""

    __tablename__ = "srd_species"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    size: Mapped[str] = mapped_column(String)
    speed: Mapped[int] = mapped_column(Integer)
    darkvision: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full record per species.json schema")


class SrdClass(Base):
    """Character class definitions — hit die, saving throws, features by level."""

    __tablename__ = "srd_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    hit_die: Mapped[int] = mapped_column(Integer)
    subclass_level: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full class record per class.json schema")


class SrdClassFeature(Base):
    """Individual class feature at a specific level."""

    __tablename__ = "srd_class_features"
    __table_args__ = (UniqueConstraint("class_name", "name", name="uq_class_features_class_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, index=True)
    class_name: Mapped[str] = mapped_column(String, index=True)
    level: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full feature record per class_feature.json schema"
    )


class SrdSubclass(Base):
    """Subclass definitions — features by level, parent class."""

    __tablename__ = "srd_subclasses"
    __table_args__ = (UniqueConstraint("class_name", "name", name="uq_subclasses_class_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, index=True)
    class_name: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full subclass record per subclass.json schema"
    )


class SrdBackground(Base):
    """Background definitions — ability scores, skill proficiencies, origin feat."""

    __tablename__ = "srd_backgrounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full background record per background.json schema"
    )


class SrdFeat(Base):
    """Feat definitions — category, prerequisites, mechanical effects."""

    __tablename__ = "srd_feats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full feat record per feat.json schema")


class SrdWeapon(Base):
    """Weapon definitions — damage dice, damage type, properties."""

    __tablename__ = "srd_weapons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    damage_dice: Mapped[str] = mapped_column(String)
    damage_type: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full weapon record per weapon.json schema")


class SrdArmor(Base):
    """Armor definitions — type, base AC, DEX cap, stealth disadvantage."""

    __tablename__ = "srd_armor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    type: Mapped[str] = mapped_column(String, index=True)
    base_ac: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full armor record per armor.json schema")


class SrdEquipment(Base):
    """Adventuring gear and miscellaneous equipment."""

    __tablename__ = "srd_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full equipment record per equipment.json schema"
    )


class SrdSpell(Base):
    """Spell definitions — level, school, components, damage, save, AOE."""

    __tablename__ = "srd_spells"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    level: Mapped[int] = mapped_column(Integer, index=True)
    school: Mapped[str] = mapped_column(String, index=True)
    requires_concentration: Mapped[bool] = mapped_column(default=False)
    ritual: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(JSONB, comment="Full spell record per spell.json schema")


class SrdMonster(Base):
    """Monster stat blocks — ability scores, resistances, CR, actions."""

    __tablename__ = "srd_monsters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    size: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, index=True)
    cr: Mapped[float] = mapped_column(Float, index=True)
    xp: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full monster record per monster.json schema"
    )


class SrdMonsterAction(Base):
    """Monster actions, traits, and legendary actions stored separately for lookup."""

    __tablename__ = "srd_monster_actions"
    __table_args__ = (
        UniqueConstraint("monster_name", "name", name="uq_monster_actions_monster_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monster_name: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full action record per monster_action.json schema"
    )


class SrdCondition(Base):
    """Condition definitions with structured mechanical effects."""

    __tablename__ = "srd_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full condition record per condition.json schema"
    )


class SrdMagicItem(Base):
    """Magic item definitions — rarity, attunement, mechanical effects."""

    __tablename__ = "srd_magic_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    type: Mapped[str] = mapped_column(String, index=True)
    rarity: Mapped[str] = mapped_column(String, index=True)
    requires_attunement: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Full magic item record per magic_item.json schema"
    )


class SrdRulesTable(Base):
    """Reference tables (encumbrance, exhaustion levels, carrying capacity, etc.)."""

    __tablename__ = "srd_rules_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(
        JSONB, comment="Table data; structure varies per table — see rules_table.json schema"
    )
