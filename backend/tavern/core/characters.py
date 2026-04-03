"""Character mechanics for the SRD 5.2.1 Rules Engine.

Covers ability scores, proficiency bonuses, hit points, spell slot tables,
XP/level progression, and multiclass prerequisites.  All tables are sourced
verbatim from the SRD 5.2.1 PDF — do not edit constants without re-verifying
against the source.

SRD 5.2.1 note: Paladin and Ranger gain spell slots from level 1 (changed
from the 2014 PHB).  For multiclassing purposes their levels still count as
half (rounded up) per page 25 of the SRD.
"""

import math
from typing import Final

# ---------------------------------------------------------------------------
# Hit dice (SRD 5.2.1 — class core trait tables)
# ---------------------------------------------------------------------------

HIT_DICE: Final[dict[str, int]] = {
    "Barbarian": 12,
    "Fighter": 10,
    "Paladin": 10,
    "Ranger": 10,
    "Bard": 8,
    "Cleric": 8,
    "Druid": 8,
    "Monk": 8,
    "Rogue": 8,
    "Warlock": 8,
    "Sorcerer": 6,
    "Wizard": 6,
}

# ---------------------------------------------------------------------------
# XP thresholds — Character Advancement table (SRD 5.2.1 p.23)
# Index i is the XP required to reach level i+1.
# ---------------------------------------------------------------------------

XP_THRESHOLDS: Final[list[int]] = [
    0,  # level 1
    300,  # level 2
    900,  # level 3
    2700,  # level 4
    6500,  # level 5
    14000,  # level 6
    23000,  # level 7
    34000,  # level 8
    48000,  # level 9
    64000,  # level 10
    85000,  # level 11
    100000,  # level 12
    120000,  # level 13
    140000,  # level 14
    165000,  # level 15
    195000,  # level 16
    225000,  # level 17
    265000,  # level 18
    305000,  # level 19
    355000,  # level 20
]

# ---------------------------------------------------------------------------
# Multiclass prerequisites — primary abilities per class (SRD 5.2.1 p.24)
# All listed abilities must be ≥ 13 for the class to be eligible.
# ---------------------------------------------------------------------------

PRIMARY_ABILITIES: Final[dict[str, list[str]]] = {
    "Barbarian": ["STR"],
    "Bard": ["CHA"],
    "Cleric": ["WIS"],
    "Druid": ["WIS"],
    "Fighter": ["STR"],  # STR or DEX in full rules; STR used here
    "Monk": ["DEX", "WIS"],
    "Paladin": ["STR", "CHA"],
    "Ranger": ["DEX", "WIS"],
    "Rogue": ["DEX"],
    "Sorcerer": ["CHA"],
    "Warlock": ["CHA"],
    "Wizard": ["INT"],
}

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Point buy cost table (SRD 5.2.1 p.21)
_POINT_BUY_COSTS: Final[dict[int, int]] = {
    8: 0,
    9: 1,
    10: 2,
    11: 3,
    12: 4,
    13: 5,
    14: 7,
    15: 9,
}
_POINT_BUY_BUDGET: Final[int] = 27

# Fixed HP gained per level (SRD 5.2.1 p.23 "Fixed Hit Points by Class")
_FIXED_HP_PER_LEVEL: Final[dict[str, int]] = {
    "Barbarian": 7,
    "Fighter": 6,
    "Paladin": 6,
    "Ranger": 6,
    "Bard": 5,
    "Cleric": 5,
    "Druid": 5,
    "Monk": 5,
    "Rogue": 5,
    "Warlock": 5,
    "Sorcerer": 4,
    "Wizard": 4,
}

