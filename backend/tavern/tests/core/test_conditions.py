"""Tests for conditions.py — all SRD 5.2.1 conditions.

Every test references the SRD 5.2.1 section it validates.
All conditions are from the Rules Glossary (pp. 177-191).
"""

import pytest

from tavern.core.conditions import (
    ActiveCondition,
    ConditionName,
    DurationKind,
    ability_check_modifiers,
    attack_roll_modifiers,
    attacks_against_modifiers,
    can_act,
    concentration_is_broken,
    effective_conditions,
    effective_speed,
    initiative_roll_modifiers,
    saving_throw_modifiers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cond(name: ConditionName) -> list[ActiveCondition]:
    return [ActiveCondition.indefinite(name)]


def conds(*names: ConditionName) -> list[ActiveCondition]:
    return [ActiveCondition.indefinite(n) for n in names]


# ===========================================================================
# ActiveCondition construction
# ===========================================================================


class TestActiveConditionConstruction:
    def test_indefinite(self) -> None:
        c = ActiveCondition.indefinite(ConditionName.BLINDED)
        assert c.name == ConditionName.BLINDED
        assert c.duration_kind == DurationKind.INDEFINITE
        assert c.remaining_rounds is None

    def test_for_rounds(self) -> None:
        c = ActiveCondition.for_rounds(ConditionName.FRIGHTENED, 3)
        assert c.duration_kind == DurationKind.ROUNDS
        assert c.remaining_rounds == 3

    def test_for_rounds_invalid(self) -> None:
        with pytest.raises(ValueError):
            ActiveCondition.for_rounds(ConditionName.FRIGHTENED, 0)

    def test_exhaustion_level(self) -> None:
        c = ActiveCondition.exhaustion(2)
        assert c.name == ConditionName.EXHAUSTION
        assert c.exhaustion_level == 2

    def test_exhaustion_invalid_level(self) -> None:
        with pytest.raises(ValueError):
            ActiveCondition.exhaustion(0)
        with pytest.raises(ValueError):
            ActiveCondition.exhaustion(7)

    def test_decrement_round_indefinite(self) -> None:
        c = ActiveCondition.indefinite(ConditionName.BLINDED)
        assert c.decrement_round() is c  # unchanged

    def test_decrement_round_expires(self) -> None:
        c = ActiveCondition.for_rounds(ConditionName.STUNNED, 1)
        assert c.decrement_round() is None

    def test_decrement_round_decrements(self) -> None:
        c = ActiveCondition.for_rounds(ConditionName.STUNNED, 3)
        c2 = c.decrement_round()
        assert c2 is not None
        assert c2.remaining_rounds == 2


# ===========================================================================
# Condition interactions: effective_conditions
# ===========================================================================


class TestEffectiveConditions:
    def test_paralyzed_implies_incapacitated(self) -> None:
        """SRD p.186: Paralyzed → Incapacitated."""
        eff = effective_conditions(cond(ConditionName.PARALYZED))
        assert ConditionName.INCAPACITATED in eff

    def test_petrified_implies_incapacitated(self) -> None:
        """SRD p.186: Petrified → Incapacitated."""
        eff = effective_conditions(cond(ConditionName.PETRIFIED))
        assert ConditionName.INCAPACITATED in eff

    def test_stunned_implies_incapacitated(self) -> None:
        """SRD p.189: Stunned → Incapacitated."""
        eff = effective_conditions(cond(ConditionName.STUNNED))
        assert ConditionName.INCAPACITATED in eff

    def test_unconscious_implies_incapacitated_and_prone(self) -> None:
        """SRD p.191: Unconscious → Incapacitated + Prone."""
        eff = effective_conditions(cond(ConditionName.UNCONSCIOUS))
        assert ConditionName.INCAPACITATED in eff
        assert ConditionName.PRONE in eff

    def test_incapacitated_alone_does_not_imply_others(self) -> None:
        """SRD p.184: Incapacitated has no further implied conditions."""
        eff = effective_conditions(cond(ConditionName.INCAPACITATED))
        assert ConditionName.PRONE not in eff
        assert ConditionName.PARALYZED not in eff

    def test_no_conditions_is_empty(self) -> None:
        eff = effective_conditions([])
        assert len(eff) == 0

    def test_multiple_conditions_accumulate(self) -> None:
        eff = effective_conditions(conds(ConditionName.PARALYZED, ConditionName.PRONE))
        assert ConditionName.PRONE in eff
        assert ConditionName.PARALYZED in eff
        assert ConditionName.INCAPACITATED in eff


# ===========================================================================
# Blinded — SRD p.177
# ===========================================================================


class TestBlinded:
    def test_attack_disadvantage(self) -> None:
        """SRD p.177: 'your attack rolls have Disadvantage'."""
        mods = attack_roll_modifiers(cond(ConditionName.BLINDED))
        assert mods.has_disadvantage
        assert "Blinded" in mods.disadvantage_sources

    def test_attacks_against_advantage(self) -> None:
        """SRD p.177: 'Attack rolls against you have Advantage'."""
        mods = attacks_against_modifiers(cond(ConditionName.BLINDED))
        assert mods.has_advantage
        assert any("Blinded" in s for s in mods.advantage_sources)

    def test_does_not_affect_speed(self) -> None:
        assert effective_speed(cond(ConditionName.BLINDED), 30) == 30

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.BLINDED)) is True


