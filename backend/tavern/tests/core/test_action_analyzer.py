"""Tests for core/action_analyzer.py — keyword-based action classification."""

from tavern.core.action_analyzer import ActionAnalysis, ActionCategory, analyze_action

# ---------------------------------------------------------------------------
# Spell detection
# ---------------------------------------------------------------------------


def test_spell_cast_keyword():
    result = analyze_action("I cast Fire Bolt at the goblin")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "fire-bolt"


def test_spell_name_without_cast():
    result = analyze_action("Magic Missile at the orc")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "magic-missile"


def test_spell_burning_hands():
    result = analyze_action("I use Burning Hands on the group of skeletons")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "burning-hands"


def test_spell_cure_wounds():
    result = analyze_action("Cast Cure Wounds on the wounded fighter")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "cure-wounds"


def test_spell_hold_person():
    result = analyze_action("Hold Person on the bandit captain")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "hold-person"


def test_spell_index_none_for_unknown_spell():
    result = analyze_action("I cast some weird cantrip")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index is None  # "cantrip" keyword but no known spell name


def test_spell_thunderwave_variant():
    result = analyze_action("thunder wave everything around me")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.spell_index == "thunderwave"


# ---------------------------------------------------------------------------
# Ranged attack detection
# ---------------------------------------------------------------------------


def test_ranged_shoot():
    result = analyze_action("I shoot the bandit with my longbow")
    assert result.category == ActionCategory.RANGED_ATTACK


def test_ranged_throw():
    result = analyze_action("Throw my javelin at the troll")
    assert result.category == ActionCategory.RANGED_ATTACK


def test_ranged_arrow():
    result = analyze_action("Loose an arrow at the fleeing cultist")
    assert result.category == ActionCategory.RANGED_ATTACK


# ---------------------------------------------------------------------------
# Melee attack detection
# ---------------------------------------------------------------------------


def test_melee_attack():
    result = analyze_action("I attack the goblin with my longsword")
    assert result.category == ActionCategory.MELEE_ATTACK


def test_melee_strike():
    result = analyze_action("Strike the skeleton with my warhammer")
    assert result.category == ActionCategory.MELEE_ATTACK


def test_melee_slash():
    result = analyze_action("Slash at the zombie twice")
    assert result.category == ActionCategory.MELEE_ATTACK


def test_melee_smite():
    result = analyze_action("Smite the undead creature")
    assert result.category == ActionCategory.MELEE_ATTACK


# ---------------------------------------------------------------------------
# Ability check detection
# ---------------------------------------------------------------------------


def test_ability_check_perception():
    result = analyze_action("I roll a perception check to look for hidden doors")
    assert result.category == ActionCategory.ABILITY_CHECK
    assert result.ability == "WIS"


def test_ability_check_strength():
    result = analyze_action("I try to break the door with my strength")
    assert result.category == ActionCategory.ABILITY_CHECK
    assert result.ability == "STR"


def test_ability_check_stealth():
    result = analyze_action("Stealth check to sneak past the guard")
    assert result.category == ActionCategory.ABILITY_CHECK
    assert result.ability == "DEX"


def test_ability_check_charisma_persuasion():
    result = analyze_action("I attempt a persuasion check on the merchant")
    assert result.category == ActionCategory.ABILITY_CHECK
    assert result.ability == "CHA"


def test_ability_check_trigger_without_ability_falls_through():
    """'roll' without an ability keyword should not be ABILITY_CHECK."""
    result = analyze_action("I roll out of the way")
    # "roll" triggers ability check path but no ability found → falls through
    assert result.category != ActionCategory.ABILITY_CHECK


# ---------------------------------------------------------------------------
# Interaction detection
# ---------------------------------------------------------------------------


def test_interaction_use():
    result = analyze_action("I use the healing potion")
    assert result.category == ActionCategory.INTERACTION


def test_interaction_open():
    result = analyze_action("Open the chest")
    assert result.category == ActionCategory.INTERACTION


def test_interaction_examine():
    result = analyze_action("Examine the runes on the door")
    assert result.category == ActionCategory.INTERACTION


def test_interaction_search():
    result = analyze_action("Search the room for traps")
    assert result.category == ActionCategory.INTERACTION


# ---------------------------------------------------------------------------
# Movement detection
# ---------------------------------------------------------------------------


def test_movement_move():
    result = analyze_action("Move behind the pillar")
    assert result.category == ActionCategory.MOVEMENT


def test_movement_dash():
    result = analyze_action("Dash toward the exit")
    assert result.category == ActionCategory.MOVEMENT


def test_movement_flee():
    result = analyze_action("Flee from the dragon")
    assert result.category == ActionCategory.MOVEMENT


def test_movement_approach():
    result = analyze_action("Approach the altar carefully")
    assert result.category == ActionCategory.MOVEMENT


# ---------------------------------------------------------------------------
# UNKNOWN fallback (short ambiguous text)
# ---------------------------------------------------------------------------


def test_unknown_very_short():
    result = analyze_action("wait")
    assert result.category == ActionCategory.UNKNOWN


def test_unknown_ambiguous_short():
    result = analyze_action("I stand guard")
    assert result.category == ActionCategory.UNKNOWN


# ---------------------------------------------------------------------------
# NARRATIVE fallback (long descriptive text, no keywords)
# ---------------------------------------------------------------------------


def test_narrative_long_description():
    result = analyze_action(
        "I watch the shadows dance across the cavern wall and consider what lies ahead"
    )
    assert result.category == ActionCategory.NARRATIVE


# ---------------------------------------------------------------------------
# Target extraction
# ---------------------------------------------------------------------------


def test_target_extracted_from_spell():
    result = analyze_action("Cast Fire Bolt at the goblin shaman")
    assert result.category == ActionCategory.CAST_SPELL
    assert result.target_name is not None
    assert "goblin" in result.target_name


def test_target_extracted_from_melee():
    result = analyze_action("Attack the orc warrior")
    assert result.category == ActionCategory.MELEE_ATTACK
    assert result.target_name is not None
    assert "orc" in result.target_name


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


def test_returns_action_analysis_instance():
    result = analyze_action("Attack the goblin")
    assert isinstance(result, ActionAnalysis)


def test_raw_action_preserved():
    text = "I attack the goblin with my sword"
    result = analyze_action(text)
    assert result.raw_action == text
