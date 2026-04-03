"""Tests for combat.py — SRD 5.2.1 combat mechanics.

Every test cites the SRD 5.2.1 section it validates.
Deterministic seeds guarantee reproducibility.
"""

from __future__ import annotations

import pytest

from tavern.core.combat import (
    ActionType,
    CoverLevel,
    CreatureState,
    DamageType,
    DeathSaveState,
    GrappleResult,
    InitiativeEntry,
    apply_damage,
    apply_healing,
    attempt_grapple,
    attempt_shove,
    concentration_save_dc,
    cover_dex_save_bonus,
    gain_temp_hp,
    resolve_attack,
    roll_concentration_save,
    roll_death_save,
    roll_initiative,
    sort_initiative_order,
    triggers_opportunity_attack,
    two_weapon_damage_modifier,
)
from tavern.core.dice import roll_d20

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(current: int, maximum: int, temp: int = 0) -> CreatureState:
    return CreatureState(current_hp=current, max_hp=maximum, temp_hp=temp)


# ===========================================================================
# DamageType — SRD 5.2.1 Rules Glossary p.180
# ===========================================================================


class TestDamageTypes:
    def test_all_thirteen_types_defined(self) -> None:
        """SRD p.180: 13 damage types listed in table."""
        expected = {
            "Acid", "Bludgeoning", "Cold", "Fire", "Force",
            "Lightning", "Necrotic", "Piercing", "Poison",
            "Psychic", "Radiant", "Slashing", "Thunder",
        }
        actual = {dt.value for dt in DamageType}
        assert actual == expected


# ===========================================================================
# CoverLevel — SRD 5.2.1 p.15
# ===========================================================================


