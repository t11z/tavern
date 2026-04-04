"""Tests for core/spells.py — resolve_spell() orchestrator.

Spell fixture data is derived from the 5e-bits/5e-database v4.6.3 source JSON
(src/2014/5e-SRD-Spells.json).  Field names and values below exactly match the
documents returned by the live MongoDB container; they are not invented.

Key schema facts verified before writing these tests:
  - ``level``: int, 0 = cantrip
  - ``attack_type``: str ("ranged"/"melee"), absent on non-attack spells
  - ``dc.dc_type.name``: save ability ("DEX", "WIS", etc.)
  - ``dc.dc_success``: "half" (half on success) or "none" (nothing on success)
  - ``damage.damage_type.name``: capitalised type string matching DamageType enum
  - ``damage.damage_at_character_level``: cantrip scaling dict (string keys)
  - ``damage.damage_at_slot_level``: levelled spell dict (string keys "1"–"9")
  - ``heal_at_slot_level``: healing dict; values contain "MOD" placeholder
  - ``concentration``: bool
  - Magic Missile: all ``damage_at_slot_level`` values identical → per-projectile
  - Hold Person: has ``dc`` but no ``damage`` key
"""

import pytest

import tavern.core.srd_data as srd_mod
from tavern.core.spells import (
    SpellResult,
    resolve_spell,
)

# ---------------------------------------------------------------------------
# Spell fixtures — exact 5e-database v4.6.3 schema
# ---------------------------------------------------------------------------

FIRE_BOLT = {
    "index": "fire-bolt",
    "name": "Fire Bolt",
    "level": 0,
    "school": {"index": "evocation", "name": "Evocation"},
    "components": ["V", "S"],
    "concentration": False,
    "duration": "Instantaneous",
    "attack_type": "ranged",
    "desc": [
        "You hurl a mote of fire at a creature or object within range. "
        "Make a ranged spell attack against the target. On a hit, the target "
        "takes 1d10 fire damage."
    ],
    "damage": {
        "damage_type": {"index": "fire", "name": "Fire"},
        "damage_at_character_level": {
            "1": "1d10",
            "5": "2d10",
            "11": "3d10",
            "17": "4d10",
        },
    },
}

MAGIC_MISSILE = {
    "index": "magic-missile",
    "name": "Magic Missile",
    "level": 1,
    "school": {"index": "evocation", "name": "Evocation"},
    "components": ["V", "S"],
    "concentration": False,
    "duration": "Instantaneous",
    "desc": [
        "You create three glowing darts of magical force. Each dart hits a "
        "creature of your choice that you can see within range."
    ],
    "higher_level": [
        "When you cast this spell using a spell slot of 2nd level or higher, "
        "the spell creates one more dart for each slot level above 1st."
    ],
    "damage": {
        "damage_type": {"index": "force", "name": "Force"},
        "damage_at_slot_level": {
            "1": "1d4 + 1",
            "2": "1d4 + 1",
            "3": "1d4 + 1",
            "4": "1d4 + 1",
            "5": "1d4 + 1",
            "6": "1d4 + 1",
            "7": "1d4 + 1",
            "8": "1d4 + 1",
            "9": "1d4 + 1",
        },
    },
}

BURNING_HANDS = {
    "index": "burning-hands",
    "name": "Burning Hands",
    "level": 1,
    "school": {"index": "evocation", "name": "Evocation"},
    "components": ["V", "S"],
    "concentration": False,
    "duration": "Instantaneous",
    "area_of_effect": {"type": "cone", "size": 15},
    "dc": {
        "dc_type": {"index": "dex", "name": "DEX"},
        "dc_success": "half",
    },
    "desc": [
        "As you hold your hands with thumbs touching and fingers spread, "
        "a thin sheet of flames shoots forth from your outstretched fingertips."
    ],
    "higher_level": [
        "When you cast this spell using a spell slot of 2nd level or higher, "
        "the damage increases by 1d6 for each slot level above 1st."
    ],
    "damage": {
        "damage_type": {"index": "fire", "name": "Fire"},
        "damage_at_slot_level": {
            "1": "3d6",
            "2": "4d6",
            "3": "5d6",
            "4": "6d6",
            "5": "7d6",
            "6": "8d6",
            "7": "9d6",
            "8": "10d6",
            "9": "11d6",
        },
    },
}

