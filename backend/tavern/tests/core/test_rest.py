"""Tests for Short Rest and Long Rest mechanics in core/characters.py."""

import pytest

from tavern.core.characters import (
    LongRestResult,
    ShortRestResult,
    apply_long_rest,
    apply_short_rest,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Fighter 5, CON 14 (mod +2), hit die d10, 3 hit dice remaining, 28/40 HP
FIGHTER_5 = {
    "class_name": "Fighter",
    "level": 5,
    "hp": 28,
    "max_hp": 40,
    "hit_dice_remaining": 3,
    "con_modifier": 2,
    "spell_slots_used": {},
}

# Wizard 3, INT 16, CON 10 (mod 0), hit die d6, 1 hit die remaining, 10/18 HP
# Has used 2 level-1 slots and 1 level-2 slot
WIZARD_3 = {
    "class_name": "Wizard",
    "level": 3,
    "hp": 10,
    "max_hp": 18,
    "hit_dice_remaining": 1,
    "con_modifier": 0,
    "spell_slots_used": {1: 2, 2: 1},
}

# Barbarian 1, CON 16 (mod +3), full HP
BARBARIAN_1_FULL = {
    "class_name": "Barbarian",
    "level": 1,
    "hp": 14,
    "max_hp": 14,
    "hit_dice_remaining": 1,
    "con_modifier": 3,
    "spell_slots_used": {},
}


# ---------------------------------------------------------------------------
# Short Rest — spend 0 dice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_no_dice(mock_srd_data):
    result = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=0)

    assert isinstance(result, ShortRestResult)
    assert result.hp_regained == 0
    assert result.hit_dice_spent == 0
    assert result.hit_dice_remaining == 3  # unchanged
    assert result.new_hp == 28  # unchanged
    assert result.rolls == []


# ---------------------------------------------------------------------------
# Short Rest — spend 1 die
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_one_die(mock_srd_data):
    result = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=1, seed=1)

    assert result.hit_dice_spent == 1
    assert result.hit_dice_remaining == 2
    assert len(result.rolls) == 1
    # Roll is 1d10 + 2 CON modifier; minimum per die is 1+2=3
    assert result.hp_regained >= 3
    assert result.new_hp == 28 + result.hp_regained
    assert result.new_hp <= 40


@pytest.mark.asyncio
async def test_short_rest_one_die_deterministic(mock_srd_data):
    r1 = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=1, seed=7)
    r2 = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=1, seed=7)

    assert r1.rolls == r2.rolls
    assert r1.hp_regained == r2.hp_regained


# ---------------------------------------------------------------------------
# Short Rest — spend multiple dice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_spend_all_dice(mock_srd_data):
    result = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=3, seed=42)

    assert result.hit_dice_spent == 3
    assert result.hit_dice_remaining == 0
    assert len(result.rolls) == 3
    # Each die: min 1+2=3, max 10+2=12 → total min 9
    assert result.hp_regained >= 9
    assert result.new_hp <= 40


# ---------------------------------------------------------------------------
# Short Rest — HP cannot exceed max
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_hp_capped_at_max(mock_srd_data):
    near_full = {**FIGHTER_5, "hp": 39}  # 1 HP below max
    result = await apply_short_rest(near_full, hit_dice_to_spend=3, seed=1)

    assert result.new_hp == 40  # capped at max_hp
    assert result.hp_regained == 1


@pytest.mark.asyncio
async def test_short_rest_already_full_hp(mock_srd_data):
    full_hp = {**FIGHTER_5, "hp": 40}
    result = await apply_short_rest(full_hp, hit_dice_to_spend=1, seed=1)

    assert result.new_hp == 40
    assert result.hp_regained == 0


# ---------------------------------------------------------------------------
# Short Rest — spend more than available raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_overspend_raises(mock_srd_data):
    with pytest.raises(ValueError, match="Cannot spend"):
        await apply_short_rest(FIGHTER_5, hit_dice_to_spend=4)


@pytest.mark.asyncio
async def test_short_rest_negative_dice_raises(mock_srd_data):
    with pytest.raises(ValueError):
        await apply_short_rest(FIGHTER_5, hit_dice_to_spend=-1)