# ===========================================================================
# Charmed — SRD p.179
# ===========================================================================


class TestCharmed:
    def test_does_not_affect_attack_rolls(self) -> None:
        """SRD p.179: Charmed restricts target selection, not roll modifiers."""
        mods = attack_roll_modifiers(cond(ConditionName.CHARMED))
        assert not mods.has_advantage
        assert not mods.has_disadvantage

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.CHARMED)) is True

    def test_does_not_affect_speed(self) -> None:
        assert effective_speed(cond(ConditionName.CHARMED), 30) == 30


# ===========================================================================
# Deafened — SRD p.181
# ===========================================================================


class TestDeafened:
    def test_does_not_affect_attack_rolls(self) -> None:
        """SRD p.181: Deafened only prevents hearing; no attack penalty."""
        mods = attack_roll_modifiers(cond(ConditionName.DEAFENED))
        assert not mods.has_advantage
        assert not mods.has_disadvantage

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.DEAFENED)) is True


# ===========================================================================
# Exhaustion — SRD p.181
# ===========================================================================


class TestExhaustion:
    def test_d20_penalty_level_1(self) -> None:
        """SRD p.181: 'the roll is reduced by 2 times your Exhaustion level'."""
        conditions = [ActiveCondition.exhaustion(1)]
        mods = attack_roll_modifiers(conditions)
        assert mods.d20_penalty == 2

    def test_d20_penalty_level_3(self) -> None:
        conditions = [ActiveCondition.exhaustion(3)]
        mods = attack_roll_modifiers(conditions)
        assert mods.d20_penalty == 6

    def test_speed_reduced_level_1(self) -> None:
        """SRD p.181: Speed reduced by 5 × exhaustion level."""
        conditions = [ActiveCondition.exhaustion(1)]
        assert effective_speed(conditions, 30) == 25

    def test_speed_reduced_level_4(self) -> None:
        conditions = [ActiveCondition.exhaustion(4)]
        assert effective_speed(conditions, 30) == 10

    def test_speed_floored_at_zero(self) -> None:
        conditions = [ActiveCondition.exhaustion(6)]
        assert effective_speed(conditions, 30) == 0

    def test_saving_throw_penalty(self) -> None:
        """SRD p.181: D20 Tests includes saving throws."""
        conditions = [ActiveCondition.exhaustion(2)]
        mods = saving_throw_modifiers(conditions)
        assert mods.d20_penalty == 4

    def test_can_act(self) -> None:
        """Exhaustion does not make a creature Incapacitated."""
        conditions = [ActiveCondition.exhaustion(5)]
        assert can_act(conditions) is True


# ===========================================================================
# Frightened — SRD p.182
# ===========================================================================


class TestFrightened:
    def test_attack_disadvantage_when_source_visible(self) -> None:
        """SRD p.182: Disadvantage on attacks while source of fear in LoS."""
        mods = attack_roll_modifiers(
            cond(ConditionName.FRIGHTENED), fear_source_visible=True
        )
        assert mods.has_disadvantage
        assert any("Frightened" in s for s in mods.disadvantage_sources)

    def test_no_attack_disadvantage_when_source_not_visible(self) -> None:
        """SRD p.182: Only while source is within line of sight."""
        mods = attack_roll_modifiers(
            cond(ConditionName.FRIGHTENED), fear_source_visible=False
        )
        assert not mods.has_disadvantage

    def test_ability_check_disadvantage_when_source_visible(self) -> None:
        """SRD p.182: Ability checks also affected."""
        mods = ability_check_modifiers(
            cond(ConditionName.FRIGHTENED), fear_source_visible=True
        )
        assert mods.has_disadvantage

    def test_frightened_does_not_affect_saving_throws(self) -> None:
        """SRD p.182: Frightened affects ability checks and attacks — not saves."""
        mods = saving_throw_modifiers(cond(ConditionName.FRIGHTENED))
        assert not mods.has_disadvantage

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.FRIGHTENED)) is True


