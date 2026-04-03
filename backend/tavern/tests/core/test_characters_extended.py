"""Extended tests for SRD 5.2.1 character mechanics.

Every test in this file asserts a specific value from a named PDF table or
section.  Comments cite the exact source so failures can be traced directly
to the document.
"""

import pytest

from tavern.core.characters import (
    ALL_FEATS,
    BACKGROUNDS,
    CLASS_CANTRIPS_KNOWN,
    CLASS_FEATURES,
    CLASS_PROFICIENCIES,
    CLASS_SPELLS_PREPARED,
    CLASS_STARTING_EQUIPMENT,
    EPIC_BOON_FEATS,
    FIGHTING_STYLE_FEATS,
    GENERAL_FEATS,
    MULTICLASS_PROFICIENCY_GAINS,
    ORIGIN_FEATS,
    SPECIES_TRAITS,
    all_class_features,
    background_ability_options,
    background_data,
    cantrips_known,
    class_features_at_level,
    class_proficiencies,
    feat_data,
    multiclass_proficiency_gains,
    species_traits,
    spells_prepared,
    starting_equipment,
    validate_background_ability_bonus,
)

# ---------------------------------------------------------------------------
# Class feature tables
# ---------------------------------------------------------------------------


class TestClassFeaturesAtLevel:
    def test_barbarian_level_1(self) -> None:
        # SRD p.28: Rage, Unarmored Defense, Weapon Mastery
        feats = class_features_at_level("Barbarian", 1)
        assert "Rage" in feats
        assert "Unarmored Defense" in feats
        assert "Weapon Mastery" in feats

    def test_barbarian_level_5(self) -> None:
        feats = class_features_at_level("Barbarian", 5)
        assert "Extra Attack" in feats
        assert "Fast Movement" in feats

    def test_barbarian_level_20(self) -> None:
        feats = class_features_at_level("Barbarian", 20)
        assert "Primal Champion" in feats

    def test_fighter_level_1(self) -> None:
        # SRD p.46: Fighting Style, Second Wind, Weapon Mastery
        feats = class_features_at_level("Fighter", 1)
        assert "Fighting Style" in feats
        assert "Second Wind" in feats

    def test_fighter_level_2_action_surge(self) -> None:
        feats = class_features_at_level("Fighter", 2)
        assert any("Action Surge" in f for f in feats)

    def test_wizard_level_1(self) -> None:
        # SRD p.77: Spellcasting, Ritual Adept, Arcane Recovery
        feats = class_features_at_level("Wizard", 1)
        assert "Spellcasting" in feats
        assert "Ritual Adept" in feats
        assert "Arcane Recovery" in feats

    def test_wizard_level_18_spell_mastery(self) -> None:
        feats = class_features_at_level("Wizard", 18)
        assert "Spell Mastery" in feats

    def test_wizard_level_20_signature_spells(self) -> None:
        feats = class_features_at_level("Wizard", 20)
        assert "Signature Spells" in feats

    def test_rogue_level_1(self) -> None:
        # SRD p.63: Expertise, Sneak Attack, Thieves' Cant, Weapon Mastery
        feats = class_features_at_level("Rogue", 1)
        assert "Expertise" in feats
        assert "Sneak Attack" in feats
        assert "Thieves' Cant" in feats

    def test_paladin_level_6_aura_of_protection(self) -> None:
        feats = class_features_at_level("Paladin", 6)
        assert "Aura of Protection" in feats

    def test_paladin_level_10_aura_of_courage(self) -> None:
        feats = class_features_at_level("Paladin", 10)
        assert "Aura of Courage" in feats

    def test_monk_level_2_monks_focus(self) -> None:
        feats = class_features_at_level("Monk", 2)
        assert "Monk's Focus" in feats

    def test_druid_level_2_wild_shape(self) -> None:
        feats = class_features_at_level("Druid", 2)
        assert "Wild Shape" in feats

    def test_every_class_has_level_19_epic_boon(self) -> None:
        # SRD: all 12 classes gain Epic Boon at level 19
        for cls in CLASS_FEATURES:
            feats = class_features_at_level(cls, 19)
            assert "Epic Boon" in feats, f"{cls} missing Epic Boon at level 19"

    def test_every_class_has_subclass_at_level_3(self) -> None:
        # All 12 classes gain subclass at level 3
        for cls in CLASS_FEATURES:
            feats = class_features_at_level(cls, 3)
            assert any("Subclass" in f for f in feats), (
                f"{cls} missing subclass feature at level 3"
            )

    def test_empty_list_for_level_with_no_features(self) -> None:
        # Wizard level 7: no new class features
        assert class_features_at_level("Wizard", 7) == []

    def test_returns_copy_not_reference(self) -> None:
        original = class_features_at_level("Wizard", 1)
        original.append("TAMPERED")
        assert "TAMPERED" not in class_features_at_level("Wizard", 1)

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            class_features_at_level("Peasant", 1)

    def test_level_0_raises(self) -> None:
        with pytest.raises(ValueError):
            class_features_at_level("Wizard", 0)