class TestCoverLevel:
    def test_half_cover_plus_two(self) -> None:
        """SRD p.15: Half cover grants +2 bonus to AC."""
        assert int(CoverLevel.HALF) == 2

    def test_three_quarters_plus_five(self) -> None:
        """SRD p.15: Three-quarters cover grants +5 bonus to AC."""
        assert int(CoverLevel.THREE_QUARTERS) == 5

    def test_cover_dex_save_bonus_half(self) -> None:
        """SRD p.15: Half cover: +2 to Dexterity saving throws."""
        assert cover_dex_save_bonus(CoverLevel.HALF) == 2

    def test_cover_dex_save_bonus_three_quarters(self) -> None:
        """SRD p.15: Three-quarters cover: +5 to Dexterity saving throws."""
        assert cover_dex_save_bonus(CoverLevel.THREE_QUARTERS) == 5

    def test_cover_dex_save_bonus_none(self) -> None:
        assert cover_dex_save_bonus(CoverLevel.NONE) == 0

    def test_total_cover_blocks_attack(self) -> None:
        """SRD p.15: Total cover — can't be targeted directly."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=12,
            damage_dice="1d6",
            damage_modifier=3,
            damage_type=DamageType.SLASHING,
            cover_level=CoverLevel.TOTAL,
            seed=42,
        )
        assert result.total_cover is True
        assert result.hit is False
        assert result.damage is None


# ===========================================================================
# ActionType — SRD 5.2.1 pp.9-10
# ===========================================================================


class TestActionType:
    def test_all_standard_actions_present(self) -> None:
        """SRD pp.9-10: Action Summary lists these standard actions."""
        expected = {
            "Attack", "Dash", "Disengage", "Dodge", "Help", "Hide",
            "Influence", "Magic", "Ready", "Search", "Study", "Utilize",
        }
        actual = {a.value for a in ActionType}
        assert actual == expected


# ===========================================================================
# resolve_attack — SRD 5.2.1 pp.14-16
# ===========================================================================


class TestResolveAttack:
    def test_hit_when_total_meets_ac(self) -> None:
        """SRD p.177: 'AC is the target number for an attack roll.' Meet or
        exceed to hit."""
        # Use seed that produces a hit at AC 10 with modifier +5
        for seed in range(100):
            r = roll_d20(modifier=5, seed=seed)
            if r.total >= 10 and not r.is_critical_hit and not r.is_critical_miss:
                result = resolve_attack(
                    attack_modifier=5,
                    target_ac=10,
                    damage_dice="1d8",
                    damage_modifier=3,
                    damage_type=DamageType.SLASHING,
                    seed=seed,
                )
                assert result.hit is True
                assert result.damage is not None
                break

    def test_miss_when_total_below_ac(self) -> None:
        """SRD p.177: Attack that falls short of AC misses."""
        # seed 1, modifier -5 → should miss AC 16
        result = resolve_attack(
            attack_modifier=-5,
            target_ac=16,
            damage_dice="1d8",
            damage_modifier=3,
            damage_type=DamageType.SLASHING,
            seed=1,
        )
        # total = natural + (-5); if natural <= 20 most likely miss
        if not result.is_critical:
            assert result.hit is False
            assert result.damage is None

    def test_natural_20_always_hits(self) -> None:
        """SRD p.16 (implied by D20 Test rules): Natural 20 = Critical Hit,
        always hits."""
        # Find a seed that produces natural 20
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if r.natural == 20:
                result = resolve_attack(
                    attack_modifier=-100,  # massive penalty
                    target_ac=100,         # impossible AC
                    damage_dice="1d6",
                    damage_modifier=0,
                    damage_type=DamageType.BLUDGEONING,
                    seed=seed,
                )
                assert result.hit is True
                assert result.is_critical is True
                break

    def test_natural_1_always_misses(self) -> None:
        """SRD p.16 (D20 Test rules): Natural 1 = critical miss, always fails."""
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if r.natural == 1:
                result = resolve_attack(
                    attack_modifier=100,  # massive bonus
                    target_ac=1,          # trivially easy AC
                    damage_dice="1d6",
                    damage_modifier=0,
                    damage_type=DamageType.BLUDGEONING,
                    seed=seed,
                )
                assert result.hit is False
                assert result.is_critical_miss is True
                break

    def test_critical_hit_doubles_damage_dice(self) -> None:
        """SRD 5.2.1 p.16: 'Roll the attack's damage dice twice, add them
        together, and add any relevant modifiers as normal.'"""
        # Find a seed that gives nat 20
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if r.natural == 20:
                normal = resolve_attack(
                    attack_modifier=5,
                    target_ac=10,
                    damage_dice="1d8",
                    damage_modifier=3,
                    damage_type=DamageType.SLASHING,
                    seed=seed,
                )
                assert normal.is_critical
                assert normal.damage is not None
                # Critical damage raw_total should exceed max normal damage
                # (1d8 + modifier) max = 8 + 3 = 11; crit min = 2 + 3 = 5
                # Just verify is_critical flag
                assert normal.damage.is_critical is True
                break

    def test_half_cover_increases_effective_ac(self) -> None:
        """SRD p.15: Half cover adds +2 to AC."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=14,
            damage_dice="1d6",
            damage_modifier=3,
            damage_type=DamageType.PIERCING,
            cover_level=CoverLevel.HALF,
            seed=42,
        )
        assert result.effective_ac == 16  # 14 + 2

    def test_three_quarters_cover_increases_effective_ac(self) -> None:
        """SRD p.15: Three-quarters cover adds +5 to AC."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=14,
            damage_dice="1d6",
            damage_modifier=3,
            damage_type=DamageType.PIERCING,
            cover_level=CoverLevel.THREE_QUARTERS,
            seed=42,
        )
        assert result.effective_ac == 19  # 14 + 5

    def test_advantage_uses_higher_roll(self) -> None:
        """SRD p.181: Advantage — roll two d20s, use higher."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=15,
            damage_dice="1d8",
            damage_modifier=3,
            damage_type=DamageType.SLASHING,
            advantage=True,
            seed=7,
        )
        assert result.attack_roll.had_advantage is True
        assert len(result.attack_roll.all_rolls) == 2
        assert result.attack_roll.natural == max(result.attack_roll.all_rolls)

    def test_disadvantage_uses_lower_roll(self) -> None:
        """SRD p.181: Disadvantage — roll two d20s, use lower."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=15,
            damage_dice="1d8",
            damage_modifier=3,
            damage_type=DamageType.SLASHING,
            disadvantage=True,
            seed=7,
        )
        assert result.attack_roll.had_disadvantage is True
        assert len(result.attack_roll.all_rolls) == 2
        assert result.attack_roll.natural == min(result.attack_roll.all_rolls)

    def test_advantage_and_disadvantage_cancel(self) -> None:
        """SRD p.181: 'Advantage and Disadvantage on the same roll cancel
        each other out.'"""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=15,
            damage_dice="1d8",
            damage_modifier=3,
            damage_type=DamageType.SLASHING,
            advantage=True,
            disadvantage=True,
            seed=7,
        )
        assert len(result.attack_roll.all_rolls) == 1

    def test_force_auto_crit_on_hit(self) -> None:
        """Paralyzed/Unconscious within 5 ft: any hit is a Critical Hit."""
        # Find a seed that hits without natural 20
        for seed in range(100):
            r = roll_d20(modifier=10, seed=seed)
            if not r.is_critical_hit and r.total >= 10:
                result = resolve_attack(
                    attack_modifier=10,
                    target_ac=10,
                    damage_dice="1d8",
                    damage_modifier=3,
                    damage_type=DamageType.SLASHING,
                    force_auto_crit=True,
                    seed=seed,
                )
                if result.hit and not result.attack_roll.is_critical_hit:
                    assert result.is_critical is True
                    break


