"""Combat mechanics for the SRD 5.2.1 Rules Engine.

Implements all deterministic combat outcomes per SRD 5.2.1 "Playing the Game"
(pp. 13–18) and the Rules Glossary. The Rules Engine is the sole authority on
mechanical outcomes (ADR-0001).

Module organisation:
- Enums and constants  (damage types, cover levels, action types)
- Result dataclasses   (AttackResult, DamageResult, InitiativeEntry, …)
- Attack pipeline      (resolve_attack)
- Damage application   (apply_damage, apply_healing)
- Initiative           (roll_initiative, sort_initiative_order)
- Surprise mechanics   (CombatParticipant, CombatSnapshot, determine_surprise,
                        roll_initiative_order) — ADR-0014
- Death saving throws  (roll_death_save)
- Grapple / Shove      (attempt_grapple, attempt_shove)
- Opportunity attacks  (triggers_opportunity_attack)
- Concentration saves  (roll_concentration_save)
- Action types         (ActionType enum)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Literal

from tavern.core.dice import D20Result, DiceResult, roll, roll_d20

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Damage types — SRD 5.2.1 Rules Glossary p.180
# ---------------------------------------------------------------------------


class DamageType(StrEnum):
    """All damage types listed in SRD 5.2.1 Rules Glossary p.180."""

    ACID = "Acid"
    BLUDGEONING = "Bludgeoning"
    COLD = "Cold"
    FIRE = "Fire"
    FORCE = "Force"
    LIGHTNING = "Lightning"
    NECROTIC = "Necrotic"
    PIERCING = "Piercing"
    POISON = "Poison"
    PSYCHIC = "Psychic"
    RADIANT = "Radiant"
    SLASHING = "Slashing"
    THUNDER = "Thunder"


# ---------------------------------------------------------------------------
# Cover levels — SRD 5.2.1 p.15
# ---------------------------------------------------------------------------


class CoverLevel(int, Enum):
    """Three degrees of cover per SRD 5.2.1 p.15.

    Half cover:         +2 bonus to AC and Dexterity saving throws.
    Three-quarters:     +5 bonus to AC and Dexterity saving throws.
    Total cover:        can't be targeted directly.

    'If a target is behind multiple sources of cover, only the most protective
    degree of cover applies; the degrees aren't added together.' (SRD p.15)
    """

    NONE = 0
    HALF = 2
    THREE_QUARTERS = 5
    TOTAL = -1  # sentinel: cannot be targeted


# ---------------------------------------------------------------------------
# Action types — SRD 5.2.1 "Playing the Game" pp.9-10
# ---------------------------------------------------------------------------


class ActionType(StrEnum):
    """Standard actions defined in SRD 5.2.1 pp.9-10."""

    ATTACK = "Attack"
    DASH = "Dash"
    DISENGAGE = "Disengage"
    DODGE = "Dodge"
    HELP = "Help"
    HIDE = "Hide"
    INFLUENCE = "Influence"
    MAGIC = "Magic"
    READY = "Ready"
    SEARCH = "Search"
    STUDY = "Study"
    UTILIZE = "Utilize"


# ---------------------------------------------------------------------------
# Attack types
# ---------------------------------------------------------------------------


class AttackType(StrEnum):
    MELEE_WEAPON = "MeleeWeapon"
    RANGED_WEAPON = "RangedWeapon"
    SPELL = "Spell"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DamageResult:
    """Fully resolved damage after resistance, vulnerability, and immunity.

    SRD 5.2.1 p.17 — Order of Application:
    1. Adjustments (bonuses, penalties, multipliers)
    2. Resistance  (halve, round down)
    3. Vulnerability (double)

    'Multiple instances of Resistance or Vulnerability … count as only one
    instance.' (SRD p.17)
    """

    total: int
    """Final damage after all modifiers. Always >= 0."""

    raw_total: int
    """Damage before resistance/vulnerability — after critical-hit dice doubling
    and ability modifiers."""

    dice_result: DiceResult
    """The raw dice roll."""

    damage_type: str
    """Damage type string (see DamageType)."""

    is_critical: bool
    """Whether this damage arose from a Critical Hit."""

    was_resisted: bool
    """True if Resistance halved the damage."""

    was_vulnerable: bool
    """True if Vulnerability doubled the damage."""

    was_immune: bool
    """True if Immunity reduced the damage to 0."""


@dataclass
class AttackResult:
    """Complete result of a single attack roll and damage calculation.

    ``damage`` is None on a miss, or when the target has Total Cover.
    """

    hit: bool
    is_critical: bool
    is_critical_miss: bool
    attack_roll: D20Result
    effective_ac: int
    """Target AC including cover bonus."""

    damage: DamageResult | None
    """None on a miss."""

    total_cover: bool = False
    """True when the target has Total Cover — attack cannot be made."""

    modifiers_applied: list[str] | None = None
    """Modifiers that influenced this attack (e.g. ``["advantage", "cover_half"]``)."""

    decision_summary: str | None = None
    """Human-readable summary, e.g. ``"Hit — 19 vs AC 15, 2d6+3 slashing"``."""


@dataclass
class InitiativeEntry:
    """One combatant's Initiative roll result.

    SRD 5.2.1 p.13: Initiative is a Dexterity check (d20 + DEX modifier).
    Ties: 'the GM decides the order among tied monsters, and the players
    decide the order among tied characters.' (SRD p.13)  For deterministic
    ordering this engine breaks ties by higher DEX modifier.
    """

    name: str
    initiative: int
    """Total roll (natural d20 + DEX modifier)."""

    dex_modifier: int
    roll_result: D20Result


@dataclass
class DeathSaveState:
    """Tracks a creature's ongoing Death Saving Throw state.

    SRD 5.2.1 p.17: 'The successes and failures don't need to be consecutive;
    keep track of both until you collect three of a kind.'
    """

    successes: int = 0
    failures: int = 0
    is_stable: bool = False
    is_dead: bool = False

    def reset(self) -> DeathSaveState:
        """Reset after regaining any HP (SRD p.17)."""
        return DeathSaveState()


@dataclass
class DeathSaveResult:
    """Result of one Death Saving Throw roll.

    SRD 5.2.1 pp.17-18:
    - 10+  = success (1 success)
    - 9-   = failure (1 failure)
    - Nat 20 = regain 1 HP (not a normal success)
    - Nat 1  = 2 failures
    - 3 successes = stabilized
    - 3 failures  = dead
    """

    roll: D20Result
    success: bool
    failures_added: int
    """0 on a success; 1 or 2 on a failure (2 on Nat 1)."""

    regained_hp: int
    """1 on a Nat 20, else 0."""

    state_after: DeathSaveState
    outcome: str
    """'continue' | 'stabilized' | 'dead' | 'regained_hp'"""


@dataclass
class CreatureState:
    """Minimal HP/temp-HP state required for damage and healing calculations."""

    current_hp: int
    max_hp: int
    temp_hp: int = 0
    death_save_state: DeathSaveState = field(default_factory=DeathSaveState)

    @property
    def is_at_zero(self) -> bool:
        return self.current_hp <= 0

    @property
    def is_bloodied(self) -> bool:
        """SRD p.16: Bloodied = half HP or fewer."""
        return self.current_hp <= self.max_hp // 2


@dataclass
class DamageApplicationResult:
    """Result of applying damage to a creature.

    SRD 5.2.1 p.18: Temporary Hit Points are lost first; any overflow
    carries to real HP.  Instant death when damage at 0 HP >= max_hp.
    """

    hp_before: int
    temp_hp_before: int
    hp_after: int
    temp_hp_after: int
    damage_to_temp_hp: int
    damage_to_real_hp: int
    instant_death: bool
    """SRD p.17: damage at 0 HP and remaining damage >= max_hp → instant death."""

    dropped_to_zero: bool
    """True if creature just reached 0 HP this hit."""

    death_save_failures_added: int
    """1 (hit at 0 HP) or 2 (critical hit at 0 HP), else 0. SRD p.18."""


@dataclass
class GrappleResult:
    """Result of a Grapple attempt (Unarmed Strike option).

    SRD 5.2.1 Rules Glossary p.190 (Unarmed Strike):
    'Grapple. The target must succeed on a Strength or Dexterity saving throw
    (it chooses which), or it has the Grappled condition. The DC equals
    8 + your Strength modifier + Proficiency Bonus.'
    """

    dc: int
    target_save: D20Result
    grappled: bool
    """True when the target *failed* the save (grapple succeeded)."""


@dataclass
class ShoveResult:
    """Result of a Shove attempt (Unarmed Strike option).

    SRD 5.2.1 Rules Glossary p.190 (Unarmed Strike):
    'Shove. The target must succeed on a Strength or Dexterity saving throw
    (it chooses which), or you either push it 5 feet away or cause it to have
    the Prone condition. The DC equals 8 + your Strength modifier +
    Proficiency Bonus.'
    """

    dc: int
    target_save: D20Result
    pushed_5ft: bool
    knocked_prone: bool


# ---------------------------------------------------------------------------
# Damage calculation helpers
# ---------------------------------------------------------------------------


def _apply_resistance_vulnerability(
    raw: int,
    damage_type: str,
    resistances: frozenset[str],
    vulnerabilities: frozenset[str],
    immunities: frozenset[str],
) -> tuple[int, bool, bool, bool]:
    """Apply resistance / vulnerability / immunity in SRD order (p.17).

    Order: bonuses/modifiers (already in raw) → Resistance → Vulnerability.
    'Multiple instances count as only one instance.' (SRD p.17)

    Returns (total, was_resisted, was_vulnerable, was_immune).
    """
    was_immune = damage_type in immunities
    was_resisted = damage_type in resistances and not was_immune
    was_vulnerable = damage_type in vulnerabilities and not was_immune

    if was_immune:
        return 0, False, False, True

    total = raw
    if was_resisted:
        total = total // 2  # round down (SRD p.17)
    if was_vulnerable:
        total = total * 2

    return total, was_resisted, was_vulnerable, False


def _roll_damage(
    damage_dice: str,
    damage_modifier: int,
    is_critical: bool,
    damage_type: str,
    resistances: frozenset[str],
    vulnerabilities: frozenset[str],
    immunities: frozenset[str],
    seed: int | None,
) -> DamageResult:
    """Roll damage dice and apply crit / resistance / vulnerability.

    SRD 5.2.1 p.16 (Critical Hits):
    'Roll the attack's damage dice twice, add them together, and add any
    relevant modifiers as normal.'  So we double the *dice* only; the
    modifier is added once.
    """
    dice_result = roll(damage_dice, seed=seed)

    if is_critical:
        # Roll damage dice a second time and add to first result
        extra = roll(damage_dice, seed=(seed + 1) if seed is not None else None)
        raw_dice_total = dice_result.total + extra.total
    else:
        raw_dice_total = dice_result.total

    # Damage can be 0 but not negative (SRD p.16)
    raw_total = max(0, raw_dice_total + damage_modifier)

    total, was_resisted, was_vulnerable, was_immune = _apply_resistance_vulnerability(
        raw_total, damage_type, resistances, vulnerabilities, immunities
    )

    return DamageResult(
        total=total,
        raw_total=raw_total,
        dice_result=dice_result,
        damage_type=damage_type,
        is_critical=is_critical,
        was_resisted=was_resisted,
        was_vulnerable=was_vulnerable,
        was_immune=was_immune,
    )


# ---------------------------------------------------------------------------
# Attack resolution — SRD 5.2.1 pp.14-16
# ---------------------------------------------------------------------------


def resolve_attack(
    *,
    attack_modifier: int,
    target_ac: int,
    damage_dice: str,
    damage_modifier: int,
    damage_type: str,
    advantage: bool = False,
    disadvantage: bool = False,
    target_resistances: frozenset[str] = frozenset(),
    target_vulnerabilities: frozenset[str] = frozenset(),
    target_immunities: frozenset[str] = frozenset(),
    cover_level: CoverLevel = CoverLevel.NONE,
    force_auto_crit: bool = False,
    seed: int | None = None,
) -> AttackResult:
    """Resolve a complete attack: roll, compare to AC, calculate damage.

    SRD 5.2.1 p.15 — Making an Attack:
    1. Choose a target
    2. Determine modifiers (cover, advantage/disadvantage)
    3. Resolve the attack (roll d20, compare AC, roll damage)

    SRD p.16 — Critical Hits:
    Natural 20 always hits and doubles the damage dice.

    SRD p.16 — Natural 1:
    Always misses, regardless of modifiers.

    Args:
        attack_modifier: Combined attack bonus (proficiency + ability modifier).
        target_ac: The target's Armor Class.
        damage_dice: Dice notation for damage (e.g. ``"1d8"``).
        damage_modifier: Ability modifier added to damage (may be negative).
        damage_type: Damage type string (see DamageType enum).
        advantage: Roll two d20s, take higher.
        disadvantage: Roll two d20s, take lower.
        target_resistances: Damage types the target resists.
        target_vulnerabilities: Damage types the target is vulnerable to.
        target_immunities: Damage types the target is immune to.
        cover_level: Cover bonus applied to target's effective AC.
            ``CoverLevel.TOTAL`` makes the attack impossible.
        force_auto_crit: Force a critical hit (Paralyzed / Unconscious within
            5 ft — any hit is a Critical Hit). Does not override a miss.
        seed: Optional seed for reproducibility.
    """
    if cover_level == CoverLevel.TOTAL:
        # SRD p.15: Total cover — can't be targeted directly.
        dummy_roll = roll_d20(modifier=attack_modifier, seed=seed)
        return AttackResult(
            hit=False,
            is_critical=False,
            is_critical_miss=False,
            attack_roll=dummy_roll,
            effective_ac=target_ac,
            damage=None,
            total_cover=True,
            modifiers_applied=["total_cover"],
            decision_summary="No attack — target has Total Cover",
        )

    # Cover bonus adds to effective AC (SRD p.15)
    effective_ac = target_ac + int(cover_level)

    attack_roll = roll_d20(
        modifier=attack_modifier,
        advantage=advantage,
        disadvantage=disadvantage,
        seed=seed,
    )

    # Natural 1 always misses; natural 20 always hits (SRD p.16 via D20 Test rules)
    is_critical_miss = attack_roll.is_critical_miss
    is_critical_hit = attack_roll.is_critical_hit or (
        force_auto_crit and not is_critical_miss and attack_roll.total >= effective_ac
    )

    if is_critical_miss:
        hit = False
    elif attack_roll.is_critical_hit:
        hit = True
    else:
        # Meet or exceed AC to hit (SRD p.177: 'AC is the target number')
        hit = attack_roll.total >= effective_ac

    damage: DamageResult | None = None
    if hit:
        dmg_seed = (seed + 1000) if seed is not None else None
        damage = _roll_damage(
            damage_dice=damage_dice,
            damage_modifier=damage_modifier,
            is_critical=is_critical_hit,
            damage_type=damage_type,
            resistances=target_resistances,
            vulnerabilities=target_vulnerabilities,
            immunities=target_immunities,
            seed=dmg_seed,
        )

    # Build modifiers_applied list for observability
    mods: list[str] = []
    if advantage:
        mods.append("advantage")
    if disadvantage:
        mods.append("disadvantage")
    if cover_level != CoverLevel.NONE:
        mods.append(f"cover_{cover_level.name.lower()}")
    if force_auto_crit:
        mods.append("force_auto_crit")
    if is_critical_hit and not force_auto_crit:
        mods.append("critical_hit")
    if is_critical_miss:
        mods.append("critical_miss")

    # Build decision_summary
    if is_critical_miss:
        _summary = f"Miss (natural 1) — roll {attack_roll.total} vs AC {effective_ac}"
    elif hit:
        _outcome = "Critical Hit" if is_critical_hit else "Hit"
        if damage is not None:
            _summary = (
                f"{_outcome} — {attack_roll.total} vs AC {effective_ac}, "
                f"{damage.total} {damage.damage_type} damage"
            )
        else:
            _summary = f"{_outcome} — {attack_roll.total} vs AC {effective_ac}"
    else:
        _summary = f"Miss — {attack_roll.total} vs AC {effective_ac}"

    return AttackResult(
        hit=hit,
        is_critical=is_critical_hit,
        is_critical_miss=is_critical_miss,
        attack_roll=attack_roll,
        effective_ac=effective_ac,
        damage=damage,
        modifiers_applied=mods if mods else None,
        decision_summary=_summary,
    )


# ---------------------------------------------------------------------------
# Two-weapon fighting — SRD 5.2.1 p.89 (Light weapon property)
# ---------------------------------------------------------------------------


def two_weapon_damage_modifier(
    ability_modifier: int,
    *,
    has_fighting_style: bool = False,
) -> int:
    """Return the ability modifier applied to the extra Light-weapon attack.

    SRD 5.2.1 p.89 (Light property):
    'you don't add your ability modifier to the extra attack's damage *unless*
    that modifier is negative.'

    Two-Weapon Fighting style feat (SRD p.88):
    'When you make an extra attack as a result of using a weapon that has the
    Light property, you can add your ability modifier to the damage of that
    attack if you aren't already adding it to the damage.'

    Returns:
        ``ability_modifier`` if negative or if the fighter has the style;
        ``0`` otherwise.
    """
    if has_fighting_style:
        return ability_modifier
    return min(0, ability_modifier)


# ---------------------------------------------------------------------------
# HP management — SRD 5.2.1 pp.16-18
# ---------------------------------------------------------------------------


def apply_damage(
    state: CreatureState,
    damage: int,
    *,
    is_critical: bool = False,
) -> tuple[CreatureState, DamageApplicationResult]:
    """Apply damage to a creature, handling temp HP and death mechanics.

    SRD 5.2.1 p.18 — Temporary Hit Points:
    'Lose Temporary Hit Points First. If you have Temporary Hit Points and
    take damage, those points are lost first, and any leftover damage carries
    over to your Hit Points.'

    SRD p.17 — Instant Death:
    'When damage reduces a character to 0 Hit Points and damage remains, the
    character dies if the remainder equals or exceeds their Hit Point maximum.'

    SRD p.18 — Damage at 0 Hit Points:
    'If you take any damage while you have 0 Hit Points, you suffer a Death
    Saving Throw failure. If the damage is from a Critical Hit, you suffer
    two failures instead.'
    """
    damage = max(0, damage)
    hp_before = state.current_hp
    temp_hp_before = state.temp_hp

    instant_death = False
    death_save_failures_added = 0
    dropped_to_zero = False

    # --- creature already at 0 HP ---
    if state.current_hp <= 0:
        # SRD p.18: damage at 0 HP adds death save failures
        death_save_failures_added = 2 if is_critical else 1
        instant_death = damage >= state.max_hp

        new_state = CreatureState(
            current_hp=0,
            max_hp=state.max_hp,
            temp_hp=0,
            death_save_state=state.death_save_state,
        )
        return new_state, DamageApplicationResult(
            hp_before=hp_before,
            temp_hp_before=temp_hp_before,
            hp_after=0,
            temp_hp_after=0,
            damage_to_temp_hp=0,
            damage_to_real_hp=damage,
            instant_death=instant_death,
            dropped_to_zero=False,
            death_save_failures_added=death_save_failures_added,
        )

    # --- apply to temp HP first ---
    absorbed_by_temp = min(state.temp_hp, damage)
    overflow = damage - absorbed_by_temp
    new_temp_hp = state.temp_hp - absorbed_by_temp

    # --- apply overflow to real HP ---
    new_hp = max(0, state.current_hp - overflow)
    damage_to_real_hp = state.current_hp - new_hp

    if new_hp == 0 and state.current_hp > 0:
        dropped_to_zero = True

        # SRD p.17 — Instant Death (Massive Damage)
        remaining_after_zero = overflow - state.current_hp
        instant_death = remaining_after_zero >= state.max_hp

    new_state = CreatureState(
        current_hp=new_hp,
        max_hp=state.max_hp,
        temp_hp=new_temp_hp,
        death_save_state=state.death_save_state,
    )
    return new_state, DamageApplicationResult(
        hp_before=hp_before,
        temp_hp_before=temp_hp_before,
        hp_after=new_hp,
        temp_hp_after=new_temp_hp,
        damage_to_temp_hp=absorbed_by_temp,
        damage_to_real_hp=damage_to_real_hp,
        instant_death=instant_death,
        dropped_to_zero=dropped_to_zero,
        death_save_failures_added=death_save_failures_added,
    )


def apply_healing(
    state: CreatureState,
    healing: int,
) -> tuple[CreatureState, int]:
    """Restore Hit Points, capped at maximum.

    SRD 5.2.1 p.17:
    'Your Hit Points can't exceed your Hit Point maximum, so any Hit Points
    regained in excess of the maximum are lost.'

    SRD p.18:
    'If you have 0 Hit Points, receiving Temporary Hit Points doesn't restore
    you to consciousness. Only true healing can save you.'

    Returns:
        (new_state, actual_hp_gained)
    """
    healing = max(0, healing)
    gained = min(healing, state.max_hp - state.current_hp)
    new_hp = state.current_hp + gained

    # Regaining any HP resets death saves (SRD p.17)
    new_state = CreatureState(
        current_hp=new_hp,
        max_hp=state.max_hp,
        temp_hp=state.temp_hp,
        death_save_state=DeathSaveState(),  # reset on any healing
    )
    return new_state, gained


def gain_temp_hp(
    state: CreatureState,
    temp_hp: int,
) -> CreatureState:
    """Grant temporary HP, replacing current temp HP if higher.

    SRD 5.2.1 p.18:
    'Temporary Hit Points can't be added together. If you have Temporary Hit
    Points and receive more of them, you decide whether to keep the ones you
    have or to gain the new ones.'

    This function always takes the *higher* value (optimal choice for a
    player character).
    """
    new_temp = max(state.temp_hp, temp_hp)
    return CreatureState(
        current_hp=state.current_hp,
        max_hp=state.max_hp,
        temp_hp=new_temp,
        death_save_state=state.death_save_state,
    )


# ---------------------------------------------------------------------------
# Initiative — SRD 5.2.1 p.13
# ---------------------------------------------------------------------------


def roll_initiative(
    dex_modifier: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
    seed: int | None = None,
) -> D20Result:
    """Roll Initiative: d20 + Dexterity modifier.

    SRD 5.2.1 p.13:
    'Everyone involved in the combat encounter rolls Initiative, determining
    the order of combatants' turns. … they make a Dexterity check.'

    SRD p.13 (Surprise):
    'If a combatant is surprised by combat starting, that combatant has
    Disadvantage on their Initiative roll.'
    """
    return roll_d20(
        modifier=dex_modifier,
        advantage=advantage,
        disadvantage=disadvantage,
        seed=seed,
    )


def sort_initiative_order(entries: list[InitiativeEntry]) -> list[InitiativeEntry]:
    """Sort combatants from highest Initiative to lowest.

    SRD 5.2.1 p.13:
    'The GM ranks the combatants, from highest to lowest Initiative.'

    Tie-breaking: higher Dexterity modifier goes first (SRD defers to GM/
    player choice; this engine uses DEX modifier for deterministic output).
    Equal DEX modifiers preserve insertion order (stable sort).
    """
    return sorted(
        entries,
        key=lambda e: (e.initiative, e.dex_modifier),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Surprise mechanics — SRD 5.2.1 p.13 (ADR-0014)
# ---------------------------------------------------------------------------


@dataclass
class CombatSnapshotCharacter:
    """Minimal per-character data required for Surprise determination.

    Callers (api/ or dm/ layer) are responsible for populating this from
    the full character record before calling determine_surprise.  core/
    does not import from dm/ or api/.

    SRD 5.2.1 p.13: passive Perception = 10 + WIS modifier + proficiency
    bonus if the character is proficient in Perception.
    """

    wis_modifier: int
    """Wisdom ability modifier (floor((WIS - 10) / 2))."""

    perception_proficient: bool = False
    """True if the character has Perception proficiency."""

    proficiency_bonus: int = 0
    """Character's proficiency bonus (used when perception_proficient is True)."""

    feats: list[str] = field(default_factory=list)
    """List of feat names the character possesses (e.g. ['Alert'])."""