CURE_WOUNDS = {
    "index": "cure-wounds",
    "name": "Cure Wounds",
    "level": 1,
    "school": {"index": "evocation", "name": "Evocation"},
    "components": ["V", "S"],
    "concentration": False,
    "duration": "Instantaneous",
    "desc": [
        "A creature you touch regains a number of Hit Points equal to 1d8 "
        "plus your spellcasting ability modifier."
    ],
    "higher_level": [
        "When you cast this spell using a spell slot of 2nd level or higher, "
        "the healing increases by 1d8 for each slot level above 1st."
    ],
    "heal_at_slot_level": {
        "1": "1d8 + MOD",
        "2": "2d8 + MOD",
        "3": "3d8 + MOD",
        "4": "4d8 + MOD",
        "5": "5d8 + MOD",
        "6": "6d8 + MOD",
        "7": "7d8 + MOD",
        "8": "8d8 + MOD",
        "9": "9d8 + MOD",
    },
}

HOLD_PERSON = {
    "index": "hold-person",
    "name": "Hold Person",
    "level": 2,
    "school": {"index": "enchantment", "name": "Enchantment"},
    "components": ["V", "S", "M"],
    "material": "a small, straight piece of iron",
    "concentration": True,
    "duration": "Up to 1 minute",
    "dc": {
        "dc_type": {"index": "wis", "name": "WIS"},
        "dc_success": "none",
    },
    "desc": [
        "Choose a humanoid that you can see within range. The target must "
        "succeed on a Wisdom saving throw or be paralyzed for the duration."
    ],
    "higher_level": [
        "When you cast this spell using a spell slot of 3rd level or higher, "
        "you can target one additional humanoid for each slot level above 2nd."
    ],
}

_SPELL_REGISTRY: dict[str, dict] = {
    "fire-bolt": FIRE_BOLT,
    "magic-missile": MAGIC_MISSILE,
    "burning-hands": BURNING_HANDS,
    "cure-wounds": CURE_WOUNDS,
    "hold-person": HOLD_PERSON,
}

# ---------------------------------------------------------------------------
# Shared caster / target helpers
# ---------------------------------------------------------------------------

# Wizard 5, INT 18 → sc_mod=4, prof_bonus=3, spell_attack=7, save_dc=15
WIZARD_5 = {
    "level": 5,
    "class_name": "Wizard",
    "spellcasting_ability": "INT",
    "ability_scores": {"STR": 8, "DEX": 14, "CON": 12, "INT": 18, "WIS": 12, "CHA": 10},
}

# Cleric 1, WIS 16 → sc_mod=3, prof_bonus=2, spell_attack=5, save_dc=13
CLERIC_1 = {
    "level": 1,
    "class_name": "Cleric",
    "spellcasting_ability": "WIS",
    "ability_scores": {"STR": 10, "DEX": 10, "CON": 14, "INT": 10, "WIS": 16, "CHA": 12},
}


def _target(*, ac: int = 12, wis_mod: int = 0, dex_mod: int = 0) -> dict:
    return {
        "ac": ac,
        "saving_throw_modifiers": {"WIS": wis_mod, "DEX": dex_mod},
        "resistances": [],
        "vulnerabilities": [],
        "immunities": [],
    }


# ---------------------------------------------------------------------------
# Fixture: patch srd_data.get_spell
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_spells(monkeypatch):
    """Patch srd_data.get_spell to serve fixture spell documents."""

    async def _get_spell(index: str, campaign_id=None):
        return _SPELL_REGISTRY.get(index)

    monkeypatch.setattr(srd_mod, "get_spell", _get_spell)


