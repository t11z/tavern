"""Root conftest — fixtures shared across all test packages.

The ``mock_srd_data`` fixture is autouse so that every test (unit and API)
runs without a live MongoDB connection.  The mocks return data from
``tests/fixtures/srd_fixtures.py`` — a static snapshot of the SRD data
used exclusively as test fixture data.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tavern.core.srd_data as srd_mod
from tavern.models.base import Base
from tavern.tests.fixtures.srd_fixtures import (
    ALL_FEATS,
    BACKGROUNDS,
    CLASS_CANTRIPS_KNOWN,
    CLASS_FEATURES,
    CLASS_PROFICIENCIES,
    CLASS_SPELLS_PREPARED,
    CLASS_STARTING_EQUIPMENT,
    FIXED_HP_PER_LEVEL,
    FULL_CASTER_SPELL_SLOTS,
    FULL_CASTERS,
    HALF_CASTER_SPELL_SLOTS,
    HALF_CASTERS,
    HIT_DICE,
    MULTICLASS_PROFICIENCY_GAINS,
    PRIMARY_ABILITIES,
    PROFICIENCY_BONUS_BY_LEVEL,
    SPECIES_TRAITS,
    WARLOCK_PACT_MAGIC,
    XP_THRESHOLDS,
)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(autouse=True)
def mock_srd_data(monkeypatch):
    """Patch all tavern.core.srd_data coroutines with srd_fixtures data.

    Applied to every test so that no test needs a live MongoDB connection.
    Integration tests that need real MongoDB should override or skip this
    fixture explicitly.
    """

    async def _get_proficiency_bonus(level: int) -> int:
        if level not in PROFICIENCY_BONUS_BY_LEVEL:
            raise ValueError(f"Level must be 1–20, got {level}")
        return PROFICIENCY_BONUS_BY_LEVEL[level]

    async def _get_class_hit_die(class_name: str) -> int:
        if class_name not in HIT_DICE:
            raise ValueError(f"Unknown class: {class_name!r}")
        return HIT_DICE[class_name]

    async def _get_class_fixed_hp_per_level(class_name: str) -> int:
        if class_name not in FIXED_HP_PER_LEVEL:
            raise ValueError(f"Unknown class: {class_name!r}")
        return FIXED_HP_PER_LEVEL[class_name]

    async def _get_class_spell_slots(class_name: str, level: int) -> dict:
        if class_name in FULL_CASTERS:
            return dict(FULL_CASTER_SPELL_SLOTS[level - 1])
        if class_name in HALF_CASTERS:
            return dict(HALF_CASTER_SPELL_SLOTS[level - 1])
        if class_name == "Warlock":
            num_slots, slot_level = WARLOCK_PACT_MAGIC[level - 1]
            return {slot_level: num_slots}
        return {}  # non-caster

    async def _get_warlock_pact_magic(level: int) -> tuple:
        return WARLOCK_PACT_MAGIC[level - 1]

    async def _get_xp_thresholds() -> list:
        return list(XP_THRESHOLDS)

    async def _get_class_primary_abilities(class_name: str) -> list:
        if class_name not in PRIMARY_ABILITIES:
            raise ValueError(f"Unknown class: {class_name!r}")
        return PRIMARY_ABILITIES[class_name]

    async def _get_class(name: str):
        for cls in srd_mod.ALL_CLASSES:
            if cls.lower() == name.lower():
                return {"name": cls}
        return None

    async def _get_species(name: str):
        for k in SPECIES_TRAITS:
            if k.lower() == name.lower():
                return {"name": k}
        return None

    async def _get_background(name: str):
        for k in BACKGROUNDS:
            if k.lower() == name.lower():
                return {"name": k}
        return None

    async def _get_background_doc(bg_name: str) -> dict:
        for k, v in BACKGROUNDS.items():
            if k.lower() == bg_name.lower():
                return v
        raise ValueError(f"Unknown background: {bg_name!r}")

    async def _get_class_cantrips_known(class_name: str, level: int) -> int:
        if class_name not in CLASS_CANTRIPS_KNOWN:
            return 0
        return CLASS_CANTRIPS_KNOWN[class_name][level - 1]

    async def _get_class_spells_prepared(class_name: str, level: int) -> int:
        if class_name not in CLASS_SPELLS_PREPARED:
            return 0
        return CLASS_SPELLS_PREPARED[class_name][level - 1]

    async def _get_class_features_at_level(class_name: str, level: int) -> list:
        if class_name not in CLASS_FEATURES:
            return []
        return list(CLASS_FEATURES[class_name].get(level, []))

    async def _get_class_proficiencies_data(class_name: str) -> dict:
        if class_name not in CLASS_PROFICIENCIES:
            raise ValueError(f"Unknown class: {class_name!r}")
        return CLASS_PROFICIENCIES[class_name]

    async def _get_class_multiclass_proficiency_gains(class_name: str) -> dict:
        if class_name not in MULTICLASS_PROFICIENCY_GAINS:
            raise ValueError(f"Unknown class: {class_name!r}")
        return MULTICLASS_PROFICIENCY_GAINS[class_name]

    async def _get_class_starting_equipment_data(class_name: str) -> dict:
        if class_name not in CLASS_STARTING_EQUIPMENT:
            raise ValueError(f"Unknown class: {class_name!r}")
        return CLASS_STARTING_EQUIPMENT[class_name]

    async def _get_species_data(species_name: str) -> dict:
        for k, v in SPECIES_TRAITS.items():
            if k.lower() == species_name.lower():
                return v
        raise ValueError(f"Unknown species: {species_name!r}")

    async def _get_feat_doc(feat_name: str) -> dict:
        if feat_name not in ALL_FEATS:
            raise ValueError(f"Unknown feat: {feat_name!r}")
        return ALL_FEATS[feat_name]

    async def _get_spell(index: str, campaign_id: str | None = None) -> dict | None:
        # Default mock: no spell data — callers must patch individually for spell tests.
        return None

    monkeypatch.setattr(srd_mod, "get_proficiency_bonus", _get_proficiency_bonus)
    monkeypatch.setattr(srd_mod, "get_class_hit_die", _get_class_hit_die)
    monkeypatch.setattr(srd_mod, "get_class_fixed_hp_per_level", _get_class_fixed_hp_per_level)
    monkeypatch.setattr(srd_mod, "get_class_spell_slots", _get_class_spell_slots)
    monkeypatch.setattr(srd_mod, "get_warlock_pact_magic", _get_warlock_pact_magic)
    monkeypatch.setattr(srd_mod, "get_xp_thresholds", _get_xp_thresholds)
    monkeypatch.setattr(srd_mod, "get_class_primary_abilities", _get_class_primary_abilities)
    monkeypatch.setattr(srd_mod, "get_class", _get_class)
    monkeypatch.setattr(srd_mod, "get_species", _get_species)
    monkeypatch.setattr(srd_mod, "get_background", _get_background)
    monkeypatch.setattr(srd_mod, "get_background_doc", _get_background_doc)
    monkeypatch.setattr(srd_mod, "get_class_cantrips_known", _get_class_cantrips_known)
    monkeypatch.setattr(srd_mod, "get_class_spells_prepared", _get_class_spells_prepared)
    monkeypatch.setattr(srd_mod, "get_class_features_at_level", _get_class_features_at_level)
    monkeypatch.setattr(srd_mod, "get_class_proficiencies_data", _get_class_proficiencies_data)
    monkeypatch.setattr(
        srd_mod, "get_class_multiclass_proficiency_gains", _get_class_multiclass_proficiency_gains
    )
    monkeypatch.setattr(
        srd_mod, "get_class_starting_equipment_data", _get_class_starting_equipment_data
    )
    monkeypatch.setattr(srd_mod, "get_species_data", _get_species_data)
    monkeypatch.setattr(srd_mod, "get_feat_doc", _get_feat_doc)
    monkeypatch.setattr(srd_mod, "get_spell", _get_spell)
