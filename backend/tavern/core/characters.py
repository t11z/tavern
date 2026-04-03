"""Character mechanics for the SRD 5.2.1 Rules Engine.

All mechanical data (tables, constants) lives in :mod:`tavern.core.srd_tables`
so it can be verified directly against the PDF without reading function code.
This module provides the computational API that the rest of the engine uses.

SRD 5.2.1 notes
---------------
- Paladin and Ranger gain spell slots from level 1 (not 2 as in the 2014 PHB).
- Half-caster multiclass levels count as ``ceil(level / 2)`` (round **up**).
- All spellcasters use fixed "Prepared Spells" tables, not a derived formula.
"""

import math
from typing import Any, Final

from tavern.core.srd_tables import (
    ALL_CLASSES,
    ALL_FEATS,
    BACKGROUNDS,
    CLASS_CANTRIPS_KNOWN,
    CLASS_FEATURES,
    CLASS_PROFICIENCIES,
    CLASS_SPELLS_PREPARED,
    CLASS_STARTING_EQUIPMENT,
    EPIC_BOON_FEATS,
    FIGHTING_STYLE_FEATS,
    FIXED_HP_PER_LEVEL,
    FULL_CASTER_SPELL_SLOTS,
    FULL_CASTERS,
    GENERAL_FEATS,
    HALF_CASTER_SPELL_SLOTS,
    HALF_CASTERS,
    HIT_DICE,
    MULTICLASS_PROFICIENCY_GAINS,
    MULTICLASS_SPELL_SLOTS,
    NON_CASTERS,
    ORIGIN_FEATS,
    POINT_BUY_BUDGET,
    POINT_BUY_COSTS,
    PRIMARY_ABILITIES,
    PROFICIENCY_BONUS_BY_LEVEL,
    SPECIES_TRAITS,
    STANDARD_ARRAY,
    WARLOCK_PACT_MAGIC,
    XP_THRESHOLDS,
)

# ---------------------------------------------------------------------------
# Re-export public constants (backward compatibility with existing imports)
# ---------------------------------------------------------------------------

__all__ = [
    # data constants (re-exported from srd_tables)
    "HIT_DICE",
    "XP_THRESHOLDS",
    "PRIMARY_ABILITIES",
    "STANDARD_ARRAY",
    "POINT_BUY_BUDGET",
    "POINT_BUY_COSTS",
    "CLASS_FEATURES",
    "CLASS_CANTRIPS_KNOWN",
    "CLASS_SPELLS_PREPARED",
    "CLASS_PROFICIENCIES",
    "MULTICLASS_PROFICIENCY_GAINS",
    "CLASS_STARTING_EQUIPMENT",
    "SPECIES_TRAITS",
    "BACKGROUNDS",
    "ORIGIN_FEATS",
    "GENERAL_FEATS",
    "FIGHTING_STYLE_FEATS",
    "EPIC_BOON_FEATS",
    "ALL_FEATS",
    # functions
    "ability_modifier",
    "validate_standard_array",
    "validate_point_buy",
    "apply_background_bonuses",
    "background_ability_options",
    "validate_background_ability_bonus",
    "proficiency_bonus",
    "max_hp_at_level_1",
    "hp_gained_on_level_up",
    "spell_slots",
    "multiclass_spell_slots",
    "cantrips_known",
    "spells_prepared",
    "class_features_at_level",
    "all_class_features",
    "class_proficiencies",
    "multiclass_proficiency_gains",
    "starting_equipment",
    "species_traits",
    "background_data",
    "feat_data",
    "level_for_xp",
    "can_multiclass",
]

_FULL_CASTERS: Final[frozenset[str]] = FULL_CASTERS
_HALF_CASTERS: Final[frozenset[str]] = HALF_CASTERS
_NON_CASTERS: Final[frozenset[str]] = NON_CASTERS
_ALL_CLASSES: Final[frozenset[str]] = ALL_CLASSES

# ---------------------------------------------------------------------------
# Ability score mechanics
# ---------------------------------------------------------------------------


def ability_modifier(score: int) -> int:
    """Return the ability modifier for *score*.

    SRD formula: ``floor((score - 10) / 2)``.
    """
    return (score - 10) // 2


def validate_standard_array(scores: list[int]) -> bool:
    """Return ``True`` if *scores* is a valid permutation of ``[15, 14, 13, 12, 10, 8]``."""
    return sorted(scores) == sorted(STANDARD_ARRAY)


def validate_point_buy(scores: dict[str, int]) -> bool:
    """Return ``True`` if all scores satisfy the 27-point buy rules.

    Rules (SRD 5.2.1 p.21):
    - Every score must be in the range 8–15 (before background bonuses).
    - The total cost must not exceed 27.
    """
    for score in scores.values():
        if score not in POINT_BUY_COSTS:
            return False
    return sum(POINT_BUY_COSTS[s] for s in scores.values()) <= POINT_BUY_BUDGET


