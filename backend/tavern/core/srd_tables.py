"""SRD 5.2.1 data tables — verbatim from the source document.

Every constant in this module is a direct transcription from the
System Reference Document 5.2.1 (SRD_CC_v5.2.1.pdf).  The page
reference in each section header tells reviewers exactly where to
cross-check the numbers.  Do not edit a constant without re-reading
the cited PDF page first.

Module contract
---------------
- Data only.  No logic, no imports, no side-effects.
- All names that are part of the public API are UPPER_SNAKE_CASE.
- Private intermediate tables used only to build other tables are
  prefixed with an underscore.
"""

from typing import Any, Final

# ---------------------------------------------------------------------------
# Ability scores  (SRD 5.2.1 p.20)
# ---------------------------------------------------------------------------

STANDARD_ARRAY: Final[list[int]] = [15, 14, 13, 12, 10, 8]

POINT_BUY_BUDGET: Final[int] = 27

# Cost in points to buy each score (before background bonuses).
# Scores outside this range are not purchasable.
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

# Ability modifier formula: floor((score - 10) / 2).
# Tabulated here so contributors can cross-check edge cases (p.19).
ABILITY_SCORE_MODIFIERS: Final[dict[int, int]] = {
    1: -5,
    2: -4,
    3: -4,
    4: -3,
    5: -3,
    6: -2,
    7: -2,
    8: -1,
    9: -1,
    10: 0,
    11: 0,
    12: 1,
    13: 1,
    14: 2,
    15: 2,
    16: 3,
    17: 3,
    18: 4,
    19: 4,
    20: 5,
    21: 5,
    22: 6,
    23: 6,
    24: 7,
    25: 7,
    26: 8,
    27: 8,
    28: 9,
    29: 9,
    30: 10,
}

# ---------------------------------------------------------------------------
# Hit dice  (SRD 5.2.1 — class core traits, pp.29–77)
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