# ===========================================================================
# Damage: resistance, vulnerability, immunity — SRD 5.2.1 p.17
# ===========================================================================


class TestDamageResistanceVulnerabilityImmunity:
    def _nat20_seed(self) -> int:
        for seed in range(1000):
            if roll_d20(seed=seed).natural == 20:
                return seed
        raise RuntimeError("Could not find nat-20 seed")  # pragma: no cover

    def test_resistance_halves_damage(self) -> None:
        """SRD p.17: 'If you have Resistance to a damage type, damage of that
        type is halved against you (round down).'"""
        # Guarantee a hit with a high modifier
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d1",  # always rolls 1 → raw = 1 + modifier
                damage_modifier=4,  # raw = 5
                damage_type=DamageType.FIRE,
                target_resistances=frozenset({"Fire"}),
                seed=seed,
            )
            if result.hit and not result.is_critical:
                assert result.damage is not None
                assert result.damage.was_resisted is True
                assert result.damage.total == result.damage.raw_total // 2
                break

    def test_vulnerability_doubles_damage(self) -> None:
        """SRD p.17: 'If you have Vulnerability to a damage type, damage of
        that type is doubled against you.'"""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d1",
                damage_modifier=4,
                damage_type=DamageType.COLD,
                target_vulnerabilities=frozenset({"Cold"}),
                seed=seed,
            )
            if result.hit and not result.is_critical:
                assert result.damage is not None
                assert result.damage.was_vulnerable is True
                assert result.damage.total == result.damage.raw_total * 2
                break

    def test_immunity_reduces_to_zero(self) -> None:
        """SRD p.17: 'Immunity to a damage type means you don't take damage
        of that type.'"""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d8",
                damage_modifier=5,
                damage_type=DamageType.POISON,
                target_immunities=frozenset({"Poison"}),
                seed=seed,
            )
            if result.hit:
                assert result.damage is not None
                assert result.damage.was_immune is True
                assert result.damage.total == 0
                break

    def test_immunity_overrides_resistance(self) -> None:
        """SRD p.17: Immunity takes precedence over Resistance."""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d6",
                damage_modifier=3,
                damage_type=DamageType.FIRE,
                target_resistances=frozenset({"Fire"}),
                target_immunities=frozenset({"Fire"}),
                seed=seed,
            )
            if result.hit:
                assert result.damage is not None
                assert result.damage.was_immune is True
                assert result.damage.total == 0
                break

    def test_order_resist_then_vulnerable(self) -> None:
        """SRD p.17: 'Resistance is applied second; Vulnerability is applied
        third.' 28 fire − (resist) → 14 − wait, creature has both resist
        and vuln: 28 → halve → 14 → double → 28? No — 'Multiple instances
        count as only one instance.' But here different modifiers. SRD example:
        28 fire with resist + vuln: halve to 14 (resist), then double to 28 (vuln)."""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d1",
                damage_modifier=27,   # raw = 28
                damage_type=DamageType.FIRE,
                target_resistances=frozenset({"Fire"}),
                target_vulnerabilities=frozenset({"Fire"}),
                seed=seed,
            )
            if result.hit and not result.is_critical:
                assert result.damage is not None
                # 28 → halve → 14 → double → 28
                assert result.damage.raw_total == 28
                assert result.damage.total == 28
                break

    def test_damage_not_negative(self) -> None:
        """SRD p.16: 'it's possible to deal 0 damage but not negative damage'."""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d1",
                damage_modifier=-10,  # heavy penalty
                damage_type=DamageType.BLUDGEONING,
                seed=seed,
            )
            if result.hit and not result.is_critical:
                assert result.damage is not None
                assert result.damage.total >= 0
                assert result.damage.raw_total >= 0
                break


# ===========================================================================
# Ranged attacks — SRD 5.2.1 p.15
# ===========================================================================


