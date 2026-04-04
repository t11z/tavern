import pytest

from tavern.core.characters import (
    ability_modifier,
    apply_background_bonuses,
    can_multiclass,
    hp_gained_on_level_up,
    level_for_xp,
    max_hp_at_level_1,
    multiclass_spell_slots,
    proficiency_bonus,
    spell_slots,
    validate_point_buy,
    validate_standard_array,
)
from tavern.tests.fixtures.srd_fixtures import PRIMARY_ABILITIES, XP_THRESHOLDS


class TestAbilityModifier:
    def test_score_10_returns_0(self) -> None:
        assert ability_modifier(10) == 0

    def test_score_11_returns_0(self) -> None:
        assert ability_modifier(11) == 0

    def test_score_14_returns_plus2(self) -> None:
        assert ability_modifier(14) == 2

    def test_score_8_returns_minus1(self) -> None:
        assert ability_modifier(8) == -1

    def test_score_20_returns_plus5(self) -> None:
        assert ability_modifier(20) == 5

    def test_score_1_returns_minus5(self) -> None:
        assert ability_modifier(1) == -5

    def test_score_18_returns_plus4(self) -> None:
        assert ability_modifier(18) == 4

    def test_score_9_returns_minus1(self) -> None:
        assert ability_modifier(9) == -1

    def test_score_15_returns_plus2(self) -> None:
        assert ability_modifier(15) == 2


class TestValidateStandardArray:
    def test_exact_standard_array_valid(self) -> None:
        assert validate_standard_array([15, 14, 13, 12, 10, 8]) is True

    def test_permuted_standard_array_valid(self) -> None:
        assert validate_standard_array([8, 10, 12, 13, 14, 15]) is True
        assert validate_standard_array([13, 15, 8, 14, 10, 12]) is True

    def test_duplicate_value_invalid(self) -> None:
        assert validate_standard_array([15, 15, 13, 12, 10, 8]) is False

    def test_wrong_values_invalid(self) -> None:
        assert validate_standard_array([15, 14, 13, 12, 10, 9]) is False

    def test_too_few_scores_invalid(self) -> None:
        assert validate_standard_array([15, 14, 13, 12, 10]) is False

    def test_all_same_invalid(self) -> None:
        assert validate_standard_array([10, 10, 10, 10, 10, 10]) is False


class TestValidatePointBuy:
    def test_minimum_scores_valid(self) -> None:
        # All 8s: cost 0 each, total 0
        scores = {"STR": 8, "DEX": 8, "CON": 8, "INT": 8, "WIS": 8, "CHA": 8}
        assert validate_point_buy(scores) is True

    def test_exactly_27_points_valid(self) -> None:
        # 15+15+8+8+8+8 = 9+9+0+0+0+0 = 18; need exactly 27
        # 15+14+13+8+8+8 = 9+7+5+0+0+0 = 21; still under
        # Let's do 15+15+15+8+8+8 = 27
        scores = {"STR": 15, "DEX": 15, "CON": 15, "INT": 8, "WIS": 8, "CHA": 8}
        assert validate_point_buy(scores) is True

    def test_over_budget_invalid(self) -> None:
        # 15+15+15+15+8+8 = 9+9+9+9+0+0 = 36 > 27
        scores = {"STR": 15, "DEX": 15, "CON": 15, "INT": 15, "WIS": 8, "CHA": 8}
        assert validate_point_buy(scores) is False

    def test_score_above_15_invalid(self) -> None:
        scores = {"STR": 16, "DEX": 8, "CON": 8, "INT": 8, "WIS": 8, "CHA": 8}
        assert validate_point_buy(scores) is False

    def test_score_below_8_invalid(self) -> None:
        scores = {"STR": 7, "DEX": 8, "CON": 8, "INT": 8, "WIS": 8, "CHA": 8}
        assert validate_point_buy(scores) is False

    def test_typical_adventurer_valid(self) -> None:
        # 15(9)+14(7)+13(5)+12(4)+10(2)+8(0) = 27
        scores = {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8}
        assert validate_point_buy(scores) is True