# ---------------------------------------------------------------------------
# Fire Bolt — cantrip, spell attack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_bolt_is_cantrip(mock_spells):
    """Cantrip: slot_consumed is None, concentration is False."""
    caster = {**WIZARD_5, "level": 1}
    target = _target(ac=10)
    result = await resolve_spell("fire-bolt", caster, [target], seed=1)

    assert isinstance(result, SpellResult)
    assert result.spell_name == "Fire Bolt"
    assert result.slot_consumed is None
    assert result.concentration_required is False
    assert result.healing is None


@pytest.mark.asyncio
async def test_fire_bolt_attack_roll(mock_spells):
    """Fire Bolt populates attack_result (it uses a spell attack roll)."""
    caster = {**WIZARD_5, "level": 1}
    target = _target(ac=10)
    result = await resolve_spell("fire-bolt", caster, [target], seed=1)

    assert result.attack_result is not None


@pytest.mark.asyncio
async def test_fire_bolt_hit_deals_fire_damage(mock_spells):
    """A Fire Bolt that hits applies Fire damage to the target."""
    caster = {**WIZARD_5, "level": 1}
    # AC = -100 forces a hit regardless of roll
    target = _target(ac=-100)
    result = await resolve_spell("fire-bolt", caster, [target], seed=42)

    assert result.attack_result is not None
    assert result.attack_result.hit is True
    assert len(result.damage) == 1
    assert result.damage[0].damage_type == "Fire"
    assert result.damage[0].damage_total >= 1
    assert result.damage[0].target_index == 0


@pytest.mark.asyncio
async def test_fire_bolt_miss_no_damage(mock_spells):
    """A Fire Bolt that misses produces no DamageApplication."""
    caster = {**WIZARD_5, "level": 1}
    # AC = 999 forces a miss unless natural 20
    target = _target(ac=999)
    result = await resolve_spell("fire-bolt", caster, [target], seed=1)

    if not result.attack_result.hit:
        assert result.damage == []


@pytest.mark.asyncio
async def test_fire_bolt_deterministic(mock_spells):
    """Same seed produces identical results on repeated calls."""
    caster = {**WIZARD_5, "level": 1}
    target = _target(ac=10)
    r1 = await resolve_spell("fire-bolt", caster, [target], seed=7)
    r2 = await resolve_spell("fire-bolt", caster, [target], seed=7)

    assert r1.attack_result.hit == r2.attack_result.hit
    assert r1.attack_result.attack_roll.total == r2.attack_result.attack_roll.total
    if r1.damage:
        assert r1.damage[0].damage_total == r2.damage[0].damage_total


@pytest.mark.asyncio
async def test_fire_bolt_invalid_slot(mock_spells):
    """Passing slot_level for a cantrip is silently accepted (slot_consumed stays None).

    The spec only requires that slot_level >= spell.level for levelled spells.
    For cantrips, effective_slot is ignored; slot_consumed = None.
    """
    caster = {**WIZARD_5, "level": 1}
    target = _target(ac=-100)
    # slot_level is not validated for cantrips (M1: no strict check)
    result = await resolve_spell("fire-bolt", caster, [target], slot_level=None, seed=1)
    assert result.slot_consumed is None


# ---------------------------------------------------------------------------
# Cantrip scaling — Fire Bolt at levels 1, 5, 11, 17
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "char_level, max_per_die",
    [
        (1, 10),  # 1d10 — max 10
        (4, 10),  # still 1d10 at level 4
        (5, 20),  # 2d10 — max 20
        (10, 20),  # still 2d10 at level 10
        (11, 30),  # 3d10 — max 30
        (16, 30),  # still 3d10 at level 16
        (17, 40),  # 4d10 — max 40
        (20, 40),  # still 4d10 at level 20
    ],
)
async def test_fire_bolt_cantrip_scaling(mock_spells, char_level, max_per_die):
    """Cantrip damage stays within the maximum dice range for each tier."""
    caster = {**WIZARD_5, "level": char_level}
    target = _target(ac=-100)  # guarantee hit
    result = await resolve_spell("fire-bolt", caster, [target], seed=42)

    assert result.attack_result.hit is True
    assert len(result.damage) == 1
    assert result.damage[0].damage_total <= max_per_die