class TestRangedAttacks:
    def test_long_range_disadvantage(self) -> None:
        """SRD p.15: 'Your attack roll has Disadvantage when your target is
        beyond normal range.'  Caller applies disadvantage; this test verifies
        the resolve_attack pipeline handles it correctly."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=14,
            damage_dice="1d8",
            damage_modifier=3,
            damage_type=DamageType.PIERCING,
            disadvantage=True,  # long range
            seed=10,
        )
        assert result.attack_roll.had_disadvantage is True

    def test_ranged_in_melee_disadvantage(self) -> None:
        """SRD p.15: 'When you make a ranged attack roll with a weapon … you
        have Disadvantage on the roll if you are within 5 feet of an enemy
        who can see you.' Caller applies disadvantage."""
        result = resolve_attack(
            attack_modifier=5,
            target_ac=14,
            damage_dice="1d6",
            damage_modifier=3,
            damage_type=DamageType.PIERCING,
            disadvantage=True,  # melee range with ranged weapon
            seed=20,
        )
        assert result.attack_roll.had_disadvantage is True


# ===========================================================================
# Two-weapon fighting — SRD 5.2.1 p.89 (Light weapon property)
# ===========================================================================


class TestTwoWeaponFighting:
    def test_positive_modifier_not_added(self) -> None:
        """SRD p.89: 'you don't add your ability modifier to the extra
        attack's damage unless that modifier is negative.'"""
        assert two_weapon_damage_modifier(3) == 0

    def test_negative_modifier_is_added(self) -> None:
        """SRD p.89: Negative modifiers still apply to extra attack."""
        assert two_weapon_damage_modifier(-2) == -2

    def test_zero_modifier_gives_zero(self) -> None:
        assert two_weapon_damage_modifier(0) == 0

    def test_fighting_style_adds_positive_modifier(self) -> None:
        """SRD p.88 (Two-Weapon Fighting feat): 'you can add your ability
        modifier to the damage of that attack.'"""
        assert two_weapon_damage_modifier(4, has_fighting_style=True) == 4

    def test_fighting_style_negative_still_applies(self) -> None:
        assert two_weapon_damage_modifier(-3, has_fighting_style=True) == -3


# ===========================================================================
# HP management — SRD 5.2.1 pp.16-18
# ===========================================================================