class TestAllClassFeatures:
    def test_wizard_up_to_3(self) -> None:
        features = all_class_features("Wizard", 3)
        assert set(features.keys()) == {1, 2, 3}
        assert "Spellcasting" in features[1]
        assert "Scholar" in features[2]
        assert "Wizard Subclass" in features[3]

    def test_all_12_classes_have_20_level_entries(self) -> None:
        for cls in CLASS_FEATURES:
            features = all_class_features(cls, 20)
            assert len(features) == 20, f"{cls} should have 20 levels"

    def test_abi_score_improvements_count(self) -> None:
        # Fighter gets Ability Score Improvement at levels 4,6,8,12,14,16 = 6 times
        fighter_features = all_class_features("Fighter", 20)
        asi_levels = [
            lvl for lvl, feats in fighter_features.items() if "Ability Score Improvement" in feats
        ]
        assert len(asi_levels) == 6
        assert 4 in asi_levels
        assert 6 in asi_levels


# ---------------------------------------------------------------------------
# Cantrips known
# ---------------------------------------------------------------------------


class TestCantripsKnown:
    # Wizard (SRD p.77 feature table)
    def test_wizard_level_1_knows_3(self) -> None:
        assert cantrips_known("Wizard", 1) == 3

    def test_wizard_level_4_knows_4(self) -> None:
        assert cantrips_known("Wizard", 4) == 4

    def test_wizard_level_10_knows_5(self) -> None:
        assert cantrips_known("Wizard", 10) == 5

    def test_wizard_level_20_knows_5(self) -> None:
        assert cantrips_known("Wizard", 20) == 5

    # Bard (SRD p.31)
    def test_bard_level_1_knows_2(self) -> None:
        assert cantrips_known("Bard", 1) == 2

    def test_bard_level_4_knows_3(self) -> None:
        assert cantrips_known("Bard", 4) == 3

    def test_bard_level_10_knows_4(self) -> None:
        assert cantrips_known("Bard", 10) == 4

    # Cleric (SRD p.37)
    def test_cleric_level_1_knows_3(self) -> None:
        assert cantrips_known("Cleric", 1) == 3

    def test_cleric_level_10_knows_5(self) -> None:
        assert cantrips_known("Cleric", 10) == 5

    # Sorcerer (SRD p.67)
    def test_sorcerer_level_1_knows_4(self) -> None:
        assert cantrips_known("Sorcerer", 1) == 4

    def test_sorcerer_level_4_knows_5(self) -> None:
        assert cantrips_known("Sorcerer", 4) == 5

    def test_sorcerer_level_10_knows_6(self) -> None:
        assert cantrips_known("Sorcerer", 10) == 6

    # Non-cantrip classes return 0
    def test_barbarian_returns_0(self) -> None:
        assert cantrips_known("Barbarian", 10) == 0

    def test_paladin_returns_0(self) -> None:
        assert cantrips_known("Paladin", 10) == 0

    def test_ranger_returns_0(self) -> None:
        assert cantrips_known("Ranger", 10) == 0

    def test_fighter_returns_0(self) -> None:
        assert cantrips_known("Fighter", 20) == 0

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError):
            cantrips_known("Peasant", 1)