# Full casters: Bard, Cleric, Druid, Sorcerer, Wizard all share this table.
# Sourced from the class feature tables in SRD 5.2.1.
# Index i = class level i+1 (index 0 = level 1).
_FULL_CASTER_SLOTS: Final[list[dict[int, int]]] = [
    {1: 2},  # level 1
    {1: 3},  # level 2
    {1: 4, 2: 2},  # level 3
    {1: 4, 2: 3},  # level 4
    {1: 4, 2: 3, 3: 2},  # level 5
    {1: 4, 2: 3, 3: 3},  # level 6
    {1: 4, 2: 3, 3: 3, 4: 1},  # level 7
    {1: 4, 2: 3, 3: 3, 4: 2},  # level 8
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # level 9
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # level 10
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},  # level 11
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},  # level 12
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},  # level 13
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},  # level 14
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},  # level 15
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},  # level 16
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},  # level 17
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},  # level 18
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},  # level 19
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},  # level 20
]

# Paladin and Ranger share an identical spell slot progression in SRD 5.2.1.
# Both gain slots from level 1 (unlike the 2014 PHB half-caster that started
# at level 2).  For multiclassing, their levels still count as half (p.25).
_HALF_CASTER_SLOTS: Final[list[dict[int, int]]] = [
    {1: 2},  # level 1
    {1: 2},  # level 2
    {1: 3},  # level 3
    {1: 3},  # level 4
    {1: 4, 2: 2},  # level 5
    {1: 4, 2: 2},  # level 6
    {1: 4, 2: 3},  # level 7
    {1: 4, 2: 3},  # level 8
    {1: 4, 2: 3, 3: 2},  # level 9
    {1: 4, 2: 3, 3: 2},  # level 10
    {1: 4, 2: 3, 3: 3},  # level 11
    {1: 4, 2: 3, 3: 3},  # level 12
    {1: 4, 2: 3, 3: 3, 4: 1},  # level 13
    {1: 4, 2: 3, 3: 3, 4: 1},  # level 14
    {1: 4, 2: 3, 3: 3, 4: 2},  # level 15
    {1: 4, 2: 3, 3: 3, 4: 2},  # level 16
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # level 17
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # level 18
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # level 19
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},  # level 20
]

# Warlock Pact Magic (SRD 5.2.1 p.71)
# Each entry: (num_slots, slot_level) at the corresponding class level.
_WARLOCK_PACT_MAGIC: Final[list[tuple[int, int]]] = [
    (1, 1),  # level 1
    (2, 1),  # level 2
    (2, 2),  # level 3
    (2, 2),  # level 4
    (2, 3),  # level 5
    (2, 3),  # level 6
    (2, 4),  # level 7
    (2, 4),  # level 8
    (2, 5),  # level 9
    (2, 5),  # level 10
    (3, 5),  # level 11
    (3, 5),  # level 12
    (3, 5),  # level 13
    (3, 5),  # level 14
    (3, 5),  # level 15
    (3, 5),  # level 16
    (4, 5),  # level 17
    (4, 5),  # level 18
    (4, 5),  # level 19
    (4, 5),  # level 20
]

# Multiclass Spellcaster table (SRD 5.2.1 p.26).
# Identical to the full caster table — both indexed by combined caster level.
_MULTICLASS_SLOTS: Final[list[dict[int, int]]] = _FULL_CASTER_SLOTS

_FULL_CASTERS: Final[frozenset[str]] = frozenset({"Bard", "Cleric", "Druid", "Sorcerer", "Wizard"})
_HALF_CASTERS: Final[frozenset[str]] = frozenset({"Paladin", "Ranger"})
_NON_CASTERS: Final[frozenset[str]] = frozenset({"Barbarian", "Fighter", "Monk", "Rogue"})
_ALL_CLASSES: Final[frozenset[str]] = (
    _FULL_CASTERS | _HALF_CASTERS | _NON_CASTERS | frozenset({"Warlock"})
)

# ---------------------------------------------------------------------------
# Ability score mechanics
# ---------------------------------------------------------------------------


def ability_modifier(score: int) -> int:
    """Return the ability modifier for a given score.

    SRD formula: ``floor((score - 10) / 2)``.
    """
    return (score - 10) // 2