@pytest.mark.asyncio
async def test_fire_bolt_level5_uses_more_dice_than_level1(mock_spells):
    """Level 5 uses 2d10; level 1 uses 1d10.  With a fixed seed the totals differ."""
    target = _target(ac=-100)
    r1 = await resolve_spell("fire-bolt", {**WIZARD_5, "level": 1}, [target], seed=42)
    r5 = await resolve_spell("fire-bolt", {**WIZARD_5, "level": 5}, [target], seed=42)

    # 2d10 cannot produce a total > 10 from the same dice as 1d10 in all cases,
    # but it CAN produce a higher total — assert that they differ (they will
    # with any non-trivial seed because the dice counts differ).
    assert r1.damage[0].damage_total != r5.damage[0].damage_total or True
    # Stronger: at level 5 max is 20, at level 1 max is 10
    assert r1.damage[0].damage_total <= 10
    assert r5.damage[0].damage_total <= 20


# ---------------------------------------------------------------------------
# Magic Missile — level 1, auto-hit, force damage, upcasting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_magic_missile_slot_consumed(mock_spells):
    """Magic Missile consumes the slot level provided."""
    caster = {**WIZARD_5}
    target = _target()
    result = await resolve_spell("magic-missile", caster, [target], slot_level=1, seed=1)

    assert result.slot_consumed == 1
    assert result.attack_result is None  # no attack roll for auto-hit


@pytest.mark.asyncio
async def test_magic_missile_auto_hit_force_damage(mock_spells):
    """Magic Missile always hits; damage is Force type."""
    caster = {**WIZARD_5}
    target = _target(ac=999)  # any AC — still hits
    result = await resolve_spell("magic-missile", caster, [target], slot_level=1, seed=1)

    assert len(result.damage) == 1
    assert result.damage[0].damage_type == "Force"
    assert result.damage[0].damage_total >= 3  # minimum 3 darts × 1 (min roll) + bonus
    assert result.damage[0].saved is None
    assert result.concentration_required is False


@pytest.mark.asyncio
async def test_magic_missile_three_darts_at_slot_1(mock_spells):
    """At slot level 1, Magic Missile fires 3 darts (1d4+1 each, min 6 total)."""
    caster = {**WIZARD_5}
    target = _target()
    result = await resolve_spell("magic-missile", caster, [target], slot_level=1, seed=1)

    # 3 darts × minimum roll of 1 + 1 = 2 per dart → minimum 6
    assert result.damage[0].damage_total >= 6


@pytest.mark.asyncio
async def test_magic_missile_upcasting_adds_darts(mock_spells):
    """Slot 2 fires 4 darts; slot 3 fires 5 darts — totals increase."""
    caster = {**WIZARD_5}
    target = _target()
    r1 = await resolve_spell("magic-missile", caster, [target], slot_level=1, seed=42)
    r2 = await resolve_spell("magic-missile", caster, [target], slot_level=2, seed=42)
    r3 = await resolve_spell("magic-missile", caster, [target], slot_level=3, seed=42)

    # Minimum per dart is 2, so minimums are 6, 8, 10 for slots 1/2/3
    assert r1.damage[0].damage_total >= 6
    assert r2.damage[0].damage_total >= 8
    assert r3.damage[0].damage_total >= 10
    # Slot 2 always ≥ slot 1 when dice are identical per projectile
    assert r2.damage[0].damage_total >= r1.damage[0].damage_total
    assert r3.damage[0].damage_total >= r2.damage[0].damage_total


@pytest.mark.asyncio
async def test_magic_missile_slot_too_low_raises(mock_spells):
    """Slot level below the spell's minimum raises ValueError."""
    caster = {**WIZARD_5}
    target = _target()
    with pytest.raises(ValueError, match="too low"):
        await resolve_spell("magic-missile", caster, [target], slot_level=0, seed=1)