# ---------------------------------------------------------------------------
# Spells prepared
# ---------------------------------------------------------------------------


class TestSpellsPrepared:
    # Wizard (SRD p.77 feature table)
    def test_wizard_level_1(self) -> None:
        assert spells_prepared("Wizard", 1) == 4

    def test_wizard_level_3(self) -> None:
        assert spells_prepared("Wizard", 3) == 6

    def test_wizard_level_5(self) -> None:
        assert spells_prepared("Wizard", 5) == 9

    def test_wizard_level_16(self) -> None:
        # SRD table: 21 (not 20)
        assert spells_prepared("Wizard", 16) == 21

    def test_wizard_level_20(self) -> None:
        assert spells_prepared("Wizard", 20) == 25

    # Cleric (SRD p.37)
    def test_cleric_level_1(self) -> None:
        assert spells_prepared("Cleric", 1) == 4

    def test_cleric_level_5(self) -> None:
        assert spells_prepared("Cleric", 5) == 9

    def test_cleric_level_20(self) -> None:
        assert spells_prepared("Cleric", 20) == 22

    # Paladin (SRD p.55)
    def test_paladin_level_1(self) -> None:
        assert spells_prepared("Paladin", 1) == 2

    def test_paladin_level_5(self) -> None:
        assert spells_prepared("Paladin", 5) == 6

    def test_paladin_level_20(self) -> None:
        assert spells_prepared("Paladin", 20) == 15

    # Ranger (SRD p.59)
    def test_ranger_level_1(self) -> None:
        assert spells_prepared("Ranger", 1) == 2

    def test_ranger_level_20(self) -> None:
        assert spells_prepared("Ranger", 20) == 15

    # Sorcerer (SRD p.67)
    def test_sorcerer_level_1(self) -> None:
        assert spells_prepared("Sorcerer", 1) == 2

    def test_sorcerer_level_2(self) -> None:
        assert spells_prepared("Sorcerer", 2) == 4

    # Warlock (SRD p.71)
    def test_warlock_level_1(self) -> None:
        assert spells_prepared("Warlock", 1) == 2

    def test_warlock_level_20(self) -> None:
        assert spells_prepared("Warlock", 20) == 15

    # Non-casters return 0
    def test_barbarian_returns_0(self) -> None:
        assert spells_prepared("Barbarian", 10) == 0

    def test_fighter_returns_0(self) -> None:
        assert spells_prepared("Fighter", 20) == 0

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError):
            spells_prepared("Peasant", 1)


# ---------------------------------------------------------------------------
# Class proficiencies
# ---------------------------------------------------------------------------


class TestClassProficiencies:
    def test_barbarian_saving_throws(self) -> None:
        # SRD p.29
        profs = class_proficiencies("Barbarian")
        assert set(profs["saving_throws"]) == {"STR", "CON"}

    def test_barbarian_armor(self) -> None:
        profs = class_proficiencies("Barbarian")
        assert "Light Armor" in profs["armor"]
        assert "Medium Armor" in profs["armor"]
        assert "Shields" in profs["armor"]

    def test_wizard_no_armor(self) -> None:
        # SRD p.77: "None"
        profs = class_proficiencies("Wizard")
        assert profs["armor"] == []

    def test_wizard_saving_throws(self) -> None:
        profs = class_proficiencies("Wizard")
        assert set(profs["saving_throws"]) == {"INT", "WIS"}

    def test_rogue_skills_choose_4(self) -> None:
        # SRD p.63: choose 4 skills
        profs = class_proficiencies("Rogue")
        assert profs["skills_choose"] == 4

    def test_ranger_skills_choose_3(self) -> None:
        profs = class_proficiencies("Ranger")
        assert profs["skills_choose"] == 3

    def test_bard_skills_from_any(self) -> None:
        profs = class_proficiencies("Bard")
        assert profs["skills_from"] == ["any"]

    def test_fighter_saves_str_con(self) -> None:
        profs = class_proficiencies("Fighter")
        assert set(profs["saving_throws"]) == {"STR", "CON"}

    def test_fighter_has_heavy_armor(self) -> None:
        profs = class_proficiencies("Fighter")
        assert "Heavy Armor" in profs["armor"]

    def test_cleric_simple_weapons_only(self) -> None:
        profs = class_proficiencies("Cleric")
        assert "Simple Weapons" in profs["weapons"]
        assert "Martial Weapons" not in profs["weapons"]

    def test_druid_herbalism_kit(self) -> None:
        profs = class_proficiencies("Druid")
        assert any("Herbalism" in t for t in profs["tools"])

    def test_rogue_thieves_tools(self) -> None:
        profs = class_proficiencies("Rogue")
        assert any("Thieves" in t for t in profs["tools"])

    def test_monk_no_armor(self) -> None:
        profs = class_proficiencies("Monk")
        assert profs["armor"] == []

    def test_all_12_classes_have_proficiency_data(self) -> None:
        for cls in CLASS_PROFICIENCIES:
            p = class_proficiencies(cls)
            assert "saving_throws" in p
            assert "skills_choose" in p
            assert "armor" in p
            assert "weapons" in p

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            class_proficiencies("Peasant")