class TestApplyBackgroundBonuses:
    def test_plus2_plus1_applied(self) -> None:
        scores = {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8}
        result = apply_background_bonuses(scores, {"STR": 2, "CHA": 1})
        assert result["STR"] == 17
        assert result["CHA"] == 9

    def test_other_scores_unchanged(self) -> None:
        scores = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
        result = apply_background_bonuses(scores, {"STR": 1})
        assert result["DEX"] == 10
        assert result["CON"] == 10

    def test_original_dict_unmodified(self) -> None:
        scores = {"STR": 10}
        apply_background_bonuses(scores, {"STR": 2})
        assert scores["STR"] == 10

    def test_exceeding_20_raises(self) -> None:
        scores = {"STR": 20}
        with pytest.raises(ValueError, match="exceed 20"):
            apply_background_bonuses(scores, {"STR": 1})

    def test_exactly_20_is_allowed(self) -> None:
        scores = {"STR": 19}
        result = apply_background_bonuses(scores, {"STR": 1})
        assert result["STR"] == 20

    def test_new_ability_added(self) -> None:
        scores = {"STR": 10}
        result = apply_background_bonuses(scores, {"DEX": 2})
        assert result["DEX"] == 2


class TestProficiencyBonus:
    async def test_level_1_returns_2(self) -> None:
        assert await proficiency_bonus(1) == 2

    async def test_level_4_returns_2(self) -> None:
        assert await proficiency_bonus(4) == 2

    async def test_level_5_returns_3(self) -> None:
        assert await proficiency_bonus(5) == 3

    async def test_level_8_returns_3(self) -> None:
        assert await proficiency_bonus(8) == 3

    async def test_level_9_returns_4(self) -> None:
        assert await proficiency_bonus(9) == 4

    async def test_level_12_returns_4(self) -> None:
        assert await proficiency_bonus(12) == 4

    async def test_level_13_returns_5(self) -> None:
        assert await proficiency_bonus(13) == 5

    async def test_level_16_returns_5(self) -> None:
        assert await proficiency_bonus(16) == 5

    async def test_level_17_returns_6(self) -> None:
        assert await proficiency_bonus(17) == 6

    async def test_level_20_returns_6(self) -> None:
        assert await proficiency_bonus(20) == 6

    async def test_level_0_raises(self) -> None:
        with pytest.raises(ValueError):
            await proficiency_bonus(0)

    async def test_level_21_raises(self) -> None:
        with pytest.raises(ValueError):
            await proficiency_bonus(21)


class TestMaxHpAtLevel1:
    async def test_barbarian_con_plus2_returns_14(self) -> None:
        assert await max_hp_at_level_1("Barbarian", 2) == 14

    async def test_wizard_con_minus1_returns_5(self) -> None:
        assert await max_hp_at_level_1("Wizard", -1) == 5

    async def test_fighter_no_con_returns_10(self) -> None:
        assert await max_hp_at_level_1("Fighter", 0) == 10

    async def test_minimum_hp_is_1(self) -> None:
        # Sorcerer (d6) with Con -5 would be 1, not 0 or negative
        assert await max_hp_at_level_1("Sorcerer", -5) == 1

    async def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await max_hp_at_level_1("Peasant", 0)


class TestHpGainedOnLevelUp:
    async def test_barbarian_fixed_value_with_bonus(self) -> None:
        # Barbarian fixed = 7, Con +2 → 9
        assert await hp_gained_on_level_up("Barbarian", 2) == 9

    async def test_wizard_fixed_value_with_penalty(self) -> None:
        # Wizard fixed = 4, Con -1 → 3
        assert await hp_gained_on_level_up("Wizard", -1) == 3

    async def test_minimum_hp_gained_is_1(self) -> None:
        # Wizard (4) with Con -5 would be -1; should be clamped to 1
        assert await hp_gained_on_level_up("Wizard", -5) == 1

    async def test_use_fixed_true_by_default(self) -> None:
        result = await hp_gained_on_level_up("Cleric", 0)
        assert result == 5  # fixed value for d8 class

    async def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await hp_gained_on_level_up("Peasant", 0)