# ---------------------------------------------------------------------------
# Short Rest — CON modifier affects each die
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_con_modifier_applied(mock_srd_data):
    # Wizard with CON 0 modifier: 1d6 + 0
    result = await apply_short_rest(WIZARD_3, hit_dice_to_spend=1, seed=1)

    assert result.hp_regained == result.rolls[0]  # no modifier added


@pytest.mark.asyncio
async def test_short_rest_con_modifier_minimum_zero_per_die(mock_srd_data):
    """A bad CON roll + negative modifier cannot produce negative healing per die."""
    low_con = {**WIZARD_3, "con_modifier": -3, "hit_dice_remaining": 5}
    result = await apply_short_rest(low_con, hit_dice_to_spend=5, seed=1)

    assert result.hp_regained >= 0


# ---------------------------------------------------------------------------
# Long Rest — full HP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_rest_restores_full_hp(mock_srd_data):
    result = await apply_long_rest(FIGHTER_5)

    assert isinstance(result, LongRestResult)
    assert result.new_hp == 40
    assert result.hp_restored == 12  # 40 - 28


@pytest.mark.asyncio
async def test_long_rest_already_full_hp(mock_srd_data):
    result = await apply_long_rest(BARBARIAN_1_FULL)

    assert result.hp_restored == 0
    assert result.new_hp == 14


# ---------------------------------------------------------------------------
# Long Rest — spell slot restoration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_rest_restores_spell_slots(mock_srd_data):
    result = await apply_long_rest(WIZARD_3)

    # Used: 2 level-1 slots, 1 level-2 slot → all restored
    assert result.spell_slots_restored == {1: 2, 2: 1}


@pytest.mark.asyncio
async def test_long_rest_no_spell_slots_used(mock_srd_data):
    result = await apply_long_rest(FIGHTER_5)

    assert result.spell_slots_restored == {}


# ---------------------------------------------------------------------------
# Long Rest — hit die recovery (half total, rounded down, minimum 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_rest_hit_dice_half_rounded_down(mock_srd_data):
    # Level 5, 3 remaining (2 spent) → recover min(2, max(1, 5//2)) = min(2, 2) = 2
    result = await apply_long_rest(FIGHTER_5)

    assert result.hit_dice_restored == 2
    assert result.new_hit_dice == 5


@pytest.mark.asyncio
async def test_long_rest_hit_dice_minimum_one(mock_srd_data):
    # Level 1: half = 0, but minimum is 1
    spent_all = {**BARBARIAN_1_FULL, "hit_dice_remaining": 0}
    result = await apply_long_rest(spent_all)

    assert result.hit_dice_restored == 1
    assert result.new_hit_dice == 1


@pytest.mark.asyncio
async def test_long_rest_hit_dice_level_3_odd(mock_srd_data):
    # Level 3: 3 // 2 = 1 (rounded down), 1 spent → recover min(1, 1) = 1
    spent_one = {**WIZARD_3, "hit_dice_remaining": 2}
    result = await apply_long_rest(spent_one)

    assert result.hit_dice_restored == 1
    assert result.new_hit_dice == 3


@pytest.mark.asyncio
async def test_long_rest_hit_dice_cannot_exceed_total(mock_srd_data):
    # Already at full hit dice — nothing to restore
    full_dice = {**FIGHTER_5, "hit_dice_remaining": 5}
    result = await apply_long_rest(full_dice)

    assert result.hit_dice_restored == 0
    assert result.new_hit_dice == 5


# ---------------------------------------------------------------------------
# Long Rest — death save reset (documented in description)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_rest_description_mentions_death_saves(mock_srd_data):
    result = await apply_long_rest(WIZARD_3)

    assert "death saves reset" in result.description.lower()


# ---------------------------------------------------------------------------
# Result shape smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rest_result_has_description(mock_srd_data):
    result = await apply_short_rest(FIGHTER_5, hit_dice_to_spend=1, seed=1)
    assert isinstance(result.description, str)
    assert len(result.description) > 0


@pytest.mark.asyncio
async def test_long_rest_result_has_description(mock_srd_data):
    result = await apply_long_rest(WIZARD_3)
    assert isinstance(result.description, str)
    assert len(result.description) > 0