# ---------------------------------------------------------------------------
# Multiclass proficiency gains
# ---------------------------------------------------------------------------


class TestMulticlassProficiencyGains:
    def test_barbarian_gains_medium_armor_and_martial(self) -> None:
        # SRD p.25
        gains = multiclass_proficiency_gains("Barbarian")
        assert "Medium Armor" in gains["armor"]
        assert "Martial Weapons" in gains["weapons"]

    def test_wizard_gains_nothing(self) -> None:
        gains = multiclass_proficiency_gains("Wizard")
        assert gains["armor"] == []
        assert gains["weapons"] == []
        assert gains["tools"] == []
        assert gains["skills_choose"] == 0

    def test_bard_gains_light_armor_and_1_skill(self) -> None:
        gains = multiclass_proficiency_gains("Bard")
        assert "Light Armor" in gains["armor"]
        assert gains["skills_choose"] == 1

    def test_rogue_gains_light_armor_and_thieves_tools(self) -> None:
        gains = multiclass_proficiency_gains("Rogue")
        assert "Light Armor" in gains["armor"]
        assert any("Thieves" in t for t in gains["tools"])
        assert gains["skills_choose"] == 1

    def test_fighter_gains_light_medium_shields_martial(self) -> None:
        gains = multiclass_proficiency_gains("Fighter")
        assert "Light Armor" in gains["armor"]
        assert "Medium Armor" in gains["armor"]
        assert "Shields" in gains["armor"]
        assert "Martial Weapons" in gains["weapons"]

    def test_ranger_gains_1_skill_from_ranger_list(self) -> None:
        gains = multiclass_proficiency_gains("Ranger")
        assert gains["skills_choose"] == 1
        assert "Survival" in gains["skills_from"]

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            multiclass_proficiency_gains("Peasant")


# ---------------------------------------------------------------------------
# Starting equipment
# ---------------------------------------------------------------------------


class TestStartingEquipment:
    def test_wizard_option_a_has_spellbook(self) -> None:
        # SRD p.77
        equip = starting_equipment("Wizard")
        assert "Spellbook" in equip["option_a"]

    def test_wizard_option_b_is_55_gp(self) -> None:
        equip = starting_equipment("Wizard")
        assert "55 GP" in equip["option_b"]

    def test_rogue_option_a_has_thieves_tools(self) -> None:
        equip = starting_equipment("Rogue")
        assert any("Thieves" in item for item in equip["option_a"])

    def test_fighter_has_three_options(self) -> None:
        # SRD p.46: Fighter has option_a, option_b, option_c
        equip = starting_equipment("Fighter")
        assert "option_a" in equip
        assert "option_b" in equip
        assert "option_c" in equip
        assert "155 GP" in equip["option_c"]

    def test_barbarian_option_a_has_greataxe(self) -> None:
        equip = starting_equipment("Barbarian")
        assert "Greataxe" in equip["option_a"]

    def test_cleric_option_b_is_110_gp(self) -> None:
        equip = starting_equipment("Cleric")
        assert "110 GP" in equip["option_b"]

    def test_paladin_option_a_has_chain_mail(self) -> None:
        equip = starting_equipment("Paladin")
        assert "Chain Mail" in equip["option_a"]

    def test_all_12_classes_have_equipment(self) -> None:
        for cls in CLASS_STARTING_EQUIPMENT:
            equip = starting_equipment(cls)
            assert "option_a" in equip
            assert "option_b" in equip

    def test_unknown_class_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown class"):
            starting_equipment("Peasant")