class TestSpellSlots:
    # Full casters
    async def test_wizard_level_1(self) -> None:
        assert await spell_slots("Wizard", 1) == {1: 2}

    async def test_wizard_level_3(self) -> None:
        assert await spell_slots("Wizard", 3) == {1: 4, 2: 2}

    async def test_wizard_level_20(self) -> None:
        expected = {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1}
        assert await spell_slots("Wizard", 20) == expected

    async def test_cleric_level_1(self) -> None:
        assert await spell_slots("Cleric", 1) == {1: 2}

    async def test_bard_level_5(self) -> None:
        assert await spell_slots("Bard", 5) == {1: 4, 2: 3, 3: 2}

    # Half casters (SRD 5.2.1: slots from level 1)
    async def test_paladin_level_1(self) -> None:
        assert await spell_slots("Paladin", 1) == {1: 2}

    async def test_paladin_level_2(self) -> None:
        assert await spell_slots("Paladin", 2) == {1: 2}

    async def test_ranger_level_1(self) -> None:
        assert await spell_slots("Ranger", 1) == {1: 2}

    async def test_paladin_level_5(self) -> None:
        assert await spell_slots("Paladin", 5) == {1: 4, 2: 2}

    # Warlock pact magic
    async def test_warlock_level_1(self) -> None:
        assert await spell_slots("Warlock", 1) == {1: 1}

    async def test_warlock_level_2(self) -> None:
        assert await spell_slots("Warlock", 2) == {1: 2}

    async def test_warlock_level_5(self) -> None:
        assert await spell_slots("Warlock", 5) == {3: 2}

    async def test_warlock_level_11(self) -> None:
        assert await spell_slots("Warlock", 11) == {5: 3}

    # Non-casters return empty dict
    async def test_fighter_level_5_returns_empty(self) -> None:
        assert await spell_slots("Fighter", 5) == {}

    async def test_barbarian_level_10_returns_empty(self) -> None:
        assert await spell_slots("Barbarian", 10) == {}

    async def test_monk_level_3_returns_empty(self) -> None:
        assert await spell_slots("Monk", 3) == {}

    # Edge cases
    async def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await spell_slots("Peasant", 1)

    async def test_level_0_raises(self) -> None:
        with pytest.raises(ValueError):
            await spell_slots("Wizard", 0)

    async def test_level_21_raises(self) -> None:
        with pytest.raises(ValueError):
            await spell_slots("Wizard", 21)

    async def test_returns_copy_not_reference(self) -> None:
        result = await spell_slots("Wizard", 1)
        result[1] = 99
        assert await spell_slots("Wizard", 1) == {1: 2}


class TestMulticlassSpellSlots:
    async def test_wizard5_fighter5(self) -> None:
        # Wizard is full caster (level 5), Fighter non-caster (0)
        # Combined level = 5, look up _FULL_CASTER_SLOTS[4]
        result = await multiclass_spell_slots({"Wizard": 5, "Fighter": 5})
        assert result == {1: 4, 2: 3, 3: 2}

    async def test_wizard5_paladin4(self) -> None:
        # Wizard 5 (full=5) + Paladin 4 (half=ceil(4/2)=2) = combined 7
        result = await multiclass_spell_slots({"Wizard": 5, "Paladin": 4})
        # Level 7 = {1: 4, 2: 3, 3: 3, 4: 1}
        assert result == {1: 4, 2: 3, 3: 3, 4: 1}

    async def test_paladin2_ranger2(self) -> None:
        # Paladin 2 (ceil(2/2)=1) + Ranger 2 (ceil(2/2)=1) = combined 2
        result = await multiclass_spell_slots({"Paladin": 2, "Ranger": 2})
        # Level 2 = {1: 3}
        assert result == {1: 3}

    async def test_warlock_only(self) -> None:
        # Warlock is separate — pact magic only
        result = await multiclass_spell_slots({"Warlock": 3})
        assert result == {2: 2}

    async def test_wizard3_warlock3(self) -> None:
        # Wizard 3 combined_level=3; Warlock level 3 pact magic = {2: 2}
        # Table level 3 = {1: 4, 2: 2}; warlock adds {2: 2} → {2: 4}
        result = await multiclass_spell_slots({"Wizard": 3, "Warlock": 3})
        assert result[1] == 4
        assert result[2] == 4  # 2 from table + 2 from warlock pact magic

    async def test_fighter_only_returns_empty(self) -> None:
        result = await multiclass_spell_slots({"Fighter": 10})
        assert result == {}

    async def test_half_caster_rounding_up(self) -> None:
        # Paladin 3: ceil(3/2) = 2
        # Paladin 1: ceil(1/2) = 1
        result_3 = await multiclass_spell_slots({"Paladin": 3})
        result_1 = await multiclass_spell_slots({"Paladin": 1})
        # combined_level=2 → {1: 3}; combined_level=1 → {1: 2}
        assert result_3 == {1: 3}
        assert result_1 == {1: 2}

    async def test_invalid_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await multiclass_spell_slots({"Peasant": 5})

    async def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError):
            await multiclass_spell_slots({"Wizard": 21})