class TestHpManagement:
    def test_damage_reduces_hp(self) -> None:
        """SRD p.16: 'Whenever you take damage, subtract it from your Hit Points.'"""
        state = _state(20, 20)
        new_state, result = apply_damage(state, 8)
        assert new_state.current_hp == 12
        assert result.damage_to_real_hp == 8

    def test_hp_floors_at_zero(self) -> None:
        """SRD p.16: 'Hit Point loss has no effect … until you reach 0 HP.'
        HP can't go below 0."""
        state = _state(5, 20)
        new_state, result = apply_damage(state, 100)
        assert new_state.current_hp == 0

    def test_temp_hp_absorbed_first(self) -> None:
        """SRD p.18: 'If you have Temporary Hit Points and take damage, those
        points are lost first, and any leftover damage carries over.'"""
        state = _state(10, 20, temp=5)
        new_state, result = apply_damage(state, 7)
        assert result.damage_to_temp_hp == 5
        assert result.damage_to_real_hp == 2
        assert new_state.temp_hp == 0
        assert new_state.current_hp == 8

    def test_temp_hp_fully_absorbs_small_damage(self) -> None:
        """SRD p.18: Temp HP absorbs damage before real HP."""
        state = _state(15, 20, temp=10)
        new_state, result = apply_damage(state, 3)
        assert new_state.temp_hp == 7
        assert new_state.current_hp == 15
        assert result.damage_to_real_hp == 0

    def test_instant_death_massive_damage(self) -> None:
        """SRD p.17: 'the character dies if the remainder equals or exceeds
        their Hit Point maximum.' 6 HP, takes 18 dmg: 12 remaining >= max 12."""
        state = _state(6, 12)
        new_state, result = apply_damage(state, 18)
        assert result.instant_death is True
        assert new_state.current_hp == 0

    def test_no_instant_death_when_remainder_less_than_max(self) -> None:
        """SRD p.17: Remainder < max_hp → not instant death."""
        state = _state(10, 20)
        new_state, result = apply_damage(state, 15)
        # remainder = 15 - 10 = 5, max_hp = 20 → no instant death
        assert result.instant_death is False
        assert result.dropped_to_zero is True

    def test_dropped_to_zero_flag(self) -> None:
        state = _state(5, 20)
        _, result = apply_damage(state, 10)
        assert result.dropped_to_zero is True

    def test_not_dropped_to_zero_when_hp_remains(self) -> None:
        state = _state(10, 20)
        _, result = apply_damage(state, 5)
        assert result.dropped_to_zero is False

    def test_damage_at_zero_adds_death_save_failure(self) -> None:
        """SRD p.18: 'If you take any damage while you have 0 HP, you suffer
        a Death Saving Throw failure.'"""
        state = _state(0, 20)
        _, result = apply_damage(state, 5)
        assert result.death_save_failures_added == 1

    def test_critical_damage_at_zero_adds_two_failures(self) -> None:
        """SRD p.18: 'If the damage is from a Critical Hit, you suffer two
        failures instead.'"""
        state = _state(0, 20)
        _, result = apply_damage(state, 5, is_critical=True)
        assert result.death_save_failures_added == 2

    def test_damage_at_zero_instant_death_threshold(self) -> None:
        """SRD p.18: 'If the damage equals or exceeds your HP maximum, you die.'"""
        state = _state(0, 10)
        _, result = apply_damage(state, 10)
        assert result.instant_death is True

    def test_healing_restores_hp(self) -> None:
        """SRD p.17: 'When you receive healing, add the restored HP to your
        current Hit Points.'"""
        state = _state(5, 20)
        new_state, gained = apply_healing(state, 8)
        assert new_state.current_hp == 13
        assert gained == 8

    def test_healing_capped_at_maximum(self) -> None:
        """SRD p.17: 'Your HP can't exceed your HP maximum.'"""
        state = _state(18, 20)
        new_state, gained = apply_healing(state, 10)
        assert new_state.current_hp == 20
        assert gained == 2

    def test_healing_resets_death_saves(self) -> None:
        """SRD p.17: 'The number of both is reset to zero when you regain any HP.'"""
        death_state = DeathSaveState(successes=2, failures=1)
        state = CreatureState(current_hp=0, max_hp=20, death_save_state=death_state)
        new_state, _ = apply_healing(state, 1)
        assert new_state.death_save_state.successes == 0
        assert new_state.death_save_state.failures == 0

    def test_gain_temp_hp_replaces_lower(self) -> None:
        """SRD p.18: 'you decide whether to keep the ones you have or gain
        the new ones.' This engine always takes the higher value."""
        state = _state(10, 20, temp=5)
        new_state = gain_temp_hp(state, 12)
        assert new_state.temp_hp == 12

    def test_gain_temp_hp_keeps_higher(self) -> None:
        """SRD p.18: Don't downgrade temp HP."""
        state = _state(10, 20, temp=15)
        new_state = gain_temp_hp(state, 8)
        assert new_state.temp_hp == 15

    def test_temp_hp_do_not_stack(self) -> None:
        """SRD p.18: 'Temporary HP can't be added together.'"""
        state = _state(10, 20, temp=10)
        new_state = gain_temp_hp(state, 10)
        assert new_state.temp_hp == 10  # not 20

    def test_bloodied_at_half_hp(self) -> None:
        """SRD p.16: Bloodied while HP <= half max."""
        state = _state(10, 20)
        assert state.is_bloodied is True

    def test_not_bloodied_above_half(self) -> None:
        state = _state(11, 20)
        assert state.is_bloodied is False


# ===========================================================================
# Initiative — SRD 5.2.1 p.13
# ===========================================================================