@dataclass
class CombatSnapshot:
    """Minimal game-state snapshot required by surprise and initiative mechanics.

    Keys in ``characters`` are character_id strings (PC UUID or NPC UUID).
    Callers construct this from their full state representation before calling
    core/ surprise functions.  This keeps core/ free of dm/ and api/ imports.
    """

    characters: dict[str, CombatSnapshotCharacter] = field(default_factory=dict)
    """character_id → CombatSnapshotCharacter."""


@dataclass
class CombatParticipant:
    """One combatant's full initiative and surprise state.

    SRD 5.2.1 p.13 (ADR-0014):
    ``surprised`` is set once during combat initialisation (from
    determine_surprise), used exactly once in roll_initiative_order to apply
    Disadvantage, and never consulted again.  The flag is retained on the
    record for logging and audit purposes only.

    ``acted_this_round`` is reset at the start of each new round by the turn
    lifecycle (api/turns.py).  core/ sets it to False at initialisation.
    """

    character_id: str
    participant_type: Literal["pc", "npc"]
    initiative_roll: int
    """Raw d20 result (the lower of two if Disadvantage was applied)."""

    initiative_result: int
    """Final initiative value: initiative_roll + DEX modifier."""

    surprised: bool
    """Set once at combat init, read once in roll_initiative_order, ignored thereafter."""

    acted_this_round: bool = False