def apply_background_bonuses(
    scores: dict[str, int],
    bonuses: dict[str, int],
) -> dict[str, int]:
    """Return a new scores dict with background bonuses applied.

    No score may exceed 20 after bonuses are applied.

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


def background_ability_options(background_name: str) -> list[dict[str, int]]:
    """Return all valid +2/+1 and +1/+1/+1 distributions for a background.

    Each background lists three eligible abilities (SRD 5.2.1 p.83).
    Valid distributions are:
    - +2 to one eligible ability, +1 to another (6 permutations)
    - +1 to all three eligible abilities (1 option)

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    bg = BACKGROUNDS.get(background_name)
    if bg is None:
        raise ValueError(f"Unknown background: {background_name!r}")
    a, b, c = bg["ability_scores_eligible"]
    options: list[dict[str, int]] = []
    for primary, secondary in [(a, b), (a, c), (b, a), (b, c), (c, a), (c, b)]:
        options.append({primary: 2, secondary: 1})
    options.append({a: 1, b: 1, c: 1})
    return options


def validate_background_ability_bonus(
    background_name: str,
    bonuses: dict[str, int],
) -> bool:
    """Return ``True`` if *bonuses* is a valid distribution for *background_name*.

    Valid distributions (SRD 5.2.1 p.83):
    - +2/+1 to two of the background's three eligible abilities, or
    - +1/+1/+1 to all three eligible abilities.

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    bg = BACKGROUNDS.get(background_name)
    if bg is None:
        raise ValueError(f"Unknown background: {background_name!r}")
    eligible = set(bg["ability_scores_eligible"])
    if not set(bonuses.keys()).issubset(eligible):
        return False
    values = sorted(bonuses.values(), reverse=True)
    return values in ([2, 1], [1, 1, 1])


# ---------------------------------------------------------------------------
# Proficiency bonus
# ---------------------------------------------------------------------------


def proficiency_bonus(total_level: int) -> int:
    """Return the proficiency bonus for *total_level* (1–20).

    Raises:
        ValueError: If *total_level* is outside 1–20.
    """
    if total_level not in PROFICIENCY_BONUS_BY_LEVEL:
        raise ValueError(f"Level must be 1–20, got {total_level}")
    return PROFICIENCY_BONUS_BY_LEVEL[total_level]


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
    """Return HP gained on levelling up using the fixed average (minimum 1).

    When ``use_fixed`` is ``True`` (default), returns the SRD fixed value for
    the class plus the Constitution modifier.  Callers wanting a rolled result
    should roll the appropriate hit die themselves and add the Con modifier.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    if class_name not in FIXED_HP_PER_LEVEL:
        raise ValueError(f"Unknown class: {class_name!r}")
    return max(1, FIXED_HP_PER_LEVEL[class_name] + con_modifier)


# ---------------------------------------------------------------------------
# Spell slots
# ---------------------------------------------------------------------------


def spell_slots(class_name: str, class_level: int) -> dict[int, int]:
    """Return spell slots for *class_name* at *class_level*.

    Returns a ``dict`` mapping spell level → number of slots.

    - Full casters (Bard, Cleric, Druid, Sorcerer, Wizard): slots from level 1.
    - Paladin and Ranger: slots from level 1 per SRD 5.2.1.
    - Warlock: Pact Magic slots (all at the same level).
    - Non-casters (Barbarian, Fighter, Monk, Rogue): empty dict.

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    _validate_class_level(class_name, class_level)
    idx = class_level - 1
    if class_name in FULL_CASTERS:
        return dict(FULL_CASTER_SPELL_SLOTS[idx])
    if class_name in HALF_CASTERS:
        return dict(HALF_CASTER_SPELL_SLOTS[idx])
    if class_name == "Warlock":
        num_slots, slot_level = WARLOCK_PACT_MAGIC[idx]
        return {slot_level: num_slots}
    return {}


def multiclass_spell_slots(classes: dict[str, int]) -> dict[int, int]:
    """Return combined spell slots for a multiclass character.

    Combined caster level (SRD 5.2.1 p.25):
    - Full casters: all levels count.
    - Half casters (Paladin, Ranger): ``ceil(level / 2)`` — **round up**.
    - Warlock: Pact Magic added separately on top.
    - Non-casters: contribute 0.

    Raises:
        ValueError: If any class name or level is invalid.
    """
    for cls, lvl in classes.items():
        _validate_class_level(cls, lvl)

    combined_level = 0
    warlock_level: int | None = None

    for cls, lvl in classes.items():
        if cls in FULL_CASTERS:
            combined_level += lvl
        elif cls in HALF_CASTERS:
            combined_level += math.ceil(lvl / 2)
        elif cls == "Warlock":
            warlock_level = lvl

    result: dict[int, int] = {}

    if combined_level > 0:
        idx = min(combined_level, 20) - 1
        for spell_lvl, count in MULTICLASS_SPELL_SLOTS[idx].items():
            result[spell_lvl] = result.get(spell_lvl, 0) + count

    if warlock_level is not None:
        num_slots, slot_level = WARLOCK_PACT_MAGIC[warlock_level - 1]
        result[slot_level] = result.get(slot_level, 0) + num_slots

    return result


def cantrips_known(class_name: str, class_level: int) -> int:
    """Return the number of cantrips known for *class_name* at *class_level*.

    Returns ``0`` for classes with no class cantrips (Barbarian, Fighter,
    Monk, Paladin, Ranger, Rogue).

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    _validate_class_level(class_name, class_level)
    table = CLASS_CANTRIPS_KNOWN.get(class_name)
    return table[class_level - 1] if table is not None else 0