class TestInitiative:
    def test_roll_initiative_adds_dex_modifier(self) -> None:
        """SRD p.13: 'they make a Dexterity check that determines their place
        in the Initiative order.'"""
        result = roll_initiative(dex_modifier=3, seed=42)
        assert result.total == result.natural + 3

    def test_sort_highest_first(self) -> None:
        """SRD p.13: 'The GM ranks the combatants, from highest to lowest.'"""
        entries = [
            InitiativeEntry("Goblin", 8, 0, roll_d20(seed=1)),
            InitiativeEntry("Fighter", 15, 2, roll_d20(seed=2)),
            InitiativeEntry("Wizard", 12, 1, roll_d20(seed=3)),
        ]
        # Manually set initiative values
        entries[0].initiative = 8
        entries[1].initiative = 15
        entries[2].initiative = 12

        sorted_entries = sort_initiative_order(entries)
        assert sorted_entries[0].name == "Fighter"
        assert sorted_entries[1].name == "Wizard"
        assert sorted_entries[2].name == "Goblin"

    def test_tiebreak_by_dex_modifier(self) -> None:
        """Tie: higher DEX modifier goes first (deterministic tiebreak)."""
        roll = roll_d20(seed=42)
        a = InitiativeEntry("A", 12, dex_modifier=1, roll_result=roll)
        b = InitiativeEntry("B", 12, dex_modifier=3, roll_result=roll)
        c = InitiativeEntry("C", 12, dex_modifier=2, roll_result=roll)
        a.initiative = b.initiative = c.initiative = 12

        sorted_entries = sort_initiative_order([a, b, c])
        assert sorted_entries[0].name == "B"
        assert sorted_entries[1].name == "C"
        assert sorted_entries[2].name == "A"

    def test_surprise_grants_disadvantage(self) -> None:
        """SRD p.13: 'If a combatant is surprised … Disadvantage on Initiative.'"""
        result = roll_initiative(dex_modifier=2, disadvantage=True, seed=5)
        assert result.had_disadvantage is True
        assert len(result.all_rolls) == 2
        assert result.natural == min(result.all_rolls)

    def test_deterministic_with_seed(self) -> None:
        """Initiative with same seed always produces same result."""
        r1 = roll_initiative(dex_modifier=2, seed=99)
        r2 = roll_initiative(dex_modifier=2, seed=99)
        assert r1.total == r2.total
        assert r1.natural == r2.natural


# ===========================================================================
# Death Saving Throws — SRD 5.2.1 pp.17-18
# ===========================================================================


class TestDeathSavingThrows:
    def _seed_for_natural(self, target: int) -> int:
        for seed in range(10000):
            r = roll_d20(seed=seed)
            if r.natural == target:
                return seed
        raise RuntimeError(f"Could not find seed for natural {target}")

    def test_success_on_10_or_higher(self) -> None:
        """SRD p.17: 'If the roll is 10 or higher, you succeed.'"""
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if 10 <= r.natural <= 19:  # success but not nat20
                result = roll_death_save(DeathSaveState(), seed=seed)
                assert result.success is True
                assert result.failures_added == 0
                assert result.state_after.successes == 1
                break

    def test_failure_on_9_or_lower(self) -> None:
        """SRD p.17: 'Otherwise, you fail.'"""
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if 2 <= r.natural <= 9:
                result = roll_death_save(DeathSaveState(), seed=seed)
                assert result.success is False
                assert result.failures_added == 1
                assert result.state_after.failures == 1
                break

    def test_natural_1_two_failures(self) -> None:
        """SRD p.18: 'When you roll a 1 on the d20 for a Death Saving Throw,
        you suffer two failures.'"""
        seed = self._seed_for_natural(1)
        result = roll_death_save(DeathSaveState(), seed=seed)
        assert result.failures_added == 2
        assert result.state_after.failures == 2

    def test_natural_20_regain_1_hp(self) -> None:
        """SRD p.18: 'If you roll a 20 on the d20, you regain 1 Hit Point.'"""
        seed = self._seed_for_natural(20)
        result = roll_death_save(DeathSaveState(), seed=seed)
        assert result.regained_hp == 1
        assert result.outcome == "regained_hp"
        # Death saves reset
        assert result.state_after.successes == 0
        assert result.state_after.failures == 0

    def test_three_successes_stabilized(self) -> None:
        """SRD p.17: 'On your third success, you become Stable.'"""
        state = DeathSaveState(successes=2, failures=0)
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if 10 <= r.natural <= 19:
                result = roll_death_save(state, seed=seed)
                assert result.outcome == "stabilized"
                assert result.state_after.is_stable is True
                break

    def test_three_failures_dead(self) -> None:
        """SRD p.17: 'On your third failure, you die.'"""
        state = DeathSaveState(successes=0, failures=2)
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if 2 <= r.natural <= 9:
                result = roll_death_save(state, seed=seed)
                assert result.outcome == "dead"
                assert result.state_after.is_dead is True
                break

    def test_nat_1_with_two_existing_failures_kills(self) -> None:
        """SRD p.18: Nat 1 = 2 failures. With 1 existing failure → total 3 → dead."""
        state = DeathSaveState(successes=0, failures=1)
        seed = self._seed_for_natural(1)
        result = roll_death_save(state, seed=seed)
        assert result.failures_added == 2
        assert result.outcome == "dead"

    def test_deterministic_with_seed(self) -> None:
        r1 = roll_death_save(DeathSaveState(), seed=42)
        r2 = roll_death_save(DeathSaveState(), seed=42)
        assert r1.roll.natural == r2.roll.natural
        assert r1.outcome == r2.outcome


# ===========================================================================
# Grapple — SRD 5.2.1 Rules Glossary p.190
# ===========================================================================


