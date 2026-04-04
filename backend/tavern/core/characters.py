"""Character mechanics for the SRD 5.2.1 Rules Engine.

All SRD game data (class tables, spell slots, species traits, backgrounds,
feats) is fetched from MongoDB via :mod:`tavern.core.srd_data`.  All
functions in this module that require data lookups are async.

Pure computation functions (ability_modifier, apply_background_bonuses, etc.)
remain synchronous.

SRD 5.2.1 notes
---------------
- Paladin and Ranger gain spell slots from level 1 (not 2 as in the 2014 PHB).
- Half-caster multiclass levels count as ``ceil(level / 2)`` (round **up**).
- All spellcasters use fixed "Prepared Spells" tables, not a derived formula.
"""

import math
from typing import Any, Final

from tavern.core import srd_data
from tavern.core.srd_data import ALL_CLASSES, FULL_CASTERS, HALF_CASTERS

# ---------------------------------------------------------------------------
# Character creation method constants
#
# These are generation-method rules, not class/species/entity data. They are
# intentionally retained as Python constants per the character creation spec.
# ---------------------------------------------------------------------------

STANDARD_ARRAY: Final[list[int]] = [15, 14, 13, 12, 10, 8]

POINT_BUY_BUDGET: Final[int] = 27

POINT_BUY_COSTS: Final[dict[int, int]] = {
    8: 0,
    9: 1,
    10: 2,
    11: 3,
    12: 4,
    13: 5,
    14: 7,
    15: 9,
}