def spells_prepared(class_name: str, class_level: int) -> int:
    """Return the number of spells prepared for *class_name* at *class_level*.

    Returns ``0`` for non-spellcasting classes (Barbarian, Fighter, Monk, Rogue).
    Uses the fixed Prepared Spells table from each class's feature table
    (SRD 5.2.1 — not a derived formula).

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    _validate_class_level(class_name, class_level)
    table = CLASS_SPELLS_PREPARED.get(class_name)
    return table[class_level - 1] if table is not None else 0


# ---------------------------------------------------------------------------
# Class features
# ---------------------------------------------------------------------------


def class_features_at_level(class_name: str, class_level: int) -> list[str]:
    """Return the list of features gained by *class_name* at *class_level*.

    Returns an empty list for levels where no new class features are gained.

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    _validate_class_level(class_name, class_level)
    return list(CLASS_FEATURES[class_name].get(class_level, []))


def all_class_features(class_name: str, up_to_level: int) -> dict[int, list[str]]:
    """Return all features for *class_name* from level 1 through *up_to_level*.

    Keys are class levels; values are (possibly empty) lists of feature names.

    Raises:
        ValueError: If *class_name* or *up_to_level* is invalid.
    """
    _validate_class_level(class_name, up_to_level)
    return {
        lvl: list(feats) for lvl, feats in CLASS_FEATURES[class_name].items() if lvl <= up_to_level
    }


# ---------------------------------------------------------------------------
# Proficiencies
# ---------------------------------------------------------------------------


def class_proficiencies(class_name: str) -> dict[str, Any]:
    """Return the proficiency data for *class_name*.

    The returned dict contains:
    ``saving_throws``, ``skills_choose``, ``skills_from``,
    ``armor``, ``weapons``, ``tools``.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    if class_name not in CLASS_PROFICIENCIES:
        raise ValueError(f"Unknown class: {class_name!r}")
    return dict(CLASS_PROFICIENCIES[class_name])


def multiclass_proficiency_gains(new_class: str) -> dict[str, Any]:
    """Return the proficiency gains when multiclassing *into* *new_class*.

    The returned dict contains:
    ``armor``, ``weapons``, ``tools``, ``skills_choose``, ``skills_from``.

    Raises:
        ValueError: If *new_class* is not recognised.
    """
    if new_class not in MULTICLASS_PROFICIENCY_GAINS:
        raise ValueError(f"Unknown class: {new_class!r}")
    return dict(MULTICLASS_PROFICIENCY_GAINS[new_class])


# ---------------------------------------------------------------------------
# Starting equipment
# ---------------------------------------------------------------------------


def starting_equipment(class_name: str) -> dict[str, list[str]]:
    """Return the starting equipment options for *class_name*.

    Keys are ``"option_a"``, ``"option_b"``, and (for Fighter) ``"option_c"``.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    if class_name not in CLASS_STARTING_EQUIPMENT:
        raise ValueError(f"Unknown class: {class_name!r}")
    return dict(CLASS_STARTING_EQUIPMENT[class_name])


# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------


def species_traits(species_name: str) -> dict[str, Any]:
    """Return the trait data for *species_name*.

    Raises:
        ValueError: If *species_name* is not recognised.
    """
    if species_name not in SPECIES_TRAITS:
        raise ValueError(
            f"Unknown species: {species_name!r}. Known species: {sorted(SPECIES_TRAITS)}."
        )
    return dict(SPECIES_TRAITS[species_name])


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------


def background_data(background_name: str) -> dict[str, Any]:
    """Return all data for *background_name*.

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    if background_name not in BACKGROUNDS:
        raise ValueError(
            f"Unknown background: {background_name!r}. Known backgrounds: {sorted(BACKGROUNDS)}."
        )
    return dict(BACKGROUNDS[background_name])


# ---------------------------------------------------------------------------
# Feats
# ---------------------------------------------------------------------------


def feat_data(feat_name: str) -> dict[str, Any]:
    """Return the data dict for *feat_name*.

    Raises:
        ValueError: If *feat_name* is not found in any feat category.
    """
    if feat_name not in ALL_FEATS:
        raise ValueError(f"Unknown feat: {feat_name!r}.")
    return dict(ALL_FEATS[feat_name])


# ---------------------------------------------------------------------------
# XP and level
# ---------------------------------------------------------------------------


def level_for_xp(xp: int) -> int:
    """Return the character level (1–20) for *xp* total experience points.

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
    """Return ``True`` if the character meets all multiclass prerequisites.

    Per SRD 5.2.1 p.24: the character must have ≥ 13 in the primary ability
    of every class they currently have **and** the new class.

    Raises:
        ValueError: If any class name is not recognised.
    """
    for cls in list(current_classes) + [new_class]:
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
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")