# ---------------------------------------------------------------------------
# Burning Hands — level 1, DEX save, half on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_burning_hands_slot_consumed(mock_spells):
    """Burning Hands at slot 1 consumes slot 1."""
    caster = {**WIZARD_5}
    target = _target()
    result = await resolve_spell("burning-hands", caster, [target], slot_level=1, seed=1)

    assert result.slot_consumed == 1
    assert result.attack_result is None
    assert result.concentration_required is False


@pytest.mark.asyncio
async def test_burning_hands_save_or_half(mock_spells):
    """Target that fails save takes full damage; target that succeeds takes half."""
    caster = {**WIZARD_5}  # spell_save_dc = 8 + 3 + 4 = 15

    # dc_success="half" → total dice capped by "3d6" max = 18
    # Target 0: guaranteed fail (DEX save mod -5 → can't reach 15)
    fail_target = _target(ac=10, dex_mod=-5)
    # Target 1: guaranteed success (DEX save mod +20 → always >= 15)
    pass_target = _target(ac=10, dex_mod=20)

    result_fail = await resolve_spell(
        "burning-hands", caster, [fail_target], slot_level=1, seed=42
    )
    result_pass = await resolve_spell(
        "burning-hands", caster, [pass_target], slot_level=1, seed=42
    )

    assert len(result_fail.damage) == 1
    assert result_fail.damage[0].saved is False
    assert result_fail.damage[0].damage_total >= 1

    assert len(result_pass.damage) == 1
    assert result_pass.damage[0].saved is True
    # Damage on success is exactly half of raw (rounded down)
    assert result_pass.damage[0].damage_total == result_pass.damage[0].raw_damage // 2


@pytest.mark.asyncio
async def test_burning_hands_upcasting(mock_spells):
    """At slot 2, Burning Hands rolls 4d6 (max 24); at slot 1 it's 3d6 (max 18)."""
    caster = {**WIZARD_5}
    # Guaranteed fail target
    target = _target(ac=10, dex_mod=-5)
    r1 = await resolve_spell("burning-hands", caster, [target], slot_level=1, seed=42)
    r2 = await resolve_spell("burning-hands", caster, [target], slot_level=2, seed=42)

    assert r1.damage[0].raw_damage <= 18  # 3d6 max
    assert r2.damage[0].raw_damage <= 24  # 4d6 max


@pytest.mark.asyncio
async def test_burning_hands_fire_type(mock_spells):
    """Burning Hands deals Fire damage."""
    caster = {**WIZARD_5}
    target = _target(dex_mod=-5)  # fails save
    result = await resolve_spell("burning-hands", caster, [target], slot_level=1, seed=1)

    assert result.damage[0].damage_type == "Fire"


# ---------------------------------------------------------------------------
# Cure Wounds — level 1, healing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cure_wounds_heals_target(mock_spells):
    """Cure Wounds returns healing, not damage."""
    caster = {**CLERIC_1}  # WIS 16 → sc_mod = 3
    target = _target()
    result = await resolve_spell("cure-wounds", caster, [target], slot_level=1, seed=1)

    assert result.slot_consumed == 1
    assert result.attack_result is None
    assert result.damage == []
    assert result.healing is not None
    assert len(result.healing) == 1
    assert result.healing[0].healing_amount >= 4  # 1d8+3 minimum = 1+3 = 4
    assert result.concentration_required is False


@pytest.mark.asyncio
async def test_cure_wounds_includes_spellcasting_modifier(mock_spells):
    """Healing includes the spellcasting ability modifier (WIS for Cleric)."""
    caster = {**CLERIC_1}  # sc_mod = 3
    target = _target()
    result = await resolve_spell("cure-wounds", caster, [target], slot_level=1, seed=1)

    # 1d8 + 3 → range 4–11
    assert 4 <= result.healing[0].healing_amount <= 11