# ---------------------------------------------------------------------------
# Re-exported classification constants (used by API layer and tests)
# ---------------------------------------------------------------------------
# These are imported from srd_data so callers have one import path.
__all__ = [
    # classification constants (from srd_data)
    "ALL_CLASSES",
    "FULL_CASTERS",
    "HALF_CASTERS",
    # character creation constants
    "STANDARD_ARRAY",
    "POINT_BUY_BUDGET",
    "POINT_BUY_COSTS",
    # sync functions
    "ability_modifier",
    "validate_standard_array",
    "validate_point_buy",
    "apply_background_bonuses",
    # async functions
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

# ---------------------------------------------------------------------------
# Ability score mechanics — synchronous, pure computation
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


# ---------------------------------------------------------------------------
# Background helpers — async (background data from MongoDB)
# ---------------------------------------------------------------------------


async def background_ability_options(background_name: str) -> list[dict[str, int]]:
    """Return all valid +2/+1 and +1/+1/+1 distributions for a background.

    Each background lists three eligible abilities (SRD 5.2.1 p.83).
    Valid distributions are:
    - +2 to one eligible ability, +1 to another (6 permutations)
    - +1 to all three eligible abilities (1 option)

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    bg = await srd_data.get_background_doc(background_name)
    eligible = _extract_eligible_abilities(bg, background_name)
    a, b, c = eligible
    options: list[dict[str, int]] = []
    for primary, secondary in [(a, b), (a, c), (b, a), (b, c), (c, a), (c, b)]:
        options.append({primary: 2, secondary: 1})
    options.append({a: 1, b: 1, c: 1})
    return options


async def validate_background_ability_bonus(
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
    bg = await srd_data.get_background_doc(background_name)
    eligible = _extract_eligible_abilities(bg, background_name)
    eligible_set = set(eligible)
    if not set(bonuses.keys()).issubset(eligible_set):
        return False
    values = sorted(bonuses.values(), reverse=True)
    return values in ([2, 1], [1, 1, 1])


def _extract_eligible_abilities(bg_doc: dict[str, Any], background_name: str) -> list[str]:
    """Extract the three eligible ability abbreviations from a background document.

    Checks the ``ability_scores_eligible`` field first (Tavern custom format),
    then falls back to parsing 5e-database ``ability_bonuses`` if present.

    Raises:
        ValueError: If eligible abilities cannot be determined.
    """
    # Tavern / custom Instance Library format
    if "ability_scores_eligible" in bg_doc:
        return list(bg_doc["ability_scores_eligible"])[:3]

    # 5e-database format: ability_bonuses list with ability_score.index
    if "ability_bonuses" in bg_doc:
        abilities = [
            b.get("ability_score", {}).get("index", "").upper()
            for b in bg_doc.get("ability_bonuses", [])
            if isinstance(b, dict)
        ]
        abilities = [a for a in abilities if a][:3]
        if len(abilities) >= 3:
            return abilities[:3]

    raise ValueError(
        f"Background {background_name!r} does not define eligible ability scores. "
        "Verify the 5e-database schema or add ability_scores_eligible to the custom entry."
    )


# ---------------------------------------------------------------------------
# Proficiency bonus — async
# ---------------------------------------------------------------------------


async def proficiency_bonus(total_level: int) -> int:
    """Return the proficiency bonus for *total_level* (1–20).

    Raises:
        ValueError: If *total_level* is outside 1–20.
    """
    return await srd_data.get_proficiency_bonus(total_level)


# ---------------------------------------------------------------------------
# Hit points — async
# ---------------------------------------------------------------------------


async def max_hp_at_level_1(class_name: str, con_modifier: int) -> int:
    """Return the HP maximum at level 1 (hit die maximum + Con modifier, min 1).

    Raises:
        ValueError: If *class_name* is not a recognised SRD class.
    """
    hit_die = await srd_data.get_class_hit_die(class_name)
    return max(1, hit_die + con_modifier)


async def hp_gained_on_level_up(
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
    fixed = await srd_data.get_class_fixed_hp_per_level(class_name)
    return max(1, fixed + con_modifier)


# ---------------------------------------------------------------------------
# Spell slots — async
# ---------------------------------------------------------------------------


async def spell_slots(class_name: str, class_level: int) -> dict[int, int]:
    """Return spell slots for *class_name* at *class_level*.

    Returns a ``dict`` mapping spell level → number of slots.

    - Full casters (Bard, Cleric, Druid, Sorcerer, Wizard): slots from level 1.
    - Paladin and Ranger: slots from level 1 per SRD 5.2.1.
    - Warlock: Pact Magic slots (all at the same level).
    - Non-casters (Barbarian, Fighter, Monk, Rogue): empty dict.

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    await _validate_class_level(class_name, class_level)
    return await srd_data.get_class_spell_slots(class_name, class_level)


async def multiclass_spell_slots(classes: dict[str, int]) -> dict[int, int]:
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
        await _validate_class_level(cls, lvl)

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
        effective = min(combined_level, 20)
        # Use Wizard (full-caster) as the multiclass spell-slot reference
        full_slots = await srd_data.get_class_spell_slots("Wizard", effective)
        for spell_lvl, count in full_slots.items():
            result[spell_lvl] = result.get(spell_lvl, 0) + count

    if warlock_level is not None:
        num_slots, slot_level = await srd_data.get_warlock_pact_magic(warlock_level)
        result[slot_level] = result.get(slot_level, 0) + num_slots

    return result


# ---------------------------------------------------------------------------
# Cantrips and prepared spells — async
# ---------------------------------------------------------------------------


async def cantrips_known(class_name: str, class_level: int) -> int:
    """Return the number of cantrips known for *class_name* at *class_level*.

    Returns ``0`` for classes with no class cantrips (Barbarian, Fighter,
    Monk, Paladin, Ranger, Rogue).

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    await _validate_class_level(class_name, class_level)
    return await srd_data.get_class_cantrips_known(class_name, class_level)


async def spells_prepared(class_name: str, class_level: int) -> int:
    """Return the number of spells prepared for *class_name* at *class_level*.

    Returns ``0`` for non-spellcasting classes (Barbarian, Fighter, Monk, Rogue).
    Uses the fixed Prepared Spells table from each class's feature table
    (SRD 5.2.1 — not a derived formula).

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    await _validate_class_level(class_name, class_level)
    return await srd_data.get_class_spells_prepared(class_name, class_level)


# ---------------------------------------------------------------------------
# Class features — async
# ---------------------------------------------------------------------------


async def class_features_at_level(class_name: str, class_level: int) -> list[str]:
    """Return the list of features gained by *class_name* at *class_level*.

    Returns an empty list for levels where no new class features are gained.

    Raises:
        ValueError: If *class_name* or *class_level* is invalid.
    """
    await _validate_class_level(class_name, class_level)
    return await srd_data.get_class_features_at_level(class_name, class_level)


async def all_class_features(class_name: str, up_to_level: int) -> dict[int, list[str]]:
    """Return all features for *class_name* from level 1 through *up_to_level*.

    Keys are class levels; values are (possibly empty) lists of feature names.

    Raises:
        ValueError: If *class_name* or *up_to_level* is invalid.
    """
    await _validate_class_level(class_name, up_to_level)
    result: dict[int, list[str]] = {}
    for lvl in range(1, up_to_level + 1):
        result[lvl] = await srd_data.get_class_features_at_level(class_name, lvl)
    return result


# ---------------------------------------------------------------------------
# Proficiencies — async
# ---------------------------------------------------------------------------


async def class_proficiencies(class_name: str) -> dict[str, Any]:
    """Return the proficiency data for *class_name*.

    The returned dict contains:
    ``saving_throws``, ``skills_choose``, ``skills_from``,
    ``armor``, ``weapons``, ``tools``.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    return await srd_data.get_class_proficiencies_data(class_name)


async def multiclass_proficiency_gains(new_class: str) -> dict[str, Any]:
    """Return the proficiency gains when multiclassing *into* *new_class*.

    The returned dict contains:
    ``armor``, ``weapons``, ``tools``, ``skills_choose``, ``skills_from``.

    Raises:
        ValueError: If *new_class* is not recognised.
    """
    return await srd_data.get_class_multiclass_proficiency_gains(new_class)


# ---------------------------------------------------------------------------
# Starting equipment — async
# ---------------------------------------------------------------------------


async def starting_equipment(class_name: str) -> dict[str, list[str]]:
    """Return the starting equipment options for *class_name*.

    Keys are ``"option_a"``, ``"option_b"``, and (for Fighter) ``"option_c"``.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    return await srd_data.get_class_starting_equipment_data(class_name)


# ---------------------------------------------------------------------------
# Species — async
# ---------------------------------------------------------------------------


async def species_traits(species_name: str) -> dict[str, Any]:
    """Return the trait data for *species_name*.

    Returns the raw 5e-database document for the species.

    Raises:
        ValueError: If *species_name* is not recognised.
    """
    return await srd_data.get_species_data(species_name)


# ---------------------------------------------------------------------------
# Backgrounds — async
# ---------------------------------------------------------------------------


async def background_data(background_name: str) -> dict[str, Any]:
    """Return all data for *background_name*.

    Returns the raw 5e-database document for the background.

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    return await srd_data.get_background_doc(background_name)


# ---------------------------------------------------------------------------
# Feats — async
# ---------------------------------------------------------------------------


async def feat_data(feat_name: str) -> dict[str, Any]:
    """Return the data dict for *feat_name*.

    Returns the raw 5e-database document for the feat.

    Raises:
        ValueError: If *feat_name* is not found.
    """
    return await srd_data.get_feat_doc(feat_name)


# ---------------------------------------------------------------------------
# XP and level — async
# ---------------------------------------------------------------------------


async def level_for_xp(xp: int) -> int:
    """Return the character level (1–20) for *xp* total experience points.

    Raises:
        ValueError: If *xp* is negative.
    """
    if xp < 0:
        raise ValueError(f"XP cannot be negative, got {xp}")
    thresholds = await srd_data.get_xp_thresholds()
    level = 1
    for i, threshold in enumerate(thresholds):
        if xp >= threshold:
            level = i + 1
    return level


# ---------------------------------------------------------------------------
# Multiclass prerequisites — async
# ---------------------------------------------------------------------------


async def can_multiclass(
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
        if await srd_data.get_class(cls.lower()) is None:
            raise ValueError(f"Unknown class: {cls!r}")
        abilities = await srd_data.get_class_primary_abilities(cls)
        for ability in abilities:
            if ability_scores.get(ability, 0) < 13:
                return False
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _validate_class_level(class_name: str, class_level: int) -> None:
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")