# Fixed HP gained per level after level 1 (SRD 5.2.1 p.23).
# "Fixed Hit Points by Class" — hit die average rounded up.
FIXED_HP_PER_LEVEL: Final[dict[str, int]] = {
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

# ---------------------------------------------------------------------------
# XP progression  (SRD 5.2.1 p.23 "Character Advancement" table)
# Index i is the minimum XP to reach level i+1.
# ---------------------------------------------------------------------------

XP_THRESHOLDS: Final[list[int]] = [
    0,  # level  1
    300,  # level  2
    900,  # level  3
    2_700,  # level  4
    6_500,  # level  5
    14_000,  # level  6
    23_000,  # level  7
    34_000,  # level  8
    48_000,  # level  9
    64_000,  # level 10
    85_000,  # level 11
    100_000,  # level 12
    120_000,  # level 13
    140_000,  # level 14
    165_000,  # level 15
    195_000,  # level 16
    225_000,  # level 17
    265_000,  # level 18
    305_000,  # level 19
    355_000,  # level 20
]

# Proficiency bonus by total character level (SRD 5.2.1 p.23).
PROFICIENCY_BONUS_BY_LEVEL: Final[dict[int, int]] = {
    1: 2,
    2: 2,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 3,
    8: 3,
    9: 4,
    10: 4,
    11: 4,
    12: 4,
    13: 5,
    14: 5,
    15: 5,
    16: 5,
    17: 6,
    18: 6,
    19: 6,
    20: 6,
}

# ---------------------------------------------------------------------------
# Multiclass prerequisites  (SRD 5.2.1 p.24)
# All listed abilities must be ≥ 13.
# ---------------------------------------------------------------------------

PRIMARY_ABILITIES: Final[dict[str, list[str]]] = {
    "Barbarian": ["STR"],
    "Bard": ["CHA"],
    "Cleric": ["WIS"],
    "Druid": ["WIS"],
    "Fighter": ["STR"],  # STR or DEX; STR used as default
    "Monk": ["DEX", "WIS"],
    "Paladin": ["STR", "CHA"],
    "Ranger": ["DEX", "WIS"],
    "Rogue": ["DEX"],
    "Sorcerer": ["CHA"],
    "Warlock": ["CHA"],
    "Wizard": ["INT"],
}

# ---------------------------------------------------------------------------
# Spell slot tables  (SRD 5.2.1 — individual class feature tables)
# Index i = class level i+1.  Key = spell level, value = number of slots.
# ---------------------------------------------------------------------------

# Full casters: Bard (p.31), Cleric (p.37), Druid (p.41),
#               Sorcerer (p.67), Wizard (p.77) — all share the same table.
FULL_CASTER_SPELL_SLOTS: Final[list[dict[int, int]]] = [
    {1: 2},  # level  1
    {1: 3},  # level  2
    {1: 4, 2: 2},  # level  3
    {1: 4, 2: 3},  # level  4
    {1: 4, 2: 3, 3: 2},  # level  5
    {1: 4, 2: 3, 3: 3},  # level  6
    {1: 4, 2: 3, 3: 3, 4: 1},  # level  7
    {1: 4, 2: 3, 3: 3, 4: 2},  # level  8
    {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},  # level  9
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

# Half-casters: Paladin (p.55), Ranger (p.59) — identical table.
# SRD 5.2.1 note: spell slots begin at class level 1 (changed from 2014 PHB).
HALF_CASTER_SPELL_SLOTS: Final[list[dict[int, int]]] = [
    {1: 2},  # level  1
    {1: 2},  # level  2
    {1: 3},  # level  3
    {1: 3},  # level  4
    {1: 4, 2: 2},  # level  5
    {1: 4, 2: 2},  # level  6
    {1: 4, 2: 3},  # level  7
    {1: 4, 2: 3},  # level  8
    {1: 4, 2: 3, 3: 2},  # level  9
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

# Warlock: Pact Magic (SRD 5.2.1 p.71).
# ALL slots at the same level; regained on Short or Long Rest.
# Tuple: (num_slots, slot_level)
WARLOCK_PACT_MAGIC: Final[list[tuple[int, int]]] = [
    (1, 1),  # level  1
    (2, 1),  # level  2
    (2, 2),  # level  3
    (2, 2),  # level  4
    (2, 3),  # level  5
    (2, 3),  # level  6
    (2, 4),  # level  7
    (2, 4),  # level  8
    (2, 5),  # level  9
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

# Multiclass Spellcaster table (SRD 5.2.1 p.26) — same as full caster table.
MULTICLASS_SPELL_SLOTS: Final[list[dict[int, int]]] = FULL_CASTER_SPELL_SLOTS

# Which classes use which slot table
FULL_CASTERS: Final[frozenset[str]] = frozenset({"Bard", "Cleric", "Druid", "Sorcerer", "Wizard"})
HALF_CASTERS: Final[frozenset[str]] = frozenset({"Paladin", "Ranger"})
NON_CASTERS: Final[frozenset[str]] = frozenset({"Barbarian", "Fighter", "Monk", "Rogue"})
ALL_CLASSES: Final[frozenset[str]] = (
    FULL_CASTERS | HALF_CASTERS | NON_CASTERS | frozenset({"Warlock"})
)

# ---------------------------------------------------------------------------
# Cantrips known per class level  (SRD 5.2.1 class feature tables)
# Index 0 = level 1, index 19 = level 20.
# Classes not in this dict have no class cantrips.
# ---------------------------------------------------------------------------

CLASS_CANTRIPS_KNOWN: Final[dict[str, list[int]]] = {
    # Bard p.31: 2 at L1 → 3 at L4 → 4 at L10
    "Bard": [2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
    # Cleric p.37: 3 at L1 → 4 at L4 → 5 at L10
    "Cleric": [3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
    # Druid p.41: 2 at L1 → 3 at L4 → 4 at L10
    "Druid": [2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
    # Sorcerer p.67: 4 at L1 → 5 at L4 → 6 at L10
    "Sorcerer": [4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6],
    # Warlock p.71: 2 at L1 → 3 at L4 → 4 at L10
    "Warlock": [2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
    # Wizard p.77: 3 at L1 → 4 at L4 → 5 at L10
    "Wizard": [3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],
}

# ---------------------------------------------------------------------------
# Spells prepared per class level  (SRD 5.2.1 class feature tables)
# Index 0 = level 1.  Sourced directly from "Prepared Spells" column.
# Classes not in this dict cast no spells (Barbarian, Fighter, Monk, Rogue).
# ---------------------------------------------------------------------------

CLASS_SPELLS_PREPARED: Final[dict[str, list[int]]] = {
    # Bard p.31
    "Bard": [4, 5, 6, 7, 9, 10, 11, 12, 14, 15, 16, 16, 17, 17, 18, 18, 19, 20, 21, 22],
    # Cleric p.37
    "Cleric": [4, 5, 6, 7, 9, 10, 11, 12, 14, 15, 16, 16, 17, 17, 18, 18, 19, 20, 21, 22],
    # Druid p.41
    "Druid": [4, 5, 6, 7, 9, 10, 11, 12, 14, 15, 16, 16, 17, 17, 18, 18, 19, 20, 21, 22],
    # Paladin p.55
    "Paladin": [2, 3, 4, 5, 6, 6, 7, 7, 9, 9, 10, 10, 11, 11, 12, 12, 14, 14, 15, 15],
    # Ranger p.59
    "Ranger": [2, 3, 4, 5, 6, 6, 7, 7, 9, 9, 10, 10, 11, 11, 12, 12, 14, 14, 15, 15],
    # Sorcerer p.67
    "Sorcerer": [2, 4, 6, 7, 9, 10, 11, 12, 14, 15, 16, 16, 17, 17, 18, 18, 19, 20, 21, 22],
    # Warlock p.71
    "Warlock": [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14, 15, 15],
    # Wizard p.77 (notably 21 at L16, 25 at L20)
    "Wizard": [4, 5, 6, 7, 9, 10, 11, 12, 14, 15, 16, 16, 17, 18, 19, 21, 22, 23, 24, 25],
}

# Spellcasting ability by class (used for spell save DC and attack bonus)
SPELLCASTING_ABILITY: Final[dict[str, str]] = {
    "Bard": "CHA",
    "Cleric": "WIS",
    "Druid": "WIS",
    "Paladin": "CHA",
    "Ranger": "WIS",
    "Sorcerer": "CHA",
    "Warlock": "CHA",
    "Wizard": "INT",
}

# ---------------------------------------------------------------------------
# Class feature tables  (SRD 5.2.1 — each class's feature table, pp.28–82)
# Outer key: class name.  Inner key: class level 1–20.
# Value: list of feature names gained at that level (empty list = no new features).
# "Subclass feature" denotes a level where the chosen subclass grants a feature.
# ---------------------------------------------------------------------------

CLASS_FEATURES: Final[dict[str, dict[int, list[str]]]] = {
    "Barbarian": {  # pp.28–30
        1: ["Rage", "Unarmored Defense", "Weapon Mastery"],
        2: ["Danger Sense", "Reckless Attack"],
        3: ["Barbarian Subclass", "Primal Knowledge"],
        4: ["Ability Score Improvement"],
        5: ["Extra Attack", "Fast Movement"],
        6: ["Subclass feature"],
        7: ["Feral Instinct", "Instinctive Pounce"],
        8: ["Ability Score Improvement"],
        9: ["Brutal Strike"],
        10: ["Subclass feature"],
        11: ["Relentless Rage"],
        12: ["Ability Score Improvement"],
        13: ["Improved Brutal Strike"],
        14: ["Subclass feature"],
        15: ["Persistent Rage"],
        16: ["Ability Score Improvement"],
        17: ["Improved Brutal Strike"],
        18: ["Indomitable Might"],
        19: ["Epic Boon"],
        20: ["Primal Champion"],
    },
    "Bard": {  # pp.31–36
        1: ["Bardic Inspiration", "Spellcasting"],
        2: ["Expertise", "Jack of All Trades"],
        3: ["Bard Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Font of Inspiration"],
        6: ["Subclass feature"],
        7: ["Countercharm"],
        8: ["Ability Score Improvement"],
        9: ["Expertise"],
        10: ["Magical Secrets"],
        11: [],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Subclass feature"],
        15: [],
        16: ["Ability Score Improvement"],
        17: [],
        18: ["Superior Inspiration"],
        19: ["Epic Boon"],
        20: ["Words of Creation"],
    },
    "Cleric": {  # pp.37–40
        1: ["Spellcasting", "Divine Order"],
        2: ["Channel Divinity"],
        3: ["Cleric Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Sear Undead"],
        6: ["Subclass feature"],
        7: ["Blessed Strikes"],
        8: ["Ability Score Improvement"],
        9: [],
        10: ["Divine Intervention"],
        11: [],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Improved Blessed Strikes"],
        15: [],
        16: ["Ability Score Improvement"],
        17: ["Subclass feature"],
        18: [],
        19: ["Epic Boon"],
        20: ["Greater Divine Intervention"],
    },
    "Druid": {  # pp.41–45
        1: ["Spellcasting", "Druidic", "Primal Order"],
        2: ["Wild Shape", "Wild Companion"],
        3: ["Druid Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Wild Resurgence"],
        6: ["Subclass feature"],
        7: ["Elemental Fury"],
        8: ["Ability Score Improvement"],
        9: [],
        10: ["Subclass feature"],
        11: [],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Subclass feature"],
        15: ["Improved Elemental Fury"],
        16: ["Ability Score Improvement"],
        17: [],
        18: ["Beast Spells"],
        19: ["Epic Boon"],
        20: ["Archdruid"],
    },
    "Fighter": {  # pp.46–50
        1: ["Fighting Style", "Second Wind", "Weapon Mastery"],
        2: ["Action Surge (one use)", "Tactical Mind"],
        3: ["Fighter Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Extra Attack", "Tactical Shift"],
        6: ["Ability Score Improvement"],
        7: ["Subclass feature"],
        8: ["Ability Score Improvement"],
        9: ["Indomitable (one use)", "Tactical Master"],
        10: ["Subclass feature"],
        11: ["Two Extra Attacks"],
        12: ["Ability Score Improvement"],
        13: ["Indomitable (two uses)", "Studied Attacks"],
        14: ["Ability Score Improvement"],
        15: ["Subclass feature"],
        16: ["Ability Score Improvement"],
        17: ["Action Surge (two uses)", "Indomitable (three uses)"],
        18: ["Subclass feature"],
        19: ["Epic Boon"],
        20: ["Three Extra Attacks"],
    },
    "Monk": {  # pp.51–54
        1: ["Martial Arts", "Unarmored Defense"],
        2: ["Monk's Focus", "Unarmored Movement", "Uncanny Metabolism"],
        3: ["Deflect Attacks", "Monk Subclass"],
        4: ["Ability Score Improvement", "Slow Fall"],
        5: ["Extra Attack", "Stunning Strike"],
        6: ["Empowered Strikes", "Subclass feature"],
        7: ["Evasion"],
        8: ["Ability Score Improvement"],
        9: ["Acrobatic Movement"],
        10: ["Heightened Focus", "Self-Restoration"],
        11: ["Subclass feature"],
        12: ["Ability Score Improvement"],
        13: ["Deflect Energy"],
        14: ["Disciplined Survivor"],
        15: ["Perfect Focus"],
        16: ["Ability Score Improvement"],
        17: ["Subclass feature"],
        18: ["Superior Defense"],
        19: ["Epic Boon"],
        20: ["Body and Mind"],
    },
    "Paladin": {  # pp.55–58
        1: ["Lay On Hands", "Spellcasting", "Weapon Mastery"],
        2: ["Fighting Style", "Paladin's Smite"],
        3: ["Channel Divinity", "Paladin Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Extra Attack", "Faithful Steed"],
        6: ["Aura of Protection"],
        7: ["Subclass feature"],
        8: ["Ability Score Improvement"],
        9: ["Abjure Foes"],
        10: ["Aura of Courage"],
        11: ["Radiant Strikes"],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Restoring Touch"],
        15: ["Subclass feature"],
        16: ["Ability Score Improvement"],
        17: [],
        18: ["Aura Expansion"],
        19: ["Epic Boon"],
        20: ["Subclass feature"],
    },
    "Ranger": {  # pp.59–62
        1: ["Spellcasting", "Favored Enemy", "Weapon Mastery"],
        2: ["Deft Explorer", "Fighting Style"],
        3: ["Ranger Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Extra Attack"],
        6: ["Roving"],
        7: ["Subclass feature"],
        8: ["Ability Score Improvement"],
        9: ["Expertise"],
        10: ["Tireless"],
        11: ["Subclass feature"],
        12: ["Ability Score Improvement"],
        13: ["Relentless Hunter"],
        14: ["Nature's Veil"],
        15: ["Subclass feature"],
        16: ["Ability Score Improvement"],
        17: ["Precise Hunter"],
        18: ["Feral Senses"],
        19: ["Epic Boon"],
        20: ["Foe Slayer"],
    },
    "Rogue": {  # pp.63–66
        1: ["Expertise", "Sneak Attack", "Thieves' Cant", "Weapon Mastery"],
        2: ["Cunning Action"],
        3: ["Rogue Subclass", "Steady Aim"],
        4: ["Ability Score Improvement"],
        5: ["Cunning Strike", "Uncanny Dodge"],
        6: ["Expertise"],
        7: ["Evasion", "Reliable Talent"],
        8: ["Ability Score Improvement"],
        9: ["Subclass feature"],
        10: ["Ability Score Improvement"],
        11: ["Improved Cunning Strike"],
        12: ["Ability Score Improvement"],
        13: ["Subclass feature"],
        14: ["Devious Strikes"],
        15: ["Slippery Mind"],
        16: ["Ability Score Improvement"],
        17: ["Subclass feature"],
        18: ["Elusive"],
        19: ["Epic Boon"],
        20: ["Stroke of Luck"],
    },
    "Sorcerer": {  # pp.67–70
        1: ["Spellcasting", "Innate Sorcery"],
        2: ["Font of Magic", "Metamagic"],
        3: ["Sorcerer Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Sorcerous Restoration"],
        6: ["Subclass feature"],
        7: ["Sorcery Incarnate"],
        8: ["Ability Score Improvement"],
        9: [],
        10: ["Metamagic"],
        11: [],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Subclass feature"],
        15: [],
        16: ["Ability Score Improvement"],
        17: ["Metamagic"],
        18: ["Subclass feature"],
        19: ["Epic Boon"],
        20: ["Arcane Apotheosis"],
    },
    "Warlock": {  # pp.71–76
        1: ["Eldritch Invocations", "Pact Magic"],
        2: ["Magical Cunning"],
        3: ["Warlock Subclass"],
        4: ["Ability Score Improvement"],
        5: [],
        6: ["Subclass feature"],
        7: [],
        8: ["Ability Score Improvement"],
        9: ["Contact Patron"],
        10: ["Subclass feature"],
        11: ["Mystic Arcanum (level 6 spell)"],
        12: ["Ability Score Improvement"],
        13: ["Mystic Arcanum (level 7 spell)"],
        14: ["Subclass feature"],
        15: ["Mystic Arcanum (level 8 spell)"],
        16: ["Ability Score Improvement"],
        17: ["Mystic Arcanum (level 9 spell)"],
        18: [],
        19: ["Epic Boon"],
        20: ["Eldritch Master"],
    },
    "Wizard": {  # pp.77–79
        1: ["Spellcasting", "Ritual Adept", "Arcane Recovery"],
        2: ["Scholar"],
        3: ["Wizard Subclass"],
        4: ["Ability Score Improvement"],
        5: ["Memorize Spell"],
        6: ["Subclass feature"],
        7: [],
        8: ["Ability Score Improvement"],
        9: [],
        10: ["Subclass feature"],
        11: [],
        12: ["Ability Score Improvement"],
        13: [],
        14: ["Subclass feature"],
        15: [],
        16: ["Ability Score Improvement"],
        17: [],
        18: ["Spell Mastery"],
        19: ["Epic Boon"],
        20: ["Signature Spells"],
    },
}

# ---------------------------------------------------------------------------
# Extra per-level class columns  (SRD 5.2.1 class feature tables)
# ---------------------------------------------------------------------------

# Barbarian: Rages/day, Rage Damage bonus, Weapon Mastery count  (p.28)
BARBARIAN_RAGE_TABLE: Final[dict[int, tuple[int, int, int]]] = {
    #  level: (rages, damage_bonus, weapon_mastery)
    1: (2, 2, 2),
    2: (2, 2, 2),
    3: (3, 2, 2),
    4: (3, 2, 3),
    5: (3, 2, 3),
    6: (4, 2, 3),
    7: (4, 2, 3),
    8: (4, 2, 3),
    9: (4, 3, 3),
    10: (4, 3, 4),
    11: (4, 3, 4),
    12: (5, 3, 4),
    13: (5, 3, 4),
    14: (5, 3, 4),
    15: (5, 3, 4),
    16: (5, 4, 4),
    17: (6, 4, 4),
    18: (6, 4, 4),
    19: (6, 4, 4),
    20: (6, 4, 4),
}

# Monk: Martial Arts die, Focus Points, Unarmored Movement bonus (ft)  (p.51)
MONK_FEATURES_TABLE: Final[dict[int, tuple[str, int, int]]] = {
    #  level: (martial_arts_die, focus_points, unarmored_movement_ft)
    1: ("1d6", 0, 0),
    2: ("1d6", 2, 10),
    3: ("1d6", 3, 10),
    4: ("1d6", 4, 10),
    5: ("1d8", 5, 10),
    6: ("1d8", 6, 15),
    7: ("1d8", 7, 15),
    8: ("1d8", 8, 15),
    9: ("1d8", 9, 15),
    10: ("1d8", 10, 20),
    11: ("1d10", 11, 20),
    12: ("1d10", 12, 20),
    13: ("1d10", 13, 20),
    14: ("1d10", 14, 25),
    15: ("1d10", 15, 25),
    16: ("1d10", 16, 25),
    17: ("1d12", 17, 25),
    18: ("1d12", 18, 30),
    19: ("1d12", 19, 30),
    20: ("1d12", 20, 30),
}

# Rogue: Sneak Attack dice  (p.63)
ROGUE_SNEAK_ATTACK: Final[dict[int, str]] = {
    1: "1d6",
    2: "1d6",
    3: "2d6",
    4: "2d6",
    5: "3d6",
    6: "3d6",
    7: "4d6",
    8: "4d6",
    9: "5d6",
    10: "5d6",
    11: "6d6",
    12: "6d6",
    13: "7d6",
    14: "7d6",
    15: "8d6",
    16: "8d6",
    17: "9d6",
    18: "9d6",
    19: "10d6",
    20: "10d6",
}

# Warlock: Eldritch Invocations known  (p.71)
WARLOCK_INVOCATIONS_TABLE: Final[dict[int, int]] = {
    1: 1,
    2: 3,
    3: 3,
    4: 3,
    5: 5,
    6: 5,
    7: 6,
    8: 6,
    9: 7,
    10: 7,
    11: 7,
    12: 8,
    13: 8,
    14: 8,
    15: 9,
    16: 9,
    17: 9,
    18: 10,
    19: 10,
    20: 10,
}

# ---------------------------------------------------------------------------
# Class proficiencies  (SRD 5.2.1 "Core Class Traits" tables, pp.29–77)
# ---------------------------------------------------------------------------

CLASS_PROFICIENCIES: Final[dict[str, dict[str, Any]]] = {
    "Barbarian": {
        "saving_throws": ["STR", "CON"],
        "skills_choose": 2,
        "skills_from": [
            "Animal Handling",
            "Athletics",
            "Intimidation",
            "Nature",
            "Perception",
            "Survival",
        ],
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Simple Weapons", "Martial Weapons"],
        "tools": [],
    },
    "Bard": {
        "saving_throws": ["DEX", "CHA"],
        "skills_choose": 3,
        "skills_from": ["any"],  # "Choose any 3 skills"
        "armor": ["Light Armor"],
        "weapons": ["Simple Weapons"],
        "tools": ["3 Musical Instruments (player's choice)"],
    },
    "Cleric": {
        "saving_throws": ["WIS", "CHA"],
        "skills_choose": 2,
        "skills_from": ["History", "Insight", "Medicine", "Persuasion", "Religion"],
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Simple Weapons"],
        "tools": [],
    },
    "Druid": {
        "saving_throws": ["INT", "WIS"],
        "skills_choose": 2,
        "skills_from": [
            "Animal Handling",
            "Arcana",
            "Insight",
            "Medicine",
            "Nature",
            "Perception",
            "Religion",
            "Survival",
        ],
        "armor": ["Light Armor", "Shields"],
        "weapons": ["Simple Weapons"],
        "tools": ["Herbalism Kit"],
    },
    "Fighter": {
        "saving_throws": ["STR", "CON"],
        "skills_choose": 2,
        "skills_from": [
            "Acrobatics",
            "Animal Handling",
            "Athletics",
            "History",
            "Insight",
            "Intimidation",
            "Perception",
            "Persuasion",
            "Survival",
        ],
        "armor": ["Light Armor", "Medium Armor", "Heavy Armor", "Shields"],
        "weapons": ["Simple Weapons", "Martial Weapons"],
        "tools": [],
    },
    "Monk": {
        "saving_throws": ["STR", "DEX"],
        "skills_choose": 2,
        "skills_from": ["Acrobatics", "Athletics", "History", "Insight", "Religion", "Stealth"],
        "armor": [],
        "weapons": ["Simple Weapons", "Martial Weapons with the Light property"],
        "tools": ["One type of Artisan's Tools or Musical Instrument"],
    },
    "Paladin": {
        "saving_throws": ["WIS", "CHA"],
        "skills_choose": 2,
        "skills_from": [
            "Athletics",
            "Insight",
            "Intimidation",
            "Medicine",
            "Persuasion",
            "Religion",
        ],
        "armor": ["Light Armor", "Medium Armor", "Heavy Armor", "Shields"],
        "weapons": ["Simple Weapons", "Martial Weapons"],
        "tools": [],
    },
    "Ranger": {
        "saving_throws": ["STR", "DEX"],
        "skills_choose": 3,
        "skills_from": [
            "Animal Handling",
            "Athletics",
            "Insight",
            "Investigation",
            "Nature",
            "Perception",
            "Stealth",
            "Survival",
        ],
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Simple Weapons", "Martial Weapons"],
        "tools": [],
    },
    "Rogue": {
        "saving_throws": ["DEX", "INT"],
        "skills_choose": 4,
        "skills_from": [
            "Acrobatics",
            "Athletics",
            "Deception",
            "Insight",
            "Intimidation",
            "Investigation",
            "Perception",
            "Persuasion",
            "Sleight of Hand",
            "Stealth",
        ],
        "armor": ["Light Armor"],
        "weapons": ["Simple Weapons", "Martial Weapons with the Finesse or Light property"],
        "tools": ["Thieves' Tools"],
    },
    "Sorcerer": {
        "saving_throws": ["CON", "CHA"],
        "skills_choose": 2,
        "skills_from": [
            "Arcana",
            "Deception",
            "Insight",
            "Intimidation",
            "Persuasion",
            "Religion",
        ],
        "armor": [],
        "weapons": ["Simple Weapons"],
        "tools": [],
    },
    "Warlock": {
        "saving_throws": ["WIS", "CHA"],
        "skills_choose": 2,
        "skills_from": [
            "Arcana",
            "Deception",
            "History",
            "Intimidation",
            "Investigation",
            "Nature",
            "Religion",
        ],
        "armor": ["Light Armor"],
        "weapons": ["Simple Weapons"],
        "tools": [],
    },
    "Wizard": {
        "saving_throws": ["INT", "WIS"],
        "skills_choose": 2,
        "skills_from": [
            "Arcana",
            "History",
            "Insight",
            "Investigation",
            "Medicine",
            "Nature",
            "Religion",
        ],
        "armor": [],
        "weapons": ["Simple Weapons"],
        "tools": [],
    },
}

# Proficiencies gained when multiclassing INTO a class  (SRD 5.2.1 p.25)
MULTICLASS_PROFICIENCY_GAINS: Final[dict[str, dict[str, Any]]] = {
    "Barbarian": {
        "armor": ["Medium Armor", "Shields"],
        "weapons": ["Martial Weapons"],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Bard": {
        "armor": ["Light Armor"],
        "weapons": [],
        "tools": ["1 Musical Instrument (player's choice)"],
        "skills_choose": 1,
        "skills_from": ["any"],
    },
    "Cleric": {
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Druid": {
        "armor": ["Light Armor", "Shields"],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Fighter": {
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Martial Weapons"],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Monk": {
        "armor": [],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Paladin": {
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Martial Weapons"],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Ranger": {
        "armor": ["Light Armor", "Medium Armor", "Shields"],
        "weapons": ["Martial Weapons"],
        "tools": [],
        "skills_choose": 1,
        "skills_from": [
            "Animal Handling",
            "Athletics",
            "Insight",
            "Investigation",
            "Nature",
            "Perception",
            "Stealth",
            "Survival",
        ],
    },
    "Rogue": {
        "armor": ["Light Armor"],
        "weapons": [],
        "tools": ["Thieves' Tools"],
        "skills_choose": 1,
        "skills_from": [
            "Acrobatics",
            "Athletics",
            "Deception",
            "Insight",
            "Intimidation",
            "Investigation",
            "Perception",
            "Persuasion",
            "Sleight of Hand",
            "Stealth",
        ],
    },
    "Sorcerer": {
        "armor": [],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Warlock": {
        "armor": ["Light Armor"],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
    "Wizard": {
        "armor": [],
        "weapons": [],
        "tools": [],
        "skills_choose": 0,
        "skills_from": [],
    },
}

# ---------------------------------------------------------------------------
# Starting equipment  (SRD 5.2.1 "Core Class Traits" tables, pp.29–77)
# Each class offers option_a (specific items) and option_b (gold pieces).
# Some classes have option_c.
# ---------------------------------------------------------------------------

CLASS_STARTING_EQUIPMENT: Final[dict[str, dict[str, list[str]]]] = {
    "Barbarian": {
        "option_a": ["Greataxe", "4 Handaxes", "Explorer's Pack", "15 GP"],
        "option_b": ["75 GP"],
    },
    "Bard": {
        "option_a": [
            "Leather Armor",
            "2 Daggers",
            "Musical Instrument (player's choice)",
            "Entertainer's Pack",
            "19 GP",
        ],
        "option_b": ["90 GP"],
    },
    "Cleric": {
        "option_a": ["Chain Shirt", "Shield", "Mace", "Holy Symbol", "Priest's Pack", "7 GP"],
        "option_b": ["110 GP"],
    },
    "Druid": {
        "option_a": [
            "Leather Armor",
            "Shield",
            "Sickle",
            "Druidic Focus (Quarterstaff)",
            "Explorer's Pack",
            "Herbalism Kit",
            "9 GP",
        ],
        "option_b": ["50 GP"],
    },
    "Fighter": {
        "option_a": [
            "Chain Mail",
            "Greatsword",
            "Flail",
            "8 Javelins",
            "Dungeoneer's Pack",
            "4 GP",
        ],
        "option_b": [
            "Studded Leather Armor",
            "Scimitar",
            "Shortsword",
            "Longbow",
            "20 Arrows",
            "Quiver",
            "Dungeoneer's Pack",
            "11 GP",
        ],
        "option_c": ["155 GP"],
    },
    "Monk": {
        "option_a": [
            "Spear",
            "5 Daggers",
            "Artisan's Tools or Musical Instrument (same as proficiency)",
            "Explorer's Pack",
            "11 GP",
        ],
        "option_b": ["50 GP"],
    },
    "Paladin": {
        "option_a": [
            "Chain Mail",
            "Shield",
            "Longsword",
            "6 Javelins",
            "Holy Symbol",
            "Priest's Pack",
            "9 GP",
        ],
        "option_b": ["150 GP"],
    },
    "Ranger": {
        "option_a": [
            "Studded Leather Armor",
            "Scimitar",
            "Shortsword",
            "Longbow",
            "20 Arrows",
            "Quiver",
            "Druidic Focus (sprig of mistletoe)",
            "Explorer's Pack",
            "7 GP",
        ],
        "option_b": ["150 GP"],
    },
    "Rogue": {
        "option_a": [
            "Leather Armor",
            "2 Daggers",
            "Shortsword",
            "Shortbow",
            "20 Arrows",
            "Quiver",
            "Thieves' Tools",
            "Burglar's Pack",
            "8 GP",
        ],
        "option_b": ["100 GP"],
    },
    "Sorcerer": {
        "option_a": ["Spear", "2 Daggers", "Arcane Focus (crystal)", "Dungeoneer's Pack", "28 GP"],
        "option_b": ["50 GP"],
    },
    "Warlock": {
        "option_a": [
            "Leather Armor",
            "Sickle",
            "2 Daggers",
            "Arcane Focus (orb)",
            "Book (occult lore)",
            "Scholar's Pack",
            "15 GP",
        ],
        "option_b": ["100 GP"],
    },
    "Wizard": {
        "option_a": [
            "2 Daggers",
            "Arcane Focus (Quarterstaff)",
            "Robe",
            "Spellbook",
            "Scholar's Pack",
            "5 GP",
        ],
        "option_b": ["55 GP"],
    },
}

# ---------------------------------------------------------------------------
# Species traits  (SRD 5.2.1 pp.84–86)
# ---------------------------------------------------------------------------

SPECIES_TRAITS: Final[dict[str, dict[str, Any]]] = {
    "Dragonborn": {  # p.84
        "creature_type": "Humanoid",
        "size": "Medium",
        "speed": 30,
        "traits": {
            "Draconic Ancestry": {
                "description": (
                    "Choose a dragon type (from the table below). "
                    "Determines your Breath Weapon damage type and Damage Resistance."
                ),
                "dragon_types": {
                    "Black": "Acid",
                    "Blue": "Lightning",
                    "Brass": "Fire",
                    "Bronze": "Lightning",
                    "Copper": "Acid",
                    "Gold": "Fire",
                    "Green": "Poison",
                    "Red": "Fire",
                    "Silver": "Cold",
                    "White": "Cold",
                },
            },
            "Breath Weapon": {
                "shape_options": ["15-foot Cone", "30-foot Line (5 ft wide)"],
                "save": "DEX (DC = 8 + CON modifier + Proficiency Bonus)",
                "damage_by_level": {
                    "levels_1_4": "1d10",
                    "level_5": "2d10",
                    "level_11": "3d10",
                    "level_17": "4d10",
                },
                "damage_type": "determined by Draconic Ancestry",
                "uses": "Proficiency Bonus per Long Rest",
            },
            "Damage Resistance": {
                "type": "determined by Draconic Ancestry",
            },
            "Darkvision": {
                "range_ft": 60,
            },
            "Draconic Flight": {
                "prerequisite": "character level 5",
                "description": "Bonus Action; spectral wings; Fly Speed = Speed for 10 min.",
                "uses": "1 per Long Rest",
            },
        },
    },
    "Dwarf": {  # p.84
        "creature_type": "Humanoid",
        "size": "Medium",
        "speed": 30,
        "traits": {
            "Darkvision": {
                "range_ft": 120,
            },
            "Dwarven Resilience": {
                "resistance": ["Poison damage"],
                "advantage": "saving throws to avoid or end Poisoned condition",
            },
            "Dwarven Toughness": {
                "description": "HP maximum +1 per character level (starting at level 1).",
            },
            "Stonecunning": {
                "description": (
                    "Bonus Action: gain Tremorsense 60 ft for 10 min (on/touching stone)."
                ),
                "uses": "Proficiency Bonus per Long Rest",
            },
        },
    },
    "Elf": {  # p.84–85
        "creature_type": "Humanoid",
        "size": "Medium",
        "speed": 30,
        "traits": {
            "Darkvision": {
                "range_ft": 60,
                "note": "Drow lineage increases to 120 ft",
            },
            "Elven Lineage": {
                "description": (
                    "Choose one lineage. Grants Darkvision changes and spells "
                    "at character levels 1, 3, and 5. Spellcasting ability: "
                    "INT, WIS, or CHA (chosen when lineage is selected)."
                ),
                "lineages": {
                    "Drow": {
                        "darkvision_ft": 120,
                        "level_1_cantrip": "Dancing Lights",
                        "level_3_spell": "Faerie Fire",
                        "level_5_spell": "Darkness",
                    },
                    "High Elf": {
                        "level_1_cantrip": (
                            "Prestidigitation (replaceable with any Wizard cantrip on Long Rest)"
                        ),
                        "level_3_spell": "Detect Magic",
                        "level_5_spell": "Misty Step",
                    },
                    "Wood Elf": {
                        "speed_bonus_ft": 5,  # speed becomes 35 ft
                        "level_1_cantrip": "Druidcraft",
                        "level_3_spell": "Longstrider",
                        "level_5_spell": "Pass without Trace",
                    },
                },
            },
            "Fey Ancestry": {
                "description": "Advantage on saves to avoid or end the Charmed condition.",
            },
            "Keen Senses": {
                "description": (
                    "Proficiency in Insight, Perception, or Survival (player's choice)."
                ),
            },
            "Trance": {
                "description": (
                    "No need to sleep; magic cannot put you to sleep. "
                    "Can finish a Long Rest in 4 hours of trance-like meditation."
                ),
            },
        },
    },
    "Gnome": {  # p.85
        "creature_type": "Humanoid",
        "size": "Small",
        "speed": 30,
        "traits": {
            "Darkvision": {
                "range_ft": 60,
            },
            "Gnomish Cunning": {
                "description": "Advantage on INT, WIS, and CHA saving throws.",
            },
            "Gnomish Lineage": {
                "description": (
                    "Choose one lineage. Spellcasting ability: INT, WIS, or CHA "
                    "(chosen when lineage is selected)."
                ),
                "lineages": {
                    "Forest Gnome": {
                        "cantrip": "Minor Illusion",
                        "innate_spell": "Speak with Animals",
                        "innate_uses": "Proficiency Bonus per Long Rest (no slot required)",
                    },
                    "Rock Gnome": {
                        "cantrips": ["Mending", "Prestidigitation"],
                        "feature": (
                            "Spend 10 min casting Prestidigitation to create a Tiny "
                            "clockwork device (AC 5, 1 HP). Up to 3 at once; each lasts 8 hours."
                        ),
                    },
                },
            },
        },
    },
    "Goliath": {  # p.85–86
        "creature_type": "Humanoid",
        "size": "Medium",
        "speed": 35,
        "traits": {
            "Giant Ancestry": {
                "description": "Choose one supernatural boon from the options below.",
                "uses": "Proficiency Bonus per Long Rest",
                "options": {
                    "Cloud's Jaunt (Cloud Giant)": "Bonus Action: teleport up to 30 ft.",
                    "Fire's Burn (Fire Giant)": "On hit: deal extra 1d10 Fire damage.",
                    "Frost's Chill (Frost Giant)": "On hit: 1d6 Cold + reduce Speed by 10 ft.",
                    "Hill's Tumble (Hill Giant)": "On hit vs Large or smaller: give Prone.",
                    "Stone's Endurance (Stone Giant)": "Reaction: 1d12+CON mod reduces damage.",
                    "Storm's Thunder (Storm Giant)": "Reaction: deal 1d8 Thunder to attacker.",
                },
            },
            "Large Form": {
                "prerequisite": "character level 5",
                "description": (
                    "Bonus Action: become Large for 10 min. Advantage on STR checks; Speed +10 ft."
                ),
                "uses": "1 per Long Rest",
            },
            "Powerful Build": {
                "description": (
                    "Advantage on checks to end Grappled condition. "
                    "Count as one size larger for carrying capacity."
                ),
            },
        },
    },
    "Halfling": {  # p.86
        "creature_type": "Humanoid",
        "size": "Small",
        "speed": 30,
        "traits": {
            "Brave": {
                "description": "Advantage on saves to avoid or end the Frightened condition.",
            },
            "Halfling Nimbleness": {
                "description": (
                    "Can move through the space of any creature one size larger, "
                    "but can't stop in the same space."
                ),
            },
            "Luck": {
                "description": (
                    "When you roll a 1 on the d20 of a D20 Test, reroll and must use the new roll."
                ),
            },
            "Naturally Stealthy": {
                "description": (
                    "Can take the Hide action even when obscured only by a creature "
                    "at least one size larger."
                ),
            },
        },
    },
    "Human": {  # p.86
        "creature_type": "Humanoid",
        "size": "Medium or Small (player's choice)",
        "speed": 30,
        "traits": {
            "Resourceful": {
                "description": "Gain Heroic Inspiration whenever you finish a Long Rest.",
            },
            "Skillful": {
                "description": "Gain proficiency in one skill of your choice.",
            },
            "Versatile": {
                "description": "Gain one Origin feat of your choice.",
            },
        },
    },
    "Orc": {  # p.86
        "creature_type": "Humanoid",
        "size": "Medium",
        "speed": 30,
        "traits": {
            "Adrenaline Rush": {
                "description": (
                    "Bonus Action: take the Dash action and gain Temporary HP "
                    "equal to your Proficiency Bonus."
                ),
                "uses": "Proficiency Bonus per Short or Long Rest",
            },
            "Darkvision": {
                "range_ft": 120,
            },
            "Relentless Endurance": {
                "description": (
                    "When reduced to 0 HP but not killed outright, drop to 1 HP instead."
                ),
                "uses": "1 per Long Rest",
            },
        },
    },
    "Tiefling": {  # p.86
        "creature_type": "Humanoid",
        "size": "Medium or Small (player's choice)",
        "speed": 30,
        "traits": {
            "Darkvision": {
                "range_ft": 60,
            },
            "Fiendish Legacy": {
                "description": (
                    "Choose one legacy. Grants resistance and spells at "
                    "character levels 1, 3, and 5. Spellcasting ability: "
                    "INT, WIS, or CHA (chosen when legacy is selected)."
                ),
                "legacies": {
                    "Abyssal": {
                        "resistance": "Poison damage",
                        "level_1_cantrip": "Poison Spray",
                        "level_3_spell": "Ray of Sickness",
                        "level_5_spell": "Hold Person",
                    },
                    "Chthonic": {
                        "resistance": "Necrotic damage",
                        "level_1_cantrip": "Chill Touch",
                        "level_3_spell": "False Life",
                        "level_5_spell": "Ray of Enfeeblement",
                    },
                    "Infernal": {
                        "resistance": "Fire damage",
                        "level_1_cantrip": "Fire Bolt",
                        "level_3_spell": "Hellish Rebuke",
                        "level_5_spell": "Darkness",
                    },
                },
            },
            "Otherworldly Presence": {
                "description": (
                    "Know the Thaumaturgy cantrip. "
                    "Uses the same spellcasting ability as Fiendish Legacy."
                ),
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Backgrounds  (SRD 5.2.1 p.83)
# Each background lists three eligible ability scores.
# The player may distribute +2/+1 or +1/+1/+1 across those three abilities.
# No increase may raise a score above 20.
# ---------------------------------------------------------------------------

BACKGROUNDS: Final[dict[str, dict[str, Any]]] = {
    "Acolyte": {
        "ability_scores_eligible": ["INT", "WIS", "CHA"],
        "origin_feat": "Magic Initiate (Cleric)",
        "skill_proficiencies": ["Insight", "Religion"],
        "tool_proficiency": "Calligrapher's Supplies",
        "starting_equipment": {
            "option_a": [
                "Calligrapher's Supplies",
                "Book (prayers)",
                "Holy Symbol",
                "Parchment (10 sheets)",
                "Robe",
                "8 GP",
            ],
            "option_b": ["50 GP"],
        },
    },
    "Criminal": {
        "ability_scores_eligible": ["DEX", "CON", "INT"],
        "origin_feat": "Alert",
        "skill_proficiencies": ["Sleight of Hand", "Stealth"],
        "tool_proficiency": "Thieves' Tools",
        "starting_equipment": {
            "option_a": [
                "2 Daggers",
                "Thieves' Tools",
                "Crowbar",
                "2 Pouches",
                "Traveler's Clothes",
                "16 GP",
            ],
            "option_b": ["50 GP"],
        },
    },
    "Sage": {
        "ability_scores_eligible": ["CON", "INT", "WIS"],
        "origin_feat": "Magic Initiate (Wizard)",
        "skill_proficiencies": ["Arcana", "History"],
        "tool_proficiency": "Calligrapher's Supplies",
        "starting_equipment": {
            "option_a": [
                "Quarterstaff",
                "Calligrapher's Supplies",
                "Book (history)",
                "Parchment (8 sheets)",
                "Robe",
                "8 GP",
            ],
            "option_b": ["50 GP"],
        },
    },
    "Soldier": {
        "ability_scores_eligible": ["STR", "DEX", "CON"],
        "origin_feat": "Savage Attacker",
        "skill_proficiencies": ["Athletics", "Intimidation"],
        "tool_proficiency": "One kind of Gaming Set (player's choice)",
        "starting_equipment": {
            "option_a": [
                "Spear",
                "Shortbow",
                "20 Arrows",
                "Gaming Set (same as proficiency)",
                "Healer's Kit",
                "Quiver",
                "Traveler's Clothes",
                "14 GP",
            ],
            "option_b": ["50 GP"],
        },
    },
}

# ---------------------------------------------------------------------------
# Feats  (SRD 5.2.1 pp.87–95)
# ---------------------------------------------------------------------------

# Origin feats — granted by backgrounds; no level prerequisite.
ORIGIN_FEATS: Final[dict[str, dict[str, Any]]] = {
    "Alert": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": False,
        "effects": {
            "Initiative Proficiency": (
                "When you roll Initiative, add your Proficiency Bonus to the roll."
            ),
            "Initiative Swap": (
                "Immediately after rolling Initiative, you may swap your result "
                "with that of one willing ally (neither may have the Incapacitated condition)."
            ),
        },
    },
    "Magic Initiate (Cleric)": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": True,
        "repeatable_note": "Each time, choose a different spell list.",
        "spell_list": "Cleric",
        "effects": {
            "Two Cantrips": (
                "Learn two Cleric cantrips. Spellcasting ability: INT, WIS, or CHA "
                "(choose when selecting this feat)."
            ),
            "Level 1 Spell": (
                "Choose one level 1 Cleric spell. Always prepared; "
                "cast once per Long Rest without a slot. "
                "Can also cast it using any spell slots you have."
            ),
            "Spell Swap": (
                "On gaining a level, may replace one chosen spell with another of the same level."
            ),
        },
    },
    "Magic Initiate (Druid)": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": True,
        "repeatable_note": "Each time, choose a different spell list.",
        "spell_list": "Druid",
        "effects": {
            "Two Cantrips": ("Learn two Druid cantrips. Spellcasting ability: INT, WIS, or CHA."),
            "Level 1 Spell": (
                "Choose one level 1 Druid spell. Always prepared; "
                "cast once per Long Rest without a slot."
            ),
            "Spell Swap": (
                "On gaining a level, may replace one chosen spell with another of the same level."
            ),
        },
    },
    "Magic Initiate (Wizard)": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": True,
        "repeatable_note": "Each time, choose a different spell list.",
        "spell_list": "Wizard",
        "effects": {
            "Two Cantrips": ("Learn two Wizard cantrips. Spellcasting ability: INT, WIS, or CHA."),
            "Level 1 Spell": (
                "Choose one level 1 Wizard spell. Always prepared; "
                "cast once per Long Rest without a slot."
            ),
            "Spell Swap": (
                "On gaining a level, may replace one chosen spell with another of the same level."
            ),
        },
    },
    "Savage Attacker": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": False,
        "effects": {
            "Powerful Strikes": (
                "Once per turn when you hit with a weapon, roll the weapon's damage dice "
                "twice and use either roll."
            ),
        },
    },
    "Skilled": {
        "category": "Origin",
        "prerequisite": None,
        "repeatable": True,
        "repeatable_note": "Can be taken more than once.",
        "effects": {
            "Three Proficiencies": (
                "Gain proficiency in any combination of three skills or tools of your choice."
            ),
        },
    },
}

# General feats — require level 4+.
GENERAL_FEATS: Final[dict[str, dict[str, Any]]] = {
    "Ability Score Improvement": {
        "category": "General",
        "prerequisite": "Level 4+",
        "repeatable": True,
        "effects": {
            "Score Increase": (
                "Increase one ability score by 2, or two ability scores by 1 each. "
                "No score may exceed 20."
            ),
        },
    },
    "Grappler": {
        "category": "General",
        "prerequisite": "Level 4+, STR or DEX 13+",
        "repeatable": False,
        "effects": {
            "Ability Score Increase": "Increase STR or DEX by 1 (max 20).",
            "Punch and Grab": (
                "When you hit with an Unarmed Strike as part of the Attack action, "
                "you can use both the Damage and Grapple option. Once per turn."
            ),
            "Attack Advantage": "Advantage on attack rolls against a Grappled creature.",
            "Fast Wrestler": (
                "No extra movement cost to move a creature Grappled by you "
                "if it is your size or smaller."
            ),
        },
    },
}

# Fighting Style feats — require the Fighting Style class feature.
FIGHTING_STYLE_FEATS: Final[dict[str, dict[str, Any]]] = {
    "Archery": {
        "category": "Fighting Style",
        "prerequisite": "Fighting Style feature",
        "effects": {
            "+2 to ranged attack rolls": "Gain +2 bonus to attack rolls with Ranged weapons.",
        },
    },
    "Defense": {
        "category": "Fighting Style",
        "prerequisite": "Fighting Style feature",
        "effects": {
            "+1 AC while armored": ("While wearing Light, Medium, or Heavy armor, gain +1 to AC."),
        },
    },
    "Great Weapon Fighting": {
        "category": "Fighting Style",
        "prerequisite": "Fighting Style feature",
        "effects": {
            "Reroll 1s and 2s": (
                "When rolling damage for a melee weapon held in two hands, "
                "treat any 1 or 2 on a damage die as a 3. "
                "Weapon must have Two-Handed or Versatile property."
            ),
        },
    },
    "Two-Weapon Fighting": {
        "category": "Fighting Style",
        "prerequisite": "Fighting Style feature",
        "effects": {
            "Modifier to extra attack": (
                "When making an extra attack with a Light weapon, "
                "add your ability modifier to its damage if you aren't already doing so."
            ),
        },
    },
}

# Epic Boon feats — require level 19+.
EPIC_BOON_FEATS: Final[dict[str, dict[str, Any]]] = {
    "Boon of Combat Prowess": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase one ability score by 1 (max 30).",
            "Peerless Aim": (
                "When you miss with an attack roll, you can hit instead. Once per turn."
            ),
        },
    },
    "Boon of Dimensional Travel": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase one ability score by 1 (max 30).",
            "Blink Steps": (
                "Immediately after the Attack or Magic action, "
                "teleport up to 30 ft to an unoccupied visible space."
            ),
        },
    },
    "Boon of Fate": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase one ability score by 1 (max 30).",
            "Improve Fate": (
                "When a creature within 60 ft succeeds or fails a D20 Test, "
                "roll 2d4 and apply total as bonus or penalty. "
                "Once per Initiative or Short/Long Rest."
            ),
        },
    },
    "Boon of Irresistible Offense": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase STR or DEX by 1 (max 30).",
            "Overcome Defenses": (
                "Bludgeoning, Piercing, and Slashing damage you deal always ignores Resistance."
            ),
            "Overwhelming Strike": (
                "On a d20 roll of 20 for an attack, deal extra damage equal to "
                "the affected ability score (same type as attack)."
            ),
        },
    },
    "Boon of Spell Recall": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+, Spellcasting feature",
        "effects": {
            "Ability Score Increase": "Increase INT, WIS, or CHA by 1 (max 30).",
            "Free Casting": (
                "When casting a level 1–4 spell, roll 1d4. "
                "If the result equals the slot's level, the slot is not expended."
            ),
        },
    },
    "Boon of the Night Spirit": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase one ability score by 1 (max 30).",
            "Merge with Shadows": (
                "While in Dim Light or Darkness: Bonus Action to gain Invisible condition "
                "(ends on Action, Bonus Action, or Reaction)."
            ),
            "Shadowy Form": (
                "While in Dim Light or Darkness: Resistance to all damage "
                "except Psychic and Radiant."
            ),
        },
    },
    "Boon of Truesight": {
        "category": "Epic Boon",
        "prerequisite": "Level 19+",
        "effects": {
            "Ability Score Increase": "Increase one ability score by 1 (max 30).",
            "Truesight": "Gain Truesight with a range of 60 feet.",
        },
    },
}

# Flat lookup across all feat categories: name → data dict
ALL_FEATS: Final[dict[str, dict[str, Any]]] = {
    **ORIGIN_FEATS,
    **GENERAL_FEATS,
    **FIGHTING_STYLE_FEATS,
    **EPIC_BOON_FEATS,
}