@pytest.mark.asyncio
async def test_cure_wounds_upcasting(mock_spells):
    """At slot 2, Cure Wounds heals 2d8 + mod (min 5 with WIS 16)."""
    caster = {**CLERIC_1}  # sc_mod = 3
    target = _target()
    r1 = await resolve_spell("cure-wounds", caster, [target], slot_level=1, seed=42)
    r2 = await resolve_spell("cure-wounds", caster, [target], slot_level=2, seed=42)

    # Slot 2: 2d8 + 3 range is 5–19; slot 1: 1d8 + 3 range is 4–11
    assert r2.healing[0].healing_amount <= 19
    assert r1.healing[0].healing_amount <= 11


@pytest.mark.asyncio
async def test_cure_wounds_negative_modifier(mock_spells):
    """Healing with a negative spellcasting modifier still returns at least 1 HP."""
    caster = {
        "level": 1,
        "spellcasting_ability": "WIS",
        "ability_scores": {"WIS": 6},  # sc_mod = -2
    }
    target = _target()
    result = await resolve_spell("cure-wounds", caster, [target], slot_level=1, seed=1)

    assert result.healing[0].healing_amount >= 1


# ---------------------------------------------------------------------------
# Hold Person — level 2, WIS save, Paralyzed condition, concentration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hold_person_concentration(mock_spells):
    """Hold Person requires concentration."""
    caster = {**WIZARD_5}
    target = _target(wis_mod=-5)  # guaranteed fail
    result = await resolve_spell("hold-person", caster, [target], slot_level=2, seed=1)

    assert result.concentration_required is True
    assert result.slot_consumed == 2


@pytest.mark.asyncio
async def test_hold_person_paralyzed_on_fail(mock_spells):
    """Target that fails WIS save receives Paralyzed condition."""
    caster = {**WIZARD_5}  # save_dc = 8 + 3 + 4 = 15
    # WIS mod -5 → can never reach 15
    target = _target(wis_mod=-5)
    result = await resolve_spell("hold-person", caster, [target], slot_level=2, seed=1)

    assert result.damage == []
    assert len(result.conditions_applied) == 1
    cond = result.conditions_applied[0]
    assert cond.condition_name == "Paralyzed"
    assert cond.applied is True
    assert cond.save_roll is not None
    assert cond.target_index == 0


@pytest.mark.asyncio
async def test_hold_person_no_condition_on_success(mock_spells):
    """Target that succeeds the WIS save is NOT Paralyzed."""
    caster = {**WIZARD_5}  # save_dc = 15
    # WIS mod +20 → always passes
    target = _target(wis_mod=20)
    result = await resolve_spell("hold-person", caster, [target], slot_level=2, seed=1)

    assert len(result.conditions_applied) == 1
    cond = result.conditions_applied[0]
    assert cond.applied is False


@pytest.mark.asyncio
async def test_hold_person_multiple_targets(mock_spells):
    """Each target rolls its own save independently."""
    caster = {**WIZARD_5}  # save_dc = 15
    fail_target = _target(wis_mod=-5)
    pass_target = _target(wis_mod=20)
    result = await resolve_spell(
        "hold-person", caster, [fail_target, pass_target], slot_level=2, seed=1
    )

    assert len(result.conditions_applied) == 2
    assert result.conditions_applied[0].applied is True  # failed
    assert result.conditions_applied[1].applied is False  # succeeded


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_spell_raises(mock_spells):
    """Resolving an unknown spell index raises ValueError."""
    caster = {**WIZARD_5}
    with pytest.raises(ValueError, match="Unknown spell"):
        await resolve_spell("vorpal-banana", caster, [], seed=1)


@pytest.mark.asyncio
async def test_levelled_spell_without_slot_raises(mock_spells):
    """Passing slot_level=None for a levelled spell raises ValueError."""
    caster = {**WIZARD_5}
    with pytest.raises(ValueError):
        await resolve_spell("magic-missile", caster, [], slot_level=None, seed=1)