# ===========================================================================
# Grappled — SRD p.182
# ===========================================================================


class TestGrappled:
    def test_speed_zero(self) -> None:
        """SRD p.182: 'Speed 0. Your Speed is 0 and can't increase.'"""
        assert effective_speed(cond(ConditionName.GRAPPLED), 30) == 0

    def test_does_not_prevent_acting(self) -> None:
        """SRD p.182: Grappled does not impose Incapacitated."""
        assert can_act(cond(ConditionName.GRAPPLED)) is True

    def test_attacks_against_no_modifier(self) -> None:
        """SRD p.182: Grappled doesn't give attackers advantage."""
        mods = attacks_against_modifiers(cond(ConditionName.GRAPPLED))
        assert not mods.has_advantage
        assert not mods.has_disadvantage


# ===========================================================================
# Incapacitated — SRD p.184
# ===========================================================================


class TestIncapacitated:
    def test_cannot_act(self) -> None:
        """SRD p.184: 'You can't take any action, Bonus Action, or Reaction.'"""
        assert can_act(cond(ConditionName.INCAPACITATED)) is False

    def test_does_not_reduce_speed(self) -> None:
        """SRD p.184: No speed reduction listed for Incapacitated."""
        assert effective_speed(cond(ConditionName.INCAPACITATED), 30) == 30

    def test_initiative_disadvantage(self) -> None:
        """SRD p.184: Disadvantage on Initiative roll when Incapacitated."""
        mods = initiative_roll_modifiers(cond(ConditionName.INCAPACITATED))
        assert mods.has_disadvantage
        assert "Incapacitated" in mods.disadvantage_sources

    def test_concentration_broken(self) -> None:
        """SRD p.179: 'Your Concentration ends if you have the Incapacitated condition.'"""
        assert concentration_is_broken(cond(ConditionName.INCAPACITATED)) is True

    def test_concentration_not_broken_without_incapacitated(self) -> None:
        assert concentration_is_broken(cond(ConditionName.POISONED)) is False


# ===========================================================================
# Invisible — SRD p.185
# ===========================================================================


class TestInvisible:
    def test_attack_advantage(self) -> None:
        """SRD p.185: 'your attack rolls have Advantage'."""
        mods = attack_roll_modifiers(cond(ConditionName.INVISIBLE))
        assert mods.has_advantage
        assert "Invisible" in mods.advantage_sources

    def test_attacks_against_disadvantage(self) -> None:
        """SRD p.185: 'Attack rolls against you have Disadvantage'."""
        mods = attacks_against_modifiers(cond(ConditionName.INVISIBLE))
        assert mods.has_disadvantage
        assert any("Invisible" in s for s in mods.disadvantage_sources)

    def test_initiative_advantage(self) -> None:
        """SRD p.185: 'If you're Invisible when you roll Initiative, you have Advantage.'"""
        mods = initiative_roll_modifiers(cond(ConditionName.INVISIBLE))
        assert mods.has_advantage
        assert "Invisible" in mods.advantage_sources

    def test_does_not_affect_speed(self) -> None:
        assert effective_speed(cond(ConditionName.INVISIBLE), 30) == 30

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.INVISIBLE)) is True


# ===========================================================================
# Paralyzed — SRD p.186
# ===========================================================================


