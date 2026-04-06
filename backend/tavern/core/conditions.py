"""Condition state machine for the SRD 5.2.1 Rules Engine.

All 15 conditions defined in the SRD 5.2.1 Rules Glossary (pp. 178–191).
Each condition is modelled with its exact mechanical effects.

Five public query functions answer the mechanically relevant questions:

1. ``attack_roll_modifiers``   — what modifiers apply to the *attacker's* roll?
2. ``attacks_against_modifiers`` — what modifiers apply to rolls *against* this creature?
3. ``saving_throw_modifiers``  — what modifiers apply to this creature's saving throws?
4. ``can_act``                 — can this creature take actions / bonus actions / reactions?
5. ``effective_speed``         — what is this creature's effective speed?

Condition interactions per SRD:
- Paralyzed  → also has Incapacitated (p.186)
- Petrified  → also has Incapacitated (p.186)
- Stunned    → also has Incapacitated (p.188)
- Unconscious → also has Incapacitated + Prone (p.191)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Condition names — exact SRD 5.2.1 names (Rules Glossary pp. 178-191)
# ---------------------------------------------------------------------------


class ConditionName(StrEnum):
    """All 15 conditions defined in SRD 5.2.1 Rules Glossary p.179."""

    BLINDED = "Blinded"
    CHARMED = "Charmed"
    DEAFENED = "Deafened"
    EXHAUSTION = "Exhaustion"
    FRIGHTENED = "Frightened"
    GRAPPLED = "Grappled"
    INCAPACITATED = "Incapacitated"
    INVISIBLE = "Invisible"
    PARALYZED = "Paralyzed"
    PETRIFIED = "Petrified"
    POISONED = "Poisoned"
    PRONE = "Prone"
    RESTRAINED = "Restrained"
    STUNNED = "Stunned"
    UNCONSCIOUS = "Unconscious"


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------


class DurationKind(StrEnum):
    ROUNDS = "rounds"
    INDEFINITE = "indefinite"


# ---------------------------------------------------------------------------
# Active condition instance
# ---------------------------------------------------------------------------


@dataclass
class ActiveCondition:
    """A condition currently affecting a creature.

    ``exhaustion_level`` is only meaningful when ``name == EXHAUSTION``.
    It must be in 1–6; the creature dies at level 6 (SRD p.181).
    """

    name: ConditionName
    duration_kind: DurationKind = DurationKind.INDEFINITE
    remaining_rounds: int | None = None
    exhaustion_level: int = 0

    @classmethod
    def indefinite(cls, name: ConditionName) -> ActiveCondition:
        """Create a condition that lasts until explicitly removed."""
        return cls(name=name, duration_kind=DurationKind.INDEFINITE)

    @classmethod
    def for_rounds(cls, name: ConditionName, rounds: int) -> ActiveCondition:
        """Create a condition that expires after *rounds* rounds."""
        if rounds < 1:
            raise ValueError(f"rounds must be >= 1, got {rounds}")
        return cls(name=name, duration_kind=DurationKind.ROUNDS, remaining_rounds=rounds)

    @classmethod
    def exhaustion(cls, level: int) -> ActiveCondition:
        """SRD p.181: Exhaustion is cumulative; die at level 6."""
        if not 1 <= level <= 6:
            raise ValueError(f"Exhaustion level must be 1–6, got {level}")
        return cls(
            name=ConditionName.EXHAUSTION,
            duration_kind=DurationKind.INDEFINITE,
            exhaustion_level=level,
        )

    def decrement_round(self) -> ActiveCondition | None:
        """Return the updated condition after one round, or None if expired."""
        if self.duration_kind != DurationKind.ROUNDS:
            return self
        assert self.remaining_rounds is not None
        new_rounds = self.remaining_rounds - 1
        if new_rounds <= 0:
            return None
        return ActiveCondition(
            name=self.name,
            duration_kind=DurationKind.ROUNDS,
            remaining_rounds=new_rounds,
            exhaustion_level=self.exhaustion_level,
        )


# ---------------------------------------------------------------------------
# Condition interaction: implied conditions
# ---------------------------------------------------------------------------


def effective_conditions(conditions: list[ActiveCondition]) -> frozenset[ConditionName]:
    """Expand explicit conditions to include all implied conditions.

    SRD implied-condition rules:
    - Paralyzed  → Incapacitated (p.186)
    - Petrified  → Incapacitated (p.186)
    - Stunned    → Incapacitated (p.188)
    - Unconscious → Incapacitated + Prone (p.191)
    """
    names: set[ConditionName] = {c.name for c in conditions}

    if ConditionName.PARALYZED in names:
        names.add(ConditionName.INCAPACITATED)
    if ConditionName.PETRIFIED in names:
        names.add(ConditionName.INCAPACITATED)
    if ConditionName.STUNNED in names:
        names.add(ConditionName.INCAPACITATED)
    if ConditionName.UNCONSCIOUS in names:
        names.add(ConditionName.INCAPACITATED)
        names.add(ConditionName.PRONE)

    return frozenset(names)


def _get_exhaustion_level(conditions: list[ActiveCondition]) -> int:
    for c in conditions:
        if c.name == ConditionName.EXHAUSTION:
            return c.exhaustion_level
    return 0


# ---------------------------------------------------------------------------
# Query result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AttackRollModifiers:
    """Modifiers applied to this creature's *own* attack rolls.

    Advantage and disadvantage cancel each other (SRD p.181).
    Callers should check ``net_advantage`` / ``net_disadvantage`` for the
    resolved result.
    """

    advantage_sources: list[str] = field(default_factory=list)
    disadvantage_sources: list[str] = field(default_factory=list)
    d20_penalty: int = 0  # Exhaustion: −2 × level subtracted from roll
    modifiers_applied: list[str] | None = None
    """Flat list of all active modifier descriptions for observability."""

    @property
    def has_advantage(self) -> bool:
        return bool(self.advantage_sources)

    @property
    def has_disadvantage(self) -> bool:
        return bool(self.disadvantage_sources)

    @property
    def net_advantage(self) -> bool:
        """True if the roll uses advantage (adv without disadv)."""
        return self.has_advantage and not self.has_disadvantage

    @property
    def net_disadvantage(self) -> bool:
        """True if the roll uses disadvantage (disadv without adv)."""
        return self.has_disadvantage and not self.has_advantage


@dataclass
class AttacksAgainstModifiers:
    """Modifiers applied to attack rolls *against* this creature.

    ``melee_auto_crit_within_5ft``: any hit by an attacker within 5 feet is
    a Critical Hit (Paralyzed p.186, Unconscious p.191).
    """

    advantage_sources: list[str] = field(default_factory=list)
    disadvantage_sources: list[str] = field(default_factory=list)
    melee_auto_crit_within_5ft: bool = False
    modifiers_applied: list[str] | None = None
    """Flat list of all active modifier descriptions for observability."""

    @property
    def has_advantage(self) -> bool:
        return bool(self.advantage_sources)

    @property
    def has_disadvantage(self) -> bool:
        return bool(self.disadvantage_sources)

    @property
    def net_advantage(self) -> bool:
        return self.has_advantage and not self.has_disadvantage

    @property
    def net_disadvantage(self) -> bool:
        return self.has_disadvantage and not self.has_advantage


@dataclass
class SavingThrowModifiers:
    """Modifiers applied to this creature's saving throws.

    ``auto_fail_abilities``: saving throws using these abilities automatically
    fail (Paralyzed / Petrified / Stunned / Unconscious → STR + DEX).

    ``d20_penalty``: Exhaustion subtracts 2 × level from every D20 Test,
    including saving throws.
    """

    auto_fail_abilities: list[str] = field(default_factory=list)
    disadvantage_sources: list[str] = field(default_factory=list)
    d20_penalty: int = 0

    @property
    def has_disadvantage(self) -> bool:
        return bool(self.disadvantage_sources)

    def auto_fails(self, ability: str) -> bool:
        """Return True if saves using *ability* automatically fail."""
        return ability.upper() in [a.upper() for a in self.auto_fail_abilities]


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------


def attack_roll_modifiers(
    conditions: list[ActiveCondition],
    *,
    fear_source_visible: bool = False,
) -> AttackRollModifiers:
    """Return modifiers that apply to this creature's own attack rolls.

    Args:
        conditions: The creature's currently active conditions.
        fear_source_visible: Whether the source of Frightened is in line of
            sight. Frightened imposes Disadvantage only while the source is
            visible (SRD p.182).

    Note on Grappled:
        SRD p.182: Grappled imposes Disadvantage against targets *other than
        the grappler*. The caller must apply this contextually; it is not
        included here.
    """
    eff = effective_conditions(conditions)
    adv: list[str] = []
    dis: list[str] = []

    # Blinded: Disadvantage on attack rolls (SRD p.177)
    if ConditionName.BLINDED in eff:
        dis.append("Blinded")

    # Frightened: Disadvantage while source of fear in line of sight (SRD p.182)
    if ConditionName.FRIGHTENED in eff and fear_source_visible:
        dis.append("Frightened (source visible)")

    # Invisible: Advantage on attack rolls (SRD p.185)
    if ConditionName.INVISIBLE in eff:
        adv.append("Invisible")

    # Poisoned: Disadvantage on attack rolls and ability checks (SRD p.187)
    if ConditionName.POISONED in eff:
        dis.append("Poisoned")

    # Prone: Disadvantage on attack rolls (SRD p.187)
    if ConditionName.PRONE in eff:
        dis.append("Prone")

    # Restrained: Disadvantage on attack rolls (SRD p.187)
    if ConditionName.RESTRAINED in eff:
        dis.append("Restrained")

    exhaustion_level = _get_exhaustion_level(conditions)
    penalty = 2 * exhaustion_level  # SRD p.181: d20 test reduced by 2 × level

    mods: list[str] = list(adv) + list(dis)
    if penalty:
        mods.append(f"exhaustion_penalty_-{penalty}")

    return AttackRollModifiers(
        advantage_sources=adv,
        disadvantage_sources=dis,
        d20_penalty=penalty,
        modifiers_applied=mods if mods else None,
    )


def attacks_against_modifiers(
    conditions: list[ActiveCondition],
    *,
    attacker_within_5ft: bool = False,
) -> AttacksAgainstModifiers:
    """Return modifiers that apply to attack rolls *against* this creature.

    Args:
        conditions: The creature's currently active conditions.
        attacker_within_5ft: Whether the attacker is within 5 feet. Required
            for Prone (melee advantage / ranged disadvantage) and for
            determining auto-crit eligibility.

    Note on Prone:
        SRD p.187: Against a Prone creature, attack rolls have Advantage if
        attacker is within 5 feet; otherwise Disadvantage. This function
        applies both based on ``attacker_within_5ft``.
    """
    eff = effective_conditions(conditions)
    adv: list[str] = []
    dis: list[str] = []
    auto_crit = False

    # Blinded: attack rolls against have Advantage (SRD p.177)
    if ConditionName.BLINDED in eff:
        adv.append("target is Blinded")

    # Invisible: attack rolls against have Disadvantage (SRD p.185)
    if ConditionName.INVISIBLE in eff:
        dis.append("target is Invisible")

    # Paralyzed: Advantage on all attacks; auto-crit within 5ft (SRD p.186)
    if ConditionName.PARALYZED in eff:
        adv.append("target is Paralyzed")
        if attacker_within_5ft:
            auto_crit = True

    # Petrified: Advantage on all attacks (SRD p.186)
    if ConditionName.PETRIFIED in eff:
        adv.append("target is Petrified")

    # Prone: Advantage within 5ft, Disadvantage otherwise (SRD p.187)
    if ConditionName.PRONE in eff:
        if attacker_within_5ft:
            adv.append("target is Prone (attacker within 5 ft)")
        else:
            dis.append("target is Prone (attacker beyond 5 ft)")

    # Restrained: attack rolls against have Advantage (SRD p.187)
    if ConditionName.RESTRAINED in eff:
        adv.append("target is Restrained")

    # Stunned: attack rolls against have Advantage (SRD p.189)
    if ConditionName.STUNNED in eff:
        adv.append("target is Stunned")

    # Unconscious: Advantage + auto-crit within 5ft (SRD p.191)
    if ConditionName.UNCONSCIOUS in eff:
        adv.append("target is Unconscious")
        if attacker_within_5ft:
            auto_crit = True

    mods: list[str] = list(adv) + list(dis)
    if auto_crit:
        mods.append("melee_auto_crit_within_5ft")

    return AttacksAgainstModifiers(
        advantage_sources=adv,
        disadvantage_sources=dis,
        melee_auto_crit_within_5ft=auto_crit,
        modifiers_applied=mods if mods else None,
    )


def saving_throw_modifiers(
    conditions: list[ActiveCondition],
    *,
    ability: str | None = None,
) -> SavingThrowModifiers:
    """Return modifiers that apply to this creature's saving throws.

    Args:
        conditions: The creature's currently active conditions.
        ability: The ability score governing the save (e.g. ``"STR"``,
            ``"DEX"``). Used to determine auto-fail. When None, the
            auto_fail_abilities list is returned for the caller to evaluate.

    Note on Frightened:
        SRD p.182: Frightened imposes Disadvantage on *ability checks* and
        attack rolls, not on saving throws. It is NOT included here.

    SRD p.183 (Help action) and concentration saves are not reflected here —
    those are context-dependent bonuses handled in combat.py.
    """
    eff = effective_conditions(conditions)
    auto_fail: list[str] = []
    dis: list[str] = []

    # Paralyzed: auto-fail STR and DEX saves (SRD p.186)
    if ConditionName.PARALYZED in eff:
        for ab in ("STR", "DEX"):
            if ab not in auto_fail:
                auto_fail.append(ab)

    # Petrified: auto-fail STR and DEX saves (SRD p.186)
    if ConditionName.PETRIFIED in eff:
        for ab in ("STR", "DEX"):
            if ab not in auto_fail:
                auto_fail.append(ab)

    # Stunned: auto-fail STR and DEX saves (SRD p.189)
    if ConditionName.STUNNED in eff:
        for ab in ("STR", "DEX"):
            if ab not in auto_fail:
                auto_fail.append(ab)

    # Unconscious: auto-fail STR and DEX saves (SRD p.191)
    if ConditionName.UNCONSCIOUS in eff:
        for ab in ("STR", "DEX"):
            if ab not in auto_fail:
                auto_fail.append(ab)

    # Restrained: Disadvantage on DEX saves (SRD p.187)
    if ConditionName.RESTRAINED in eff:
        dis.append("Restrained (DEX saves)")

    exhaustion_level = _get_exhaustion_level(conditions)
    penalty = 2 * exhaustion_level

    result = SavingThrowModifiers(
        auto_fail_abilities=auto_fail,
        disadvantage_sources=dis,
        d20_penalty=penalty,
    )

    # If specific ability provided, filter disadvantage to only applicable ones
    # (Restrained only affects DEX)
    if ability is not None:
        filtered_dis: list[str] = []
        if ConditionName.RESTRAINED in eff and ability.upper() == "DEX":
            filtered_dis.append("Restrained (DEX saves)")
        result = SavingThrowModifiers(
            auto_fail_abilities=auto_fail,
            disadvantage_sources=filtered_dis,
            d20_penalty=penalty,
        )

    return result


def can_act(conditions: list[ActiveCondition]) -> bool:
    """Return False if this creature cannot take actions, Bonus Actions, or Reactions.

    SRD p.184 (Incapacitated):
    'You can't take any action, Bonus Action, or Reaction.'

    Incapacitated is also implied by Paralyzed, Petrified, Stunned, and
    Unconscious (effective_conditions handles this expansion).
    """
    return ConditionName.INCAPACITATED not in effective_conditions(conditions)


def initiative_roll_modifiers(conditions: list[ActiveCondition]) -> AttackRollModifiers:
    """Return modifiers that apply to this creature's Initiative roll.

    SRD p.184 (Incapacitated): 'If you're Incapacitated when you roll
    Initiative, you have Disadvantage on the roll.'
    SRD p.185 (Invisible): 'If you're Invisible when you roll Initiative,
    you have Advantage on the roll.'
    """
    eff = effective_conditions(conditions)
    adv: list[str] = []
    dis: list[str] = []

    if ConditionName.INCAPACITATED in eff:
        dis.append("Incapacitated")
    if ConditionName.INVISIBLE in eff:
        adv.append("Invisible")

    exhaustion_level = _get_exhaustion_level(conditions)
    penalty = 2 * exhaustion_level

    mods: list[str] = list(adv) + list(dis)
    if penalty:
        mods.append(f"exhaustion_penalty_-{penalty}")

    return AttackRollModifiers(
        advantage_sources=adv,
        disadvantage_sources=dis,
        d20_penalty=penalty,
        modifiers_applied=mods if mods else None,
    )


def effective_speed(
    conditions: list[ActiveCondition],
    base_speed: int,
) -> int:
    """Return this creature's effective speed after condition penalties.

    Speed-zeroing conditions (SRD):
    - Grappled   p.182: Speed 0 and can't increase
    - Paralyzed  p.186: Speed 0 and can't increase
    - Petrified  p.186: Speed 0 and can't increase
    - Restrained p.187: Speed 0 and can't increase
    - Unconscious p.191: Speed 0 and can't increase

    Stunned does NOT reduce speed (SRD p.189 — only Incapacitated + STR/DEX
    auto-fail + attacks with Advantage; no Speed 0 listed).

    Exhaustion p.181: Speed reduced by 5 × exhaustion_level.

    Prone p.187: Does not reduce Speed (movement modes change, but Speed
    itself is unchanged — standing up costs half Speed).

    The returned value is always >= 0.
    """
    eff = effective_conditions(conditions)

    speed_zero_conditions = {
        ConditionName.GRAPPLED,
        ConditionName.PARALYZED,
        ConditionName.PETRIFIED,
        ConditionName.RESTRAINED,
        ConditionName.UNCONSCIOUS,
    }
    if speed_zero_conditions & eff:
        return 0

    speed = base_speed
    exhaustion_level = _get_exhaustion_level(conditions)
    speed = max(0, speed - 5 * exhaustion_level)

    return speed


def ability_check_modifiers(
    conditions: list[ActiveCondition],
    *,
    fear_source_visible: bool = False,
) -> AttackRollModifiers:
    """Return modifiers that apply to this creature's ability checks.

    Poisoned: Disadvantage on ability checks (SRD p.187).
    Frightened: Disadvantage while source of fear is in line of sight (SRD p.182).
    Exhaustion: −2 × level to all D20 Tests including ability checks (SRD p.181).

    Note: Blinded auto-fails checks *that require sight*; this is handled by
    the caller who knows what the check requires.
    """
    eff = effective_conditions(conditions)
    adv: list[str] = []
    dis: list[str] = []

    if ConditionName.POISONED in eff:
        dis.append("Poisoned")

    if ConditionName.FRIGHTENED in eff and fear_source_visible:
        dis.append("Frightened (source visible)")

    exhaustion_level = _get_exhaustion_level(conditions)
    penalty = 2 * exhaustion_level

    mods: list[str] = list(adv) + list(dis)
    if penalty:
        mods.append(f"exhaustion_penalty_-{penalty}")

    return AttackRollModifiers(
        advantage_sources=adv,
        disadvantage_sources=dis,
        d20_penalty=penalty,
        modifiers_applied=mods if mods else None,
    )


def concentration_is_broken(conditions: list[ActiveCondition]) -> bool:
    """Return True if this creature's Concentration is broken by conditions.

    SRD p.179: 'Your Concentration ends if you have the Incapacitated
    condition or you die.'
    """
    return ConditionName.INCAPACITATED in effective_conditions(conditions)