# ---------------------------------------------------------------------------
# Species traits
# ---------------------------------------------------------------------------


class TestSpeciesTraits:
    def test_all_9_species_present(self) -> None:
        expected = {
            "Dragonborn",
            "Dwarf",
            "Elf",
            "Gnome",
            "Goliath",
            "Halfling",
            "Human",
            "Orc",
            "Tiefling",
        }
        assert set(SPECIES_TRAITS.keys()) == expected

    def test_dwarf_darkvision_120(self) -> None:
        # SRD p.84
        traits = species_traits("Dwarf")
        assert traits["traits"]["Darkvision"]["range_ft"] == 120

    def test_elf_darkvision_60(self) -> None:
        traits = species_traits("Elf")
        assert traits["traits"]["Darkvision"]["range_ft"] == 60

    def test_orc_darkvision_120(self) -> None:
        traits = species_traits("Orc")
        assert traits["traits"]["Darkvision"]["range_ft"] == 120

    def test_dragonborn_darkvision_60(self) -> None:
        traits = species_traits("Dragonborn")
        assert traits["traits"]["Darkvision"]["range_ft"] == 60

    def test_gnome_darkvision_60(self) -> None:
        traits = species_traits("Gnome")
        assert traits["traits"]["Darkvision"]["range_ft"] == 60

    def test_halfling_no_darkvision(self) -> None:
        traits = species_traits("Halfling")
        assert "Darkvision" not in traits["traits"]

    def test_human_no_darkvision(self) -> None:
        traits = species_traits("Human")
        assert "Darkvision" not in traits["traits"]

    def test_goliath_speed_35(self) -> None:
        # SRD p.85: Goliath speed is 35 ft
        traits = species_traits("Goliath")
        assert traits["speed"] == 35

    def test_standard_speed_30(self) -> None:
        for species in ["Dwarf", "Elf", "Gnome", "Halfling", "Human", "Orc", "Tiefling"]:
            assert species_traits(species)["speed"] == 30

    def test_gnome_is_small(self) -> None:
        traits = species_traits("Gnome")
        assert traits["size"] == "Small"

    def test_halfling_is_small(self) -> None:
        traits = species_traits("Halfling")
        assert traits["size"] == "Small"

    def test_dwarf_dwarven_toughness(self) -> None:
        traits = species_traits("Dwarf")
        assert "Dwarven Toughness" in traits["traits"]

    def test_dwarf_poison_resistance(self) -> None:
        traits = species_traits("Dwarf")
        resistance = traits["traits"]["Dwarven Resilience"]["resistance"]
        assert any("Poison" in r for r in resistance)

    def test_elf_fey_ancestry(self) -> None:
        traits = species_traits("Elf")
        assert "Fey Ancestry" in traits["traits"]

    def test_elf_lineages_present(self) -> None:
        traits = species_traits("Elf")
        lineages = traits["traits"]["Elven Lineage"]["lineages"]
        assert "Drow" in lineages
        assert "High Elf" in lineages
        assert "Wood Elf" in lineages

    def test_wood_elf_speed_bonus(self) -> None:
        traits = species_traits("Elf")
        wood_elf = traits["traits"]["Elven Lineage"]["lineages"]["Wood Elf"]
        assert wood_elf["speed_bonus_ft"] == 5

    def test_drow_darkvision_120(self) -> None:
        traits = species_traits("Elf")
        drow = traits["traits"]["Elven Lineage"]["lineages"]["Drow"]
        assert drow["darkvision_ft"] == 120

    def test_gnome_lineages(self) -> None:
        traits = species_traits("Gnome")
        lineages = traits["traits"]["Gnomish Lineage"]["lineages"]
        assert "Forest Gnome" in lineages
        assert "Rock Gnome" in lineages

    def test_tiefling_legacies(self) -> None:
        traits = species_traits("Tiefling")
        legacies = traits["traits"]["Fiendish Legacy"]["legacies"]
        assert "Abyssal" in legacies
        assert "Chthonic" in legacies
        assert "Infernal" in legacies

    def test_tiefling_infernal_fire_resistance(self) -> None:
        traits = species_traits("Tiefling")
        infernal = traits["traits"]["Fiendish Legacy"]["legacies"]["Infernal"]
        assert "Fire" in infernal["resistance"]

    def test_dragonborn_10_dragon_types(self) -> None:
        traits = species_traits("Dragonborn")
        dragon_types = traits["traits"]["Draconic Ancestry"]["dragon_types"]
        assert len(dragon_types) == 10

    def test_orc_relentless_endurance(self) -> None:
        traits = species_traits("Orc")
        assert "Relentless Endurance" in traits["traits"]

    def test_halfling_luck(self) -> None:
        traits = species_traits("Halfling")
        assert "Luck" in traits["traits"]

    def test_human_versatile_grants_feat(self) -> None:
        traits = species_traits("Human")
        description = traits["traits"]["Versatile"]["description"]
        assert "feat" in description.lower()

    def test_unknown_species_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown species"):
            species_traits("Dragon")


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------