class TestParalyzed:
    def test_cannot_act(self) -> None:
        """SRD p.186: Paralyzed → Incapacitated → can't act."""
        assert can_act(cond(ConditionName.PARALYZED)) is False

    def test_speed_zero(self) -> None:
        """SRD p.186: 'Speed 0. Your Speed is 0 and can't increase.'"""
        assert effective_speed(cond(ConditionName.PARALYZED), 30) == 0

    def test_auto_fail_str_save(self) -> None:
        """SRD p.186: 'You automatically fail Strength and Dexterity saving throws.'"""
        mods = saving_throw_modifiers(cond(ConditionName.PARALYZED))
        assert mods.auto_fails("STR")

    def test_auto_fail_dex_save(self) -> None:
        """SRD p.186: DEX saves also auto-fail."""
        mods = saving_throw_modifiers(cond(ConditionName.PARALYZED))
        assert mods.auto_fails("DEX")

    def test_does_not_auto_fail_con_save(self) -> None:
        mods = saving_throw_modifiers(cond(ConditionName.PARALYZED))
        assert not mods.auto_fails("CON")

    def test_attacks_against_advantage(self) -> None:
        """SRD p.186: 'Attack rolls against you have Advantage.'"""
        mods = attacks_against_modifiers(cond(ConditionName.PARALYZED))
        assert mods.has_advantage

    def test_auto_crit_within_5ft(self) -> None:
        """SRD p.186: 'Any attack roll that hits you is a Critical Hit if the
        attacker is within 5 feet of you.'"""
        mods = attacks_against_modifiers(
            cond(ConditionName.PARALYZED), attacker_within_5ft=True
        )
        assert mods.melee_auto_crit_within_5ft is True

    def test_no_auto_crit_beyond_5ft(self) -> None:
        """SRD p.186: Auto-crit only applies within 5 feet."""
        mods = attacks_against_modifiers(
            cond(ConditionName.PARALYZED), attacker_within_5ft=False
        )
        assert mods.melee_auto_crit_within_5ft is False

    def test_concentration_broken(self) -> None:
        """Paralyzed → Incapacitated → Concentration broken."""
        assert concentration_is_broken(cond(ConditionName.PARALYZED)) is True


# ===========================================================================
# Petrified — SRD p.186
# ===========================================================================


class TestPetrified:
    def test_cannot_act(self) -> None:
        """SRD p.186: Petrified → Incapacitated."""
        assert can_act(cond(ConditionName.PETRIFIED)) is False

    def test_speed_zero(self) -> None:
        """SRD p.186: Speed 0."""
        assert effective_speed(cond(ConditionName.PETRIFIED), 30) == 0

    def test_auto_fail_str_dex_saves(self) -> None:
        """SRD p.186: Auto-fail STR and DEX saves."""
        mods = saving_throw_modifiers(cond(ConditionName.PETRIFIED))
        assert mods.auto_fails("STR")
        assert mods.auto_fails("DEX")

    def test_attacks_against_advantage(self) -> None:
        """SRD p.186: Attack rolls against have Advantage."""
        mods = attacks_against_modifiers(cond(ConditionName.PETRIFIED))
        assert mods.has_advantage

    def test_no_auto_crit(self) -> None:
        """SRD p.186: Petrified does NOT grant auto-crit (unlike Paralyzed/Unconscious)."""
        mods = attacks_against_modifiers(
            cond(ConditionName.PETRIFIED), attacker_within_5ft=True
        )
        assert mods.melee_auto_crit_within_5ft is False


# ===========================================================================
# Poisoned — SRD p.187
# ===========================================================================


class TestPoisoned:
    def test_attack_disadvantage(self) -> None:
        """SRD p.187: 'You have Disadvantage on attack rolls and ability checks.'"""
        mods = attack_roll_modifiers(cond(ConditionName.POISONED))
        assert mods.has_disadvantage
        assert "Poisoned" in mods.disadvantage_sources

    def test_ability_check_disadvantage(self) -> None:
        mods = ability_check_modifiers(cond(ConditionName.POISONED))
        assert mods.has_disadvantage
        assert "Poisoned" in mods.disadvantage_sources

    def test_does_not_affect_saving_throws(self) -> None:
        """SRD p.187: Poisoned affects attack rolls and ability checks — not saves."""
        mods = saving_throw_modifiers(cond(ConditionName.POISONED))
        assert not mods.has_disadvantage
        assert len(mods.auto_fail_abilities) == 0

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.POISONED)) is True

    def test_does_not_affect_speed(self) -> None:
        assert effective_speed(cond(ConditionName.POISONED), 30) == 30


# ===========================================================================
# Prone — SRD p.187
# ===========================================================================