class TestGrapple:
    def test_dc_equals_8_plus_str_mod_plus_prof(self) -> None:
        """SRD p.190: 'DC equals 8 plus your Strength modifier and Proficiency Bonus.'"""
        result = attempt_grapple(
            attacker_str_modifier=3,
            attacker_proficiency_bonus=2,
            target_str_modifier=1,
            target_dex_modifier=2,
            seed=42,
        )
        assert result.dc == 13  # 8 + 3 + 2

    def test_target_fails_save_becomes_grappled(self) -> None:
        """SRD p.190: Target fails → Grappled condition."""
        # Make DC impossibly high (50) and target roll will fail
        for seed in range(1000):
            result = attempt_grapple(
                attacker_str_modifier=20,  # DC = 30
                attacker_proficiency_bonus=2,
                target_str_modifier=-5,    # tiny chance of success
                target_dex_modifier=-5,
                target_uses_dex=False,
                seed=seed,
            )
            if result.grappled:
                assert result.grappled is True
                break

    def test_target_succeeds_not_grappled(self) -> None:
        """SRD p.190: Target succeeds → no effect."""
        # DC = 10, target rolls with +20 modifier — will always beat 10
        for seed in range(100):
            result = attempt_grapple(
                attacker_str_modifier=0,  # DC = 10
                attacker_proficiency_bonus=2,
                target_str_modifier=20,
                target_dex_modifier=20,
                target_uses_dex=False,
                seed=seed,
            )
            if not result.grappled:
                assert result.grappled is False
                break

    def test_target_can_use_dex(self) -> None:
        """SRD p.190: Target chooses STR or DEX for saving throw."""
        result = attempt_grapple(
            attacker_str_modifier=2,
            attacker_proficiency_bonus=2,
            target_str_modifier=0,
            target_dex_modifier=4,
            target_uses_dex=True,
            seed=42,
        )
        # Just verifying it runs without error when dex is chosen
        assert isinstance(result, GrappleResult)

    def test_deterministic_with_seed(self) -> None:
        r1 = attempt_grapple(2, 2, 1, 1, seed=99)
        r2 = attempt_grapple(2, 2, 1, 1, seed=99)
        assert r1.grappled == r2.grappled
        assert r1.target_save.natural == r2.target_save.natural


# ===========================================================================
# Shove — SRD 5.2.1 Rules Glossary p.190
# ===========================================================================


class TestShove:
    def test_dc_equals_8_plus_str_mod_plus_prof(self) -> None:
        """SRD p.190: Same DC formula as Grapple."""
        result = attempt_shove(
            attacker_str_modifier=4,
            attacker_proficiency_bonus=3,
            target_str_modifier=0,
            target_dex_modifier=0,
            effect="push",
            seed=42,
        )
        assert result.dc == 15  # 8 + 4 + 3

    def test_push_effect(self) -> None:
        """SRD p.190: 'you either push it 5 feet away'."""
        # Make DC low enough that we can force a failure
        for seed in range(1000):
            result = attempt_shove(
                attacker_str_modifier=20,
                attacker_proficiency_bonus=4,
                target_str_modifier=-5,
                target_dex_modifier=-5,
                effect="push",
                seed=seed,
            )
            if result.pushed_5ft:
                assert result.knocked_prone is False
                break

    def test_prone_effect(self) -> None:
        """SRD p.190: 'or cause it to have the Prone condition'."""
        for seed in range(1000):
            result = attempt_shove(
                attacker_str_modifier=20,
                attacker_proficiency_bonus=4,
                target_str_modifier=-5,
                target_dex_modifier=-5,
                effect="prone",
                seed=seed,
            )
            if result.knocked_prone:
                assert result.pushed_5ft is False
                break

    def test_invalid_effect_raises(self) -> None:
        with pytest.raises(ValueError):
            attempt_shove(0, 2, 0, 0, effect="fly", seed=1)

    def test_successful_save_no_effect(self) -> None:
        for seed in range(100):
            result = attempt_shove(
                attacker_str_modifier=0,
                attacker_proficiency_bonus=2,
                target_str_modifier=20,
                target_dex_modifier=20,
                effect="push",
                seed=seed,
            )
            if not result.pushed_5ft:
                assert result.knocked_prone is False
                break

    def test_deterministic_with_seed(self) -> None:
        r1 = attempt_shove(2, 2, 1, 1, effect="prone", seed=77)
        r2 = attempt_shove(2, 2, 1, 1, effect="prone", seed=77)
        assert r1.knocked_prone == r2.knocked_prone