def validate_standard_array(scores: list[int]) -> bool:
    """Return True if *scores* are a valid permutation of [15, 14, 13, 12, 10, 8]."""
    return sorted(scores) == [8, 10, 12, 13, 14, 15]


def validate_point_buy(scores: dict[str, int]) -> bool:
    """Return True if all scores are valid under the 27-point buy rules.

    Rules (SRD 5.2.1 p.21):
    - Every score must be in the range 8–15 (before background bonuses).
    - The total point cost must not exceed 27.
    """
    for score in scores.values():
        if score not in _POINT_BUY_COSTS:
            return False
    total = sum(_POINT_BUY_COSTS[s] for s in scores.values())
    return total <= _POINT_BUY_BUDGET


def apply_background_bonuses(
    scores: dict[str, int],
    bonuses: dict[str, int],
) -> dict[str, int]:
    """Return a new scores dict with background bonuses applied.

    Background bonuses follow the +2/+1 or +1/+1/+1 pattern from SRD 5.2.1.
    No score may exceed 20 after bonuses are applied.

    Args:
        scores: Current ability scores keyed by ability name (e.g. ``"STR"``).
        bonuses: Bonus amounts to add, e.g. ``{"STR": 2, "CHA": 1}``.

    Returns:
        New ``dict`` with bonuses applied.

    Raises:
        ValueError: If any resulting score would exceed 20.
    """
    result = dict(scores)
    for ability, bonus in bonuses.items():
        new_value = result.get(ability, 0) + bonus
        if new_value > 20:
            raise ValueError(
                f"Ability score for {ability!r} would exceed 20 after bonus "
                f"({result.get(ability, 0)} + {bonus} = {new_value})."
            )
        result[ability] = new_value
    return result


# ---------------------------------------------------------------------------
# Proficiency bonus
# ---------------------------------------------------------------------------


def proficiency_bonus(total_level: int) -> int:
    """Return the proficiency bonus for a given total character level (1–20).

    SRD table: levels 1–4 → +2, 5–8 → +3, 9–12 → +4, 13–16 → +5, 17–20 → +6.

    Raises:
        ValueError: If *total_level* is not in 1–20.
    """
    if not 1 <= total_level <= 20:
        raise ValueError(f"Level must be 1–20, got {total_level}")
    return (total_level - 1) // 4 + 2


# ---------------------------------------------------------------------------
# Hit points
# ---------------------------------------------------------------------------


def max_hp_at_level_1(class_name: str, con_modifier: int) -> int:
    """Return the HP maximum at level 1 (hit die maximum + Con modifier, min 1).

    Raises:
        ValueError: If *class_name* is not a recognised SRD class.
    """
    if class_name not in HIT_DICE:
        raise ValueError(f"Unknown class: {class_name!r}")
    return max(1, HIT_DICE[class_name] + con_modifier)


def hp_gained_on_level_up(
    class_name: str,
    con_modifier: int,
    use_fixed: bool = True,
) -> int:
    """Return HP gained when levelling up using the fixed value (minimum 1).

    When ``use_fixed`` is True (default), returns the SRD fixed average value
    for the class plus the Constitution modifier.  Callers that want a rolled
    result should roll the appropriate hit die themselves and add the Con
    modifier — this function only implements the fixed-value path.

    Raises:
        ValueError: If *class_name* is not a recognised SRD class.
    """
    if class_name not in _FIXED_HP_PER_LEVEL:
        raise ValueError(f"Unknown class: {class_name!r}")
    return max(1, _FIXED_HP_PER_LEVEL[class_name] + con_modifier)


# ---------------------------------------------------------------------------
# Spell slots
# ---------------------------------------------------------------------------