def _has_surprise_immunity(character_id: str, snapshot: CombatSnapshot) -> bool:
    """Return True if *character_id* is immune to Surprise (e.g. Alert feat).

    SRD 5.2.1 (ADR-0014 §6): Characters with the Alert feat cannot be
    surprised.  This pre-filter is the caller's responsibility — callers must
    remove immune characters from ``potential_surprised`` before passing the
    list to determine_surprise.  determine_surprise does not call this helper
    internally.

    Logs at INFO level when immunity is applied.
    """
    char = snapshot.characters.get(character_id)
    if char is None:
        return False
    # Alert feat grants immunity to Surprise (SRD 5.2.1)
    if "Alert" in char.feats:
        logger.info(
            "Character %s has Alert feat — immune to Surprise",
            character_id,
        )
        return True
    return False


def determine_surprise(
    potential_surprised: list[str],
    stealth_results: dict[str, int],
    snapshot: CombatSnapshot,
) -> dict[str, bool]:
    """Determine which characters in *potential_surprised* are actually surprised.

    SRD 5.2.1 p.13 (ADR-0014 §2):
    A target is surprised if ALL concealing characters beat (strictly greater
    than) that target's passive Perception.  If any single concealer fails to
    beat a target's passive Perception, that target is NOT surprised — one
    detected member ruins the ambush for everyone.

    Passive Perception = 10 + WIS modifier + proficiency bonus (if proficient).

    Pre-conditions (caller's responsibility, per ADR-0014 §6):
    - Characters with the Alert feat must be removed from *potential_surprised*
      before calling this function.  Use _has_surprise_immunity() as the
      pre-filter.

    Args:
        potential_surprised: character_ids of potentially surprised targets.
        stealth_results: concealing character_id → stealth total (roll + mod).
        snapshot: Minimal snapshot providing passive Perception data.

    Returns:
        dict mapping each character_id in potential_surprised to a bool.
        True = surprised (Disadvantage on initiative roll).
    """
    if not potential_surprised:
        return {}

    # No concealers → no one can be surprised
    if not stealth_results:
        return {cid: False for cid in potential_surprised}

    concealer_rolls = list(stealth_results.values())

    result: dict[str, bool] = {}
    for target_id in potential_surprised:
        char = snapshot.characters.get(target_id)
        if char is None:
            # Unknown character: cannot compute passive Perception → not surprised
            result[target_id] = False
            continue

        # Passive Perception = 10 + WIS modifier [+ proficiency bonus if proficient]
        passive_perception = 10 + char.wis_modifier
        if char.perception_proficient:
            passive_perception += char.proficiency_bonus

        # All concealers must strictly beat the target's passive Perception
        # for that target to be surprised.  One failure = not surprised.
        all_beat = all(stealth > passive_perception for stealth in concealer_rolls)
        result[target_id] = all_beat

    return result