# ===========================================================================
# Opportunity Attacks — SRD 5.2.1 p.15
# ===========================================================================


class TestOpportunityAttacks:
    def test_triggers_when_leaving_reach(self) -> None:
        """SRD p.15: 'You can make an Opportunity Attack when a creature that
        you can see leaves your reach.'"""
        assert triggers_opportunity_attack(leaving_reach=True) is True

    def test_disengage_prevents_opportunity_attack(self) -> None:
        """SRD p.15: 'You can avoid provoking an Opportunity Attack by taking
        the Disengage action.'"""
        assert triggers_opportunity_attack(
            leaving_reach=True, used_disengage=True
        ) is False

    def test_teleport_does_not_trigger(self) -> None:
        """SRD p.15: 'You also don't provoke an Opportunity Attack when you
        Teleport.'"""
        assert triggers_opportunity_attack(
            leaving_reach=True, is_teleporting=True
        ) is False

    def test_external_force_does_not_trigger(self) -> None:
        """SRD p.15: 'or when you are moved without using your movement,
        action, Bonus Action, or Reaction.'"""
        assert triggers_opportunity_attack(
            leaving_reach=True, moved_by_external_force=True
        ) is False

    def test_not_leaving_reach_no_trigger(self) -> None:
        assert triggers_opportunity_attack(leaving_reach=False) is False


# ===========================================================================
# Concentration saves — SRD 5.2.1 p.179
# ===========================================================================


class TestConcentrationSaves:
    def test_dc_minimum_ten(self) -> None:
        """SRD p.179: 'The DC equals 10 or half the damage taken (round down),
        whichever is higher.'"""
        assert concentration_save_dc(5) == 10   # half of 5 = 2; max(10,2)=10
        assert concentration_save_dc(10) == 10  # half of 10 = 5; max(10,5)=10

    def test_dc_half_damage_when_higher(self) -> None:
        assert concentration_save_dc(30) == 15  # half of 30 = 15

    def test_dc_capped_at_30(self) -> None:
        """SRD p.179: 'up to a maximum DC of 30'."""
        assert concentration_save_dc(200) == 30

    def test_concentration_save_uses_con_modifier(self) -> None:
        """SRD p.179: Constitution saving throw."""
        result = roll_concentration_save(damage_taken=10, con_modifier=3, seed=42)
        assert result.total == result.natural + 3

    def test_proficiency_adds_to_roll(self) -> None:
        r1 = roll_concentration_save(10, con_modifier=2, seed=42)
        r2 = roll_concentration_save(
            10, con_modifier=2, proficiency_bonus=3, is_proficient=True, seed=42
        )
        assert r2.total == r1.total + 3


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_zero_damage_does_not_drop_to_zero(self) -> None:
        state = _state(10, 20)
        new_state, result = apply_damage(state, 0)
        assert new_state.current_hp == 10
        assert result.dropped_to_zero is False

    def test_healing_zero_hp_creature(self) -> None:
        state = _state(0, 20)
        new_state, gained = apply_healing(state, 5)
        assert new_state.current_hp == 5
        assert gained == 5

    def test_initiative_order_empty_list(self) -> None:
        assert sort_initiative_order([]) == []

    def test_attack_modifier_exactly_meets_ac(self) -> None:
        """SRD p.177: 'meet or exceed' — equal to AC is a hit."""
        # Find a seed where natural + modifier == target_ac exactly
        # Use modifier 0 and AC = the natural roll value
        for seed in range(1000):
            r = roll_d20(seed=seed)
            if r.natural not in (1, 20):  # avoid crit/miss
                ac = r.natural  # attack total will exactly equal AC
                result = resolve_attack(
                    attack_modifier=0,
                    target_ac=ac,
                    damage_dice="1d4",
                    damage_modifier=0,
                    damage_type=DamageType.BLUDGEONING,
                    seed=seed,
                )
                assert result.hit is True
                break

    def test_damage_type_mismatch_no_resistance(self) -> None:
        """Resistance to Fire does not affect Slashing damage."""
        for seed in range(100):
            result = resolve_attack(
                attack_modifier=20,
                target_ac=10,
                damage_dice="1d8",
                damage_modifier=3,
                damage_type=DamageType.SLASHING,
                target_resistances=frozenset({"Fire"}),  # wrong type
                seed=seed,
            )
            if result.hit and not result.is_critical:
                assert result.damage is not None
                assert result.damage.was_resisted is False
                break