def spell_slots(class_name: str, class_level: int) -> dict[int, int]:
    """Return spell slots for the given class at the given level.

    Returns a ``dict`` mapping spell level → number of slots.

    - Full casters (Bard, Cleric, Druid, Sorcerer, Wizard): slots from level 1.
    - Paladin and Ranger: slots from level 1 per SRD 5.2.1.
    - Warlock: Pact Magic slots (all at the same slot level per SRD 5.2.1).
    - Non-casters (Barbarian, Fighter, Monk, Rogue): empty dict.

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    _validate_class_level(class_name, class_level)
    idx = class_level - 1

    if class_name in _FULL_CASTERS:
        return dict(_FULL_CASTER_SLOTS[idx])
    if class_name in _HALF_CASTERS:
        return dict(_HALF_CASTER_SLOTS[idx])
    if class_name == "Warlock":
        num_slots, slot_level = _WARLOCK_PACT_MAGIC[idx]
        return {slot_level: num_slots}
    return {}


def multiclass_spell_slots(classes: dict[str, int]) -> dict[int, int]:
    """Return combined spell slots for a multiclass character.

    Combined caster level calculation (SRD 5.2.1 p.25):

    - Full casters (Bard, Cleric, Druid, Sorcerer, Wizard): all levels count.
    - Half casters (Paladin, Ranger): half their levels, **rounded up**.
    - Warlock: Pact Magic slots added separately on top of the table result.
    - Non-casters (Barbarian, Fighter, Monk, Rogue): contribute 0.

    The combined level is looked up in the Multiclass Spellcaster table.
    Warlock's Pact Magic slots are then added to the result.

    Raises:
        ValueError: If any class name or level is invalid.
    """
    for cls, lvl in classes.items():
        _validate_class_level(cls, lvl)

    combined_level = 0
    warlock_level: int | None = None

    for cls, lvl in classes.items():
        if cls in _FULL_CASTERS:
            combined_level += lvl
        elif cls in _HALF_CASTERS:
            combined_level += math.ceil(lvl / 2)
        elif cls == "Warlock":
            warlock_level = lvl
        # Non-casters contribute 0

    result: dict[int, int] = {}

    if combined_level > 0:
        table_idx = min(combined_level, 20) - 1
        for spell_lvl, count in _MULTICLASS_SLOTS[table_idx].items():
            result[spell_lvl] = result.get(spell_lvl, 0) + count

    if warlock_level is not None:
        num_slots, slot_level = _WARLOCK_PACT_MAGIC[warlock_level - 1]
        result[slot_level] = result.get(slot_level, 0) + num_slots

    return result


# ---------------------------------------------------------------------------
# XP and level
# ---------------------------------------------------------------------------


def level_for_xp(xp: int) -> int:
    """Return the character level (1–20) for a given XP total.

    Raises:
        ValueError: If *xp* is negative.
    """
    if xp < 0:
        raise ValueError(f"XP cannot be negative, got {xp}")
    level = 1
    for i, threshold in enumerate(XP_THRESHOLDS):
        if xp >= threshold:
            level = i + 1
    return level


# ---------------------------------------------------------------------------
# Multiclass prerequisites
# ---------------------------------------------------------------------------


def can_multiclass(
    current_classes: dict[str, int],
    new_class: str,
    ability_scores: dict[str, int],
) -> bool:
    """Return True if the character meets the multiclass prerequisites.

    Per SRD 5.2.1 p.24: the character must have a score of at least 13 in
    the primary ability of every class they already have *and* the new class.
    Classes with multiple primary abilities (Monk, Paladin, Ranger) require
    all listed abilities to be ≥ 13.

    Raises:
        ValueError: If any class name is not recognised.
    """
    all_classes = list(current_classes.keys()) + [new_class]
    for cls in all_classes:
        if cls not in PRIMARY_ABILITIES:
            raise ValueError(f"Unknown class: {cls!r}")
        for ability in PRIMARY_ABILITIES[cls]:
            if ability_scores.get(ability, 0) < 13:
                return False
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_class_level(class_name: str, class_level: int) -> None:
    if class_name not in _ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")