class TestBackgroundData:
    def test_all_4_backgrounds_present(self) -> None:
        assert set(BACKGROUNDS.keys()) == {"Acolyte", "Criminal", "Sage", "Soldier"}

    def test_acolyte_abilities(self) -> None:
        # SRD p.83
        bg = background_data("Acolyte")
        assert set(bg["ability_scores_eligible"]) == {"INT", "WIS", "CHA"}

    def test_acolyte_origin_feat(self) -> None:
        bg = background_data("Acolyte")
        assert bg["origin_feat"] == "Magic Initiate (Cleric)"

    def test_acolyte_skills(self) -> None:
        bg = background_data("Acolyte")
        assert set(bg["skill_proficiencies"]) == {"Insight", "Religion"}

    def test_acolyte_tool(self) -> None:
        bg = background_data("Acolyte")
        assert "Calligrapher" in bg["tool_proficiency"]

    def test_criminal_abilities(self) -> None:
        bg = background_data("Criminal")
        assert set(bg["ability_scores_eligible"]) == {"DEX", "CON", "INT"}

    def test_criminal_origin_feat(self) -> None:
        bg = background_data("Criminal")
        assert bg["origin_feat"] == "Alert"

    def test_criminal_skills(self) -> None:
        bg = background_data("Criminal")
        assert set(bg["skill_proficiencies"]) == {"Sleight of Hand", "Stealth"}

    def test_sage_abilities(self) -> None:
        bg = background_data("Sage")
        assert set(bg["ability_scores_eligible"]) == {"CON", "INT", "WIS"}

    def test_sage_origin_feat(self) -> None:
        bg = background_data("Sage")
        assert bg["origin_feat"] == "Magic Initiate (Wizard)"

    def test_sage_skills(self) -> None:
        bg = background_data("Sage")
        assert set(bg["skill_proficiencies"]) == {"Arcana", "History"}

    def test_soldier_abilities(self) -> None:
        bg = background_data("Soldier")
        assert set(bg["ability_scores_eligible"]) == {"STR", "DEX", "CON"}

    def test_soldier_origin_feat(self) -> None:
        bg = background_data("Soldier")
        assert bg["origin_feat"] == "Savage Attacker"

    def test_soldier_skills(self) -> None:
        bg = background_data("Soldier")
        assert set(bg["skill_proficiencies"]) == {"Athletics", "Intimidation"}

    def test_acolyte_equipment_option_b_is_50_gp(self) -> None:
        bg = background_data("Acolyte")
        assert "50 GP" in bg["starting_equipment"]["option_b"]

    def test_unknown_background_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown background"):
            background_data("Hermit")