class TestLevelForXp:
    async def test_0_xp_returns_level_1(self) -> None:
        assert await level_for_xp(0) == 1

    async def test_299_xp_returns_level_1(self) -> None:
        assert await level_for_xp(299) == 1

    async def test_300_xp_returns_level_2(self) -> None:
        assert await level_for_xp(300) == 2

    async def test_355000_xp_returns_level_20(self) -> None:
        assert await level_for_xp(355000) == 20

    async def test_above_max_xp_returns_level_20(self) -> None:
        assert await level_for_xp(999999) == 20

    async def test_xp_thresholds_all_correct(self) -> None:
        expected_pairs = [
            (0, 1),
            (300, 2),
            (900, 3),
            (2700, 4),
            (6500, 5),
            (14000, 6),
            (23000, 7),
            (34000, 8),
            (48000, 9),
            (64000, 10),
            (85000, 11),
            (100000, 12),
            (120000, 13),
            (140000, 14),
            (165000, 15),
            (195000, 16),
            (225000, 17),
            (265000, 18),
            (305000, 19),
            (355000, 20),
        ]
        for xp, expected_level in expected_pairs:
            assert await level_for_xp(xp) == expected_level, (
                f"Expected level {expected_level} for {xp} XP"
            )

    async def test_one_below_threshold_stays_lower(self) -> None:
        # Just below level 3 threshold (900 - 1 = 899)
        assert await level_for_xp(XP_THRESHOLDS[2] - 1) == 2

    async def test_negative_xp_raises(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            await level_for_xp(-1)


class TestCanMulticlass:
    async def test_barbarian_to_fighter_with_str_13(self) -> None:
        # Barbarian needs STR≥13, Fighter needs STR≥13
        assert await can_multiclass({"Barbarian": 3}, "Fighter", {"STR": 13, "DEX": 10}) is True

    async def test_barbarian_to_wizard_low_int(self) -> None:
        # Wizard needs INT≥13
        assert await can_multiclass({"Barbarian": 3}, "Wizard", {"STR": 15, "INT": 10}) is False

    async def test_wizard_to_fighter_int_13_str_13(self) -> None:
        assert await can_multiclass({"Wizard": 5}, "Fighter", {"INT": 15, "STR": 13}) is True

    async def test_monk_needs_dex_and_wis(self) -> None:
        # Monk requires DEX≥13 AND WIS≥13
        assert await can_multiclass({}, "Monk", {"DEX": 13, "WIS": 13}) is True
        assert await can_multiclass({}, "Monk", {"DEX": 13, "WIS": 12}) is False
        assert await can_multiclass({}, "Monk", {"DEX": 12, "WIS": 13}) is False

    async def test_paladin_needs_str_and_cha(self) -> None:
        assert await can_multiclass({}, "Paladin", {"STR": 13, "CHA": 13}) is True
        assert await can_multiclass({}, "Paladin", {"STR": 13, "CHA": 12}) is False

    async def test_ranger_needs_dex_and_wis(self) -> None:
        assert await can_multiclass({}, "Ranger", {"DEX": 13, "WIS": 13}) is True
        assert await can_multiclass({}, "Ranger", {"DEX": 14, "WIS": 12}) is False

    async def test_current_class_also_checked(self) -> None:
        # Barbarian needs STR≥13; if character has STR 12, they can't even
        # have legally been a Barbarian but we still validate
        assert await can_multiclass({"Barbarian": 3}, "Rogue", {"STR": 12, "DEX": 13}) is False

    async def test_single_class_character(self) -> None:
        assert await can_multiclass({}, "Rogue", {"DEX": 13}) is True

    async def test_unknown_current_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await can_multiclass({"Peasant": 1}, "Fighter", {"STR": 15})

    async def test_unknown_new_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            await can_multiclass({"Fighter": 1}, "Peasant", {"STR": 15})

    async def test_all_primary_abilities_covered(self) -> None:
        # Ensure PRIMARY_ABILITIES covers all 12 SRD classes
        assert set(PRIMARY_ABILITIES.keys()) == {
            "Barbarian",
            "Bard",
            "Cleric",
            "Druid",
            "Fighter",
            "Monk",
            "Paladin",
            "Ranger",
            "Rogue",
            "Sorcerer",
            "Warlock",
            "Wizard",
        }