def roll_initiative_order(
    participants: list[CombatParticipant],
    *,
    surprised_map: dict[str, bool] | None = None,
    dex_modifiers: dict[str, int] | None = None,
    seeds: dict[str, int] | None = None,
) -> list[CombatParticipant]:
    """Roll initiative for all participants, applying Disadvantage to surprised ones.

    SRD 5.2.1 p.13 (ADR-0014 §4):
    Surprised participants roll initiative with Disadvantage (two d20s, take
    the lower result).  Both d20 values are logged.  Non-surprised participants
    roll one d20 normally.

    Args:
        participants: List of CombatParticipant records (surprised flag is read
            from each participant and/or from surprised_map if provided).
        surprised_map: Optional override map of character_id → surprised bool.
            If provided, values here take precedence over participant.surprised.
        dex_modifiers: character_id → DEX modifier.  Defaults to 0 for any
            participant not present in the map.
        seeds: character_id → seed for reproducible rolls.

    Returns:
        A new list of CombatParticipant records sorted by initiative_result
        descending (highest first).  Input records are NOT mutated.
    """
    if surprised_map is None:
        surprised_map = {}
    if dex_modifiers is None:
        dex_modifiers = {}
    if seeds is None:
        seeds = {}

    updated: list[CombatParticipant] = []
    for p in participants:
        is_surprised = surprised_map.get(p.character_id, p.surprised)
        dex_mod = dex_modifiers.get(p.character_id, 0)
        seed = seeds.get(p.character_id, None)

        if is_surprised:
            d20_result = roll_d20(modifier=dex_mod, disadvantage=True, seed=seed)
            logger.debug(
                "Initiative (Disadvantage — Surprised): %s rolled %s, took %d; result %d",
                p.character_id,
                d20_result.all_rolls,
                d20_result.natural,
                d20_result.total,
            )
        else:
            d20_result = roll_d20(modifier=dex_mod, seed=seed)
            logger.debug(
                "Initiative: %s rolled %d; result %d",
                p.character_id,
                d20_result.natural,
                d20_result.total,
            )

        updated.append(
            CombatParticipant(
                character_id=p.character_id,
                participant_type=p.participant_type,
                initiative_roll=d20_result.natural,
                initiative_result=d20_result.total,
                surprised=is_surprised,
                acted_this_round=p.acted_this_round,
            )
        )

    return sorted(updated, key=lambda p: p.initiative_result, reverse=True)