class TestBackgroundAbilityOptions:
    def test_acolyte_has_7_options(self) -> None:
        # 6 permutations of +2/+1 + 1 triple +1 = 7
        options = background_ability_options("Acolyte")
        assert len(options) == 7

    def test_acolyte_includes_triple_plus1(self) -> None:
        options = background_ability_options("Acolyte")
        assert {"INT": 1, "WIS": 1, "CHA": 1} in options

    def test_acolyte_includes_int2_wis1(self) -> None:
        options = background_ability_options("Acolyte")
        assert {"INT": 2, "WIS": 1} in options

    def test_all_options_sum_to_3(self) -> None:
        for bg_name in BACKGROUNDS:
            for option in background_ability_options(bg_name):
                assert sum(option.values()) == 3


class TestValidateBackgroundAbilityBonus:
    def test_valid_plus2_plus1(self) -> None:
        assert validate_background_ability_bonus("Acolyte", {"INT": 2, "WIS": 1}) is True

    def test_valid_triple_plus1(self) -> None:
        assert validate_background_ability_bonus("Acolyte", {"INT": 1, "WIS": 1, "CHA": 1}) is True

    def test_wrong_ability_invalid(self) -> None:
        # STR is not eligible for Acolyte (INT, WIS, CHA)
        assert validate_background_ability_bonus("Acolyte", {"STR": 2, "WIS": 1}) is False

    def test_wrong_total_invalid(self) -> None:
        assert validate_background_ability_bonus("Acolyte", {"INT": 3}) is False

    def test_three_twos_invalid(self) -> None:
        assert (
            validate_background_ability_bonus("Acolyte", {"INT": 2, "WIS": 2, "CHA": 2}) is False
        )

    def test_unknown_background_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown background"):
            validate_background_ability_bonus("Hermit", {"INT": 2, "WIS": 1})


# ---------------------------------------------------------------------------
# Feats
# ---------------------------------------------------------------------------


class TestFeatData:
    def test_alert_is_origin_feat(self) -> None:
        feat = feat_data("Alert")
        assert feat["category"] == "Origin"

    def test_alert_not_repeatable(self) -> None:
        feat = feat_data("Alert")
        assert feat["repeatable"] is False

    def test_magic_initiate_cleric_is_origin(self) -> None:
        feat = feat_data("Magic Initiate (Cleric)")
        assert feat["category"] == "Origin"
        assert feat["spell_list"] == "Cleric"

    def test_magic_initiate_cleric_is_repeatable(self) -> None:
        feat = feat_data("Magic Initiate (Cleric)")
        assert feat["repeatable"] is True

    def test_savage_attacker_is_origin(self) -> None:
        feat = feat_data("Savage Attacker")
        assert feat["category"] == "Origin"

    def test_skilled_is_repeatable_origin(self) -> None:
        feat = feat_data("Skilled")
        assert feat["category"] == "Origin"
        assert feat["repeatable"] is True

    def test_ability_score_improvement_is_general(self) -> None:
        feat = feat_data("Ability Score Improvement")
        assert feat["category"] == "General"

    def test_archery_is_fighting_style(self) -> None:
        feat = feat_data("Archery")
        assert feat["category"] == "Fighting Style"

    def test_boon_of_truesight_is_epic_boon(self) -> None:
        feat = feat_data("Boon of Truesight")
        assert feat["category"] == "Epic Boon"

    def test_all_epic_boons_have_level_19_prerequisite(self) -> None:
        for name, feat in EPIC_BOON_FEATS.items():
            assert "19" in feat["prerequisite"], f"{name} should require level 19+"

    def test_all_origin_feats_have_no_prerequisite(self) -> None:
        for name, feat in ORIGIN_FEATS.items():
            assert feat["prerequisite"] is None, f"{name} should have no prerequisite"

    def test_origin_feats_count(self) -> None:
        # SRD has 6 origin feats: Alert, Magic Initiate ×3, Savage Attacker, Skilled
        assert len(ORIGIN_FEATS) == 6

    def test_fighting_style_feats_count(self) -> None:
        # SRD: Archery, Defense, Great Weapon Fighting, Two-Weapon Fighting
        assert len(FIGHTING_STYLE_FEATS) == 4

    def test_epic_boon_feats_count(self) -> None:
        # SRD has 7 Epic Boon feats
        assert len(EPIC_BOON_FEATS) == 7

    def test_all_feats_lookup_contains_all_categories(self) -> None:
        for name in ORIGIN_FEATS:
            assert name in ALL_FEATS
        for name in GENERAL_FEATS:
            assert name in ALL_FEATS
        for name in FIGHTING_STYLE_FEATS:
            assert name in ALL_FEATS
        for name in EPIC_BOON_FEATS:
            assert name in ALL_FEATS

    def test_unknown_feat_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown feat"):
            feat_data("Dragon Breath")


