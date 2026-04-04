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
from dataclasses import dataclass, field
from typing import Any, Final

from tavern.core import srd_data
from tavern.core.dice import roll
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
    # rest mechanics
    "ShortRestResult",
    "LongRestResult",
    "apply_short_rest",
    "apply_long_rest",
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

    Checks fields in order:
    1. ``ability_scores_eligible`` — Tavern custom Instance Library format
    2. ``ability_scores``          — 2024 SRD format (ADR-0010)
    3. ``ability_bonuses``         — 2014 5e-database format (fallback)

    Raises:
        ValueError: If eligible abilities cannot be determined.
    """
    # Tavern / custom Instance Library format
    if "ability_scores_eligible" in bg_doc:
        return list(bg_doc["ability_scores_eligible"])[:3]

    # 2024 SRD format: ability_scores array of {index, name, url} refs
    if "ability_scores" in bg_doc:
        abilities = [
            ref["index"].upper()
            for ref in bg_doc["ability_scores"]
            if isinstance(ref, dict) and "index" in ref
        ]
        abilities = [a for a in abilities if a][:3]
        if len(abilities) >= 3:
            return abilities[:3]

    # 2014 5e-database format: ability_bonuses list with ability_score.index
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
# Rest mechanics — SRD 5.2.1 pp.17-18
# ---------------------------------------------------------------------------


@dataclass
class ShortRestResult:
    """Outcome of a Short Rest with optional hit die spending.

    SRD 5.2.1 p.17:
    'A Short Rest is a period of downtime, at least 1 hour long, during which
    a character does nothing more strenuous than eating, drinking, reading, and
    tending to wounds.  A character can spend one or more Hit Dice at the end of
    a Short Rest, up to the character's maximum number of Hit Dice, which is
    equal to the character's level.'
    """

    hp_regained: int
    hit_dice_spent: int
    hit_dice_remaining: int
    new_hp: int
    rolls: list[int] = field(default_factory=list)
    """Individual hit die roll results (before adding CON modifier) for display."""

    description: str = ""


@dataclass
class LongRestResult:
    """Outcome of a Long Rest.

    SRD 5.2.1 p.17:
    'A Long Rest is a period of extended downtime, at least 8 hours long.
    A character regains all lost Hit Points at the end of a Long Rest.
    The character also regains spent Hit Dice, up to a number of dice equal
    to half of the character's total number of them (minimum of one die).'
    """

    hp_restored: int
    """HP actually restored (max_hp − old_hp); 0 if already at full HP."""

    spell_slots_restored: dict[int, int]
    """Spell level → number of slots restored (0 for each already-full level)."""

    hit_dice_restored: int
    new_hp: int
    new_hit_dice: int
    description: str = ""


async def apply_short_rest(
    character_state: dict,
    hit_dice_to_spend: int = 0,
    seed: int | None = None,
) -> ShortRestResult:
    """Resolve a Short Rest, optionally spending hit dice to recover HP.

    Args:
        character_state: Current character state.  Expected keys:
            ``hp`` (int), ``max_hp`` (int),
            ``hit_dice_remaining`` (int),
            ``class_name`` (str), ``level`` (int),
            ``con_modifier`` (int).
        hit_dice_to_spend: Number of hit dice to roll for healing.
            0 is valid (rest without spending dice).
        seed: Optional integer seed for reproducible rolls.

    Returns:
        ``ShortRestResult`` with updated HP and hit dice counts.

    Raises:
        ValueError: If ``hit_dice_to_spend`` exceeds ``hit_dice_remaining``.
    """
    current_hp: int = int(character_state.get("hp", 0))
    max_hp: int = int(character_state.get("max_hp", 1))
    hit_dice_remaining: int = int(character_state.get("hit_dice_remaining", 0))
    class_name: str = character_state.get("class_name", "")
    con_modifier: int = int(character_state.get("con_modifier", 0))

    if hit_dice_to_spend < 0:
        raise ValueError(f"hit_dice_to_spend must be >= 0, got {hit_dice_to_spend}")
    if hit_dice_to_spend > hit_dice_remaining:
        raise ValueError(
            f"Cannot spend {hit_dice_to_spend} hit dice; only {hit_dice_remaining} remaining"
        )

    rolls: list[int] = []
    total_healed = 0

    if hit_dice_to_spend > 0:
        hit_die = await srd_data.get_class_hit_die(class_name)
        notation = f"1d{hit_die}"
        for i in range(hit_dice_to_spend):
            die_seed = (seed + i) if seed is not None else None
            result = roll(notation, seed=die_seed)
            rolls.append(result.total)
            # SRD p.17: add CON modifier per die; minimum 0 per die
            total_healed += max(0, result.total + con_modifier)

    new_hp = min(max_hp, current_hp + total_healed)
    actual_healed = new_hp - current_hp
    new_hit_dice = hit_dice_remaining - hit_dice_to_spend

    description = _short_rest_description(hit_dice_to_spend, rolls, con_modifier, actual_healed)

    return ShortRestResult(
        hp_regained=actual_healed,
        hit_dice_spent=hit_dice_to_spend,
        hit_dice_remaining=new_hit_dice,
        new_hp=new_hp,
        rolls=rolls,
        description=description,
    )


async def apply_long_rest(
    character_state: dict,
) -> LongRestResult:
    """Resolve a Long Rest: full HP, full spell slots, partial hit die recovery.

    Args:
        character_state: Current character state.  Expected keys:
            ``hp`` (int), ``max_hp`` (int),
            ``hit_dice_remaining`` (int),
            ``level`` (int), ``class_name`` (str),
            ``spell_slots_used`` (dict[int, int], spell level → slots expended).

    Returns:
        ``LongRestResult`` with restored HP, spell slots, and hit dice.
    """
    current_hp: int = int(character_state.get("hp", 0))
    max_hp: int = int(character_state.get("max_hp", 1))
    level: int = int(character_state.get("level", 1))
    hit_dice_remaining: int = int(character_state.get("hit_dice_remaining", 0))
    spell_slots_used: dict[int, int] = character_state.get("spell_slots_used", {})

    # Full HP recovery
    new_hp = max_hp
    hp_restored = max_hp - current_hp

    # Spell slot recovery — restore all expended slots
    spell_slots_restored: dict[int, int] = {}
    for spell_level_str, used in spell_slots_used.items():
        spell_level = int(spell_level_str)
        if used > 0:
            spell_slots_restored[spell_level] = used

    # Hit dice recovery: regain up to half total (rounded down), minimum 1
    # SRD p.17: "up to a number of dice equal to half of the character's total"
    total_hit_dice = level
    spent = total_hit_dice - hit_dice_remaining
    dice_to_restore = min(spent, max(1, level // 2))
    new_hit_dice = min(total_hit_dice, hit_dice_remaining + dice_to_restore)
    actual_dice_restored = new_hit_dice - hit_dice_remaining

    # Death save reset — caller owns the death save state; we report the reset
    # as part of the description (state mutation is the API layer's job).

    description = _long_rest_description(hp_restored, spell_slots_restored, actual_dice_restored)

    return LongRestResult(
        hp_restored=hp_restored,
        spell_slots_restored=spell_slots_restored,
        hit_dice_restored=actual_dice_restored,
        new_hp=new_hp,
        new_hit_dice=new_hit_dice,
        description=description,
    )


def _short_rest_description(
    dice_spent: int,
    rolls: list[int],
    con_modifier: int,
    hp_regained: int,
) -> str:
    if dice_spent == 0:
        return "Short rest taken; no hit dice spent."
    roll_str = ", ".join(str(r) for r in rolls)
    mod_str = (
        f" + {con_modifier} CON"
        if con_modifier > 0
        else (f" {con_modifier} CON" if con_modifier < 0 else "")
    )
    return (
        f"Short rest: spent {dice_spent} hit {'die' if dice_spent == 1 else 'dice'} "
        f"(rolled {roll_str}{mod_str}), regained {hp_regained} HP."
    )


def _long_rest_description(
    hp_restored: int,
    spell_slots_restored: dict[int, int],
    hit_dice_restored: int,
) -> str:
    parts = ["Long rest:"]
    if hp_restored > 0:
        parts.append(f"restored {hp_restored} HP")
    else:
        parts.append("already at full HP")
    slot_total = sum(spell_slots_restored.values())
    if slot_total:
        parts.append(f"restored {slot_total} spell slot(s)")
    if hit_dice_restored:
        parts.append(
            f"regained {hit_dice_restored} hit {'die' if hit_dice_restored == 1 else 'dice'}"
        )
    parts.append("death saves reset.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _validate_class_level(class_name: str, class_level: int) -> None:
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")