class TestProne:
    def test_own_attack_disadvantage(self) -> None:
        """SRD p.187: 'You have Disadvantage on attack rolls.'"""
        mods = attack_roll_modifiers(cond(ConditionName.PRONE))
        assert mods.has_disadvantage
        assert "Prone" in mods.disadvantage_sources

    def test_attacks_within_5ft_have_advantage(self) -> None:
        """SRD p.187: 'An attack roll against you has Advantage if the attacker
        is within 5 feet of you.'"""
        mods = attacks_against_modifiers(
            cond(ConditionName.PRONE), attacker_within_5ft=True
        )
        assert mods.has_advantage
        assert not mods.has_disadvantage

    def test_attacks_beyond_5ft_have_disadvantage(self) -> None:
        """SRD p.187: 'Otherwise, that attack roll has Disadvantage.'"""
        mods = attacks_against_modifiers(
            cond(ConditionName.PRONE), attacker_within_5ft=False
        )
        assert mods.has_disadvantage
        assert not mods.has_advantage

    def test_does_not_reduce_speed(self) -> None:
        """SRD p.187: Prone affects movement costs, not Speed itself."""
        assert effective_speed(cond(ConditionName.PRONE), 30) == 30

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.PRONE)) is True

    def test_no_auto_crit(self) -> None:
        mods = attacks_against_modifiers(
            cond(ConditionName.PRONE), attacker_within_5ft=True
        )
        assert mods.melee_auto_crit_within_5ft is False


# ===========================================================================
# Restrained — SRD p.187
# ===========================================================================


class TestRestrained:
    def test_speed_zero(self) -> None:
        """SRD p.187: 'Speed 0. Your Speed is 0 and can't increase.'"""
        assert effective_speed(cond(ConditionName.RESTRAINED), 30) == 0

    def test_attacks_against_advantage(self) -> None:
        """SRD p.187: 'Attack rolls against you have Advantage.'"""
        mods = attacks_against_modifiers(cond(ConditionName.RESTRAINED))
        assert mods.has_advantage

    def test_own_attack_disadvantage(self) -> None:
        """SRD p.187: 'your attack rolls have Disadvantage.'"""
        mods = attack_roll_modifiers(cond(ConditionName.RESTRAINED))
        assert mods.has_disadvantage

    def test_dex_save_disadvantage(self) -> None:
        """SRD p.187: 'You have Disadvantage on Dexterity saving throws.'"""
        mods = saving_throw_modifiers(cond(ConditionName.RESTRAINED), ability="DEX")
        assert mods.has_disadvantage

    def test_non_dex_save_no_disadvantage(self) -> None:
        """SRD p.187: Only DEX saves are penalized, not STR/CON/etc."""
        mods = saving_throw_modifiers(cond(ConditionName.RESTRAINED), ability="CON")
        assert not mods.has_disadvantage

    def test_does_not_prevent_acting(self) -> None:
        assert can_act(cond(ConditionName.RESTRAINED)) is True


# ===========================================================================
# Stunned — SRD p.189
# ===========================================================================


class TestStunned:
    def test_cannot_act(self) -> None:
        """SRD p.189: Stunned → Incapacitated → can't act."""
        assert can_act(cond(ConditionName.STUNNED)) is False

    def test_speed_not_reduced(self) -> None:
        """SRD p.189: Stunned does NOT reduce speed (no Speed 0 in SRD listing)."""
        assert effective_speed(cond(ConditionName.STUNNED), 30) == 30

    def test_auto_fail_str_dex_saves(self) -> None:
        """SRD p.189: 'You automatically fail Strength and Dexterity saving throws.'"""
        mods = saving_throw_modifiers(cond(ConditionName.STUNNED))
        assert mods.auto_fails("STR")
        assert mods.auto_fails("DEX")

    def test_attacks_against_advantage(self) -> None:
        """SRD p.189: 'Attack rolls against you have Advantage.'"""
        mods = attacks_against_modifiers(cond(ConditionName.STUNNED))
        assert mods.has_advantage

    def test_no_auto_crit(self) -> None:
        """SRD p.189: Stunned does NOT grant auto-crit (only Paralyzed/Unconscious do)."""
        mods = attacks_against_modifiers(
            cond(ConditionName.STUNNED), attacker_within_5ft=True
        )
        assert mods.melee_auto_crit_within_5ft is False

    def test_concentration_broken(self) -> None:
        assert concentration_is_broken(cond(ConditionName.STUNNED)) is True


# ===========================================================================
# Unconscious — SRD p.191
# ===========================================================================