# ---------------------------------------------------------------------------
# Data completeness / structural integrity
# ---------------------------------------------------------------------------


class TestDataCompleteness:
    def test_class_features_covers_all_12_classes(self) -> None:
        expected = {
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
        assert set(CLASS_FEATURES.keys()) == expected

    def test_class_features_each_class_has_20_levels(self) -> None:
        for cls, table in CLASS_FEATURES.items():
            assert set(table.keys()) == set(range(1, 21)), (
                f"{cls} feature table must have exactly levels 1–20"
            )

    def test_class_proficiencies_covers_all_12_classes(self) -> None:
        assert set(CLASS_PROFICIENCIES.keys()) == set(CLASS_FEATURES.keys())

    def test_multiclass_gains_covers_all_12_classes(self) -> None:
        assert set(MULTICLASS_PROFICIENCY_GAINS.keys()) == set(CLASS_FEATURES.keys())

    def test_starting_equipment_covers_all_12_classes(self) -> None:
        assert set(CLASS_STARTING_EQUIPMENT.keys()) == set(CLASS_FEATURES.keys())

    def test_cantrips_known_table_has_20_entries(self) -> None:
        for cls, table in CLASS_CANTRIPS_KNOWN.items():
            assert len(table) == 20, f"{cls} cantrips table must have 20 entries"

    def test_spells_prepared_table_has_20_entries(self) -> None:
        for cls, table in CLASS_SPELLS_PREPARED.items():
            assert len(table) == 20, f"{cls} spells prepared table must have 20 entries"

    def test_spells_prepared_monotonically_nondecreasing(self) -> None:
        for cls, table in CLASS_SPELLS_PREPARED.items():
            for i in range(len(table) - 1):
                assert table[i] <= table[i + 1], (
                    f"{cls} prepared spells must not decrease: "
                    f"level {i + 1}={table[i]} > level {i + 2}={table[i + 1]}"
                )

    def test_cantrips_known_monotonically_nondecreasing(self) -> None:
        for cls, table in CLASS_CANTRIPS_KNOWN.items():
            for i in range(len(table) - 1):
                assert table[i] <= table[i + 1], f"{cls} cantrips known must not decrease"

    def test_species_traits_has_9_species(self) -> None:
        assert len(SPECIES_TRAITS) == 9

    def test_each_species_has_required_keys(self) -> None:
        required = {"creature_type", "size", "speed", "traits"}
        for species, data in SPECIES_TRAITS.items():
            assert required.issubset(data.keys()), (
                f"{species} missing keys: {required - set(data.keys())}"
            )

    def test_backgrounds_has_4_entries(self) -> None:
        assert len(BACKGROUNDS) == 4

    def test_each_background_has_required_keys(self) -> None:
        required = {
            "ability_scores_eligible",
            "origin_feat",
            "skill_proficiencies",
            "tool_proficiency",
            "starting_equipment",
        }
        for bg_name, data in BACKGROUNDS.items():
            assert required.issubset(data.keys()), (
                f"{bg_name} missing keys: {required - set(data.keys())}"
            )

    def test_each_background_has_exactly_3_eligible_abilities(self) -> None:
        for bg_name, data in BACKGROUNDS.items():
            assert len(data["ability_scores_eligible"]) == 3, (
                f"{bg_name} must list exactly 3 eligible abilities"
            )

    def test_background_origin_feats_exist_in_origin_feats(self) -> None:
        for bg_name, data in BACKGROUNDS.items():
            feat_name = data["origin_feat"]
            assert feat_name in ORIGIN_FEATS, (
                f"Background {bg_name} references unknown feat {feat_name!r}"
            )