# ---------------------------------------------------------------------------
# Death Saving Throws — SRD 5.2.1 pp.17-18
# ---------------------------------------------------------------------------


def roll_death_save(
    state: DeathSaveState,
    seed: int | None = None,
) -> DeathSaveResult:
    """Roll a Death Saving Throw and update state.

    SRD 5.2.1 p.17-18:
    - Roll 1d20 (no modifiers)
    - 10+ = 1 success; 9- = 1 failure
    - Natural 20 = regain 1 HP (resets death saves)
    - Natural 1  = 2 failures
    - 3 successes = Stable
    - 3 failures  = Dead
    """
    d20 = roll_d20(seed=seed)
    natural = d20.natural

    failures_added = 0
    regained_hp = 0
    success = False

    new_successes = state.successes
    new_failures = state.failures

    if natural == 20:
        # SRD p.18: regain 1 HP — effectively a "super-success"
        regained_hp = 1
        outcome = "regained_hp"
        new_state = DeathSaveState()  # reset completely
        return DeathSaveResult(
            roll=d20,
            success=True,
            failures_added=0,
            regained_hp=1,
            state_after=new_state,
            outcome="regained_hp",
        )
    elif natural == 1:
        # SRD p.18: natural 1 = two failures
        failures_added = 2
        new_failures = min(3, state.failures + 2)
    elif natural >= 10:
        success = True
        new_successes = min(3, state.successes + 1)
    else:
        failures_added = 1
        new_failures = min(3, state.failures + 1)

    is_dead = new_failures >= 3
    is_stable = new_successes >= 3 and not is_dead

    new_state = DeathSaveState(
        successes=new_successes,
        failures=new_failures,
        is_stable=is_stable,
        is_dead=is_dead,
    )

    if is_dead:
        outcome = "dead"
    elif is_stable:
        outcome = "stabilized"
    else:
        outcome = "continue"

    return DeathSaveResult(
        roll=d20,
        success=success,
        failures_added=failures_added,
        regained_hp=regained_hp,
        state_after=new_state,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Grapple and Shove — SRD 5.2.1 Rules Glossary p.190 (Unarmed Strike)
# ---------------------------------------------------------------------------


def _unarmed_strike_dc(
    attacker_str_modifier: int,
    attacker_proficiency_bonus: int,
) -> int:
    """SRD p.190: DC = 8 + Strength modifier + Proficiency Bonus."""
    return 8 + attacker_str_modifier + attacker_proficiency_bonus


def attempt_grapple(
    attacker_str_modifier: int,
    attacker_proficiency_bonus: int,
    target_str_modifier: int,
    target_dex_modifier: int,
    *,
    target_uses_dex: bool = False,
    seed: int | None = None,
) -> GrappleResult:
    """Attempt to grapple a target using an Unarmed Strike.

    SRD 5.2.1 Rules Glossary p.190:
    'The target must succeed on a Strength or Dexterity saving throw (it
    chooses which), or it has the Grappled condition. The DC equals 8 plus
    your Strength modifier and Proficiency Bonus.'

    Args:
        attacker_str_modifier: Attacker's STR ability modifier.
        attacker_proficiency_bonus: Attacker's proficiency bonus.
        target_str_modifier: Target's STR modifier (used when target chooses STR).
        target_dex_modifier: Target's DEX modifier (used when target chooses DEX).
        target_uses_dex: If True, target rolls DEX; otherwise STR.
        seed: Optional seed.

    Returns:
        GrappleResult where ``grappled=True`` means the target failed the save.
    """
    dc = _unarmed_strike_dc(attacker_str_modifier, attacker_proficiency_bonus)
    save_mod = target_dex_modifier if target_uses_dex else target_str_modifier
    target_save = roll_d20(modifier=save_mod, seed=seed)

    # Target succeeds if total >= DC
    save_succeeded = target_save.total >= dc
    return GrappleResult(
        dc=dc,
        target_save=target_save,
        grappled=not save_succeeded,
    )


def attempt_shove(
    attacker_str_modifier: int,
    attacker_proficiency_bonus: int,
    target_str_modifier: int,
    target_dex_modifier: int,
    *,
    target_uses_dex: bool = False,
    effect: str = "push",
    seed: int | None = None,
) -> ShoveResult:
    """Attempt to shove a target using an Unarmed Strike.

    SRD 5.2.1 Rules Glossary p.190:
    'The target must succeed on a Strength or Dexterity saving throw (it
    chooses which), or you either push it 5 feet away or cause it to have the
    Prone condition. The DC equals 8 plus your Strength modifier and
    Proficiency Bonus.'

    Args:
        effect: ``"push"`` to push 5 feet, or ``"prone"`` to knock prone.
    """
    if effect not in ("push", "prone"):
        raise ValueError(f"effect must be 'push' or 'prone', got {effect!r}")

    dc = _unarmed_strike_dc(attacker_str_modifier, attacker_proficiency_bonus)
    save_mod = target_dex_modifier if target_uses_dex else target_str_modifier
    target_save = roll_d20(modifier=save_mod, seed=seed)

    save_succeeded = target_save.total >= dc
    failed = not save_succeeded

    return ShoveResult(
        dc=dc,
        target_save=target_save,
        pushed_5ft=failed and effect == "push",
        knocked_prone=failed and effect == "prone",
    )


# ---------------------------------------------------------------------------
# Opportunity Attacks — SRD 5.2.1 p.15
# ---------------------------------------------------------------------------


def triggers_opportunity_attack(
    *,
    leaving_reach: bool = True,
    used_disengage: bool = False,
    is_teleporting: bool = False,
    moved_by_external_force: bool = False,
) -> bool:
    """Return True if the creature's movement triggers an Opportunity Attack.

    SRD 5.2.1 p.15:
    'You can make an Opportunity Attack when a creature that you can see
    leaves your reach.'

    'Avoiding Opportunity Attacks. You can avoid provoking an Opportunity
    Attack by taking the Disengage action. You also don't provoke an
    Opportunity Attack when you Teleport or when you are moved without using
    your movement, action, Bonus Action, or Reaction.'
    """
    if not leaving_reach:
        return False
    if used_disengage:
        return False
    if is_teleporting:
        return False
    if moved_by_external_force:
        return False
    return True


# ---------------------------------------------------------------------------
# Concentration saving throw — SRD 5.2.1 p.179
# ---------------------------------------------------------------------------


def roll_concentration_save(
    damage_taken: int,
    con_modifier: int,
    *,
    proficiency_bonus: int = 0,
    is_proficient: bool = False,
    seed: int | None = None,
) -> D20Result:
    """Roll a Constitution save to maintain Concentration.

    SRD 5.2.1 p.179:
    'If you take damage, you must succeed on a Constitution saving throw to
    maintain Concentration. The DC equals 10 or half the damage taken
    (round down), whichever number is higher, up to a maximum DC of 30.'

    Note: The return value is a D20Result; the caller compares
    ``result.total`` against the DC (computed here and embedded in context).
    This function returns the roll; the DC is also returned via the
    ``concentration_save_dc`` helper.
    """
    bonus = con_modifier + (proficiency_bonus if is_proficient else 0)
    return roll_d20(modifier=bonus, seed=seed)


def concentration_save_dc(damage_taken: int) -> int:
    """Return the DC for a Concentration saving throw.

    SRD 5.2.1 p.179: DC = max(10, damage_taken // 2), capped at 30.
    """
    return min(30, max(10, damage_taken // 2))


# ---------------------------------------------------------------------------
# Cover bonus to Dexterity saving throws — SRD 5.2.1 p.15
# ---------------------------------------------------------------------------


def cover_dex_save_bonus(cover_level: CoverLevel) -> int:
    """Return the DEX saving throw bonus granted by cover.

    SRD 5.2.1 p.15: Half cover +2, Three-quarters +5, Total = irrelevant
    (can't be targeted). The bonus is the same value as the AC bonus.
    """
    if cover_level in (CoverLevel.HALF, CoverLevel.THREE_QUARTERS):
        return int(cover_level)
    return 0