class TestUnconscious:
    def test_cannot_act(self) -> None:
        """SRD p.191: Unconscious → Incapacitated."""
        assert can_act(cond(ConditionName.UNCONSCIOUS)) is False

    def test_speed_zero(self) -> None:
        """SRD p.191: 'Speed 0. Your Speed is 0 and can't increase.'"""
        assert effective_speed(cond(ConditionName.UNCONSCIOUS), 30) == 0

    def test_auto_fail_str_dex_saves(self) -> None:
        """SRD p.191: 'You automatically fail Strength and Dexterity saving throws.'"""
        mods = saving_throw_modifiers(cond(ConditionName.UNCONSCIOUS))
        assert mods.auto_fails("STR")
        assert mods.auto_fails("DEX")

    def test_attacks_against_advantage(self) -> None:
        """SRD p.191: 'Attack rolls against you have Advantage.'"""
        mods = attacks_against_modifiers(cond(ConditionName.UNCONSCIOUS))
        assert mods.has_advantage

    def test_auto_crit_within_5ft(self) -> None:
        """SRD p.191: 'Any attack roll that hits you is a Critical Hit if the
        attacker is within 5 feet of you.'"""
        mods = attacks_against_modifiers(
            cond(ConditionName.UNCONSCIOUS), attacker_within_5ft=True
        )
        assert mods.melee_auto_crit_within_5ft is True

    def test_no_auto_crit_beyond_5ft(self) -> None:
        mods = attacks_against_modifiers(
            cond(ConditionName.UNCONSCIOUS), attacker_within_5ft=False
        )
        assert mods.melee_auto_crit_within_5ft is False

    def test_implies_prone(self) -> None:
        """SRD p.191: 'You have the Incapacitated and Prone conditions.'"""
        eff = effective_conditions(cond(ConditionName.UNCONSCIOUS))
        assert ConditionName.PRONE in eff

    def test_concentration_broken(self) -> None:
        assert concentration_is_broken(cond(ConditionName.UNCONSCIOUS)) is True


# ===========================================================================
# Condition stacking / interactions
# ===========================================================================


class TestConditionStacking:
    def test_conditions_do_not_stack_with_themselves(self) -> None:
        """SRD p.179: 'A condition doesn't stack with itself.' Two Blinded
        entries produce the same result as one."""
        two_blinded = [
            ActiveCondition.indefinite(ConditionName.BLINDED),
            ActiveCondition.indefinite(ConditionName.BLINDED),
        ]
        mods = attack_roll_modifiers(two_blinded)
        # Still just one disadvantage source for Blinded
        assert mods.disadvantage_sources.count("Blinded") == 1

    def test_advantage_and_disadvantage_cancel(self) -> None:
        """SRD p.181: Advantage and Disadvantage on the same roll cancel out."""
        # Invisible (adv) + Prone (dis)
        conditions = conds(ConditionName.INVISIBLE, ConditionName.PRONE)
        mods = attack_roll_modifiers(conditions)
        assert mods.has_advantage
        assert mods.has_disadvantage
        assert not mods.net_advantage
        assert not mods.net_disadvantage

    def test_multiple_disadvantage_sources_still_just_disadvantage(self) -> None:
        """Multiple sources of disadvantage don't stack — it's still just disadvantage."""
        conditions = conds(ConditionName.BLINDED, ConditionName.POISONED)
        mods = attack_roll_modifiers(conditions)
        assert mods.net_disadvantage
        # Both sources are recorded
        assert "Blinded" in mods.disadvantage_sources
        assert "Poisoned" in mods.disadvantage_sources

    def test_paralyzed_plus_prone_auto_crit_and_advantage(self) -> None:
        """Paralyzed (within 5ft) + Prone: auto-crit from Paralyzed, advantage from Prone."""
        conditions = conds(ConditionName.PARALYZED, ConditionName.PRONE)
        mods = attacks_against_modifiers(conditions, attacker_within_5ft=True)
        assert mods.melee_auto_crit_within_5ft is True
        assert mods.has_advantage

    def test_exhaustion_level_6_kills(self) -> None:
        """SRD p.181: 'You die if your Exhaustion level is 6.'
        Level 6 should be accepted (the death is the caller's responsibility)."""
        c = ActiveCondition.exhaustion(6)
        assert c.exhaustion_level == 6
        assert effective_speed([c], 30) == 0
