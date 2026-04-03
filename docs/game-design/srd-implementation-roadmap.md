# SRD Implementation Roadmap

- **Status**: Accepted
- **Date**: 2026-04-03
- **Author**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/core/` (Rules Engine), `scripts/srd_import/` (Import Pipeline), `scripts/schemas/` (Data Schemas), database seed data
- **References**: ADR-0001 (SRD Rules Engine), ADR-0002 (Claude as Narrator), ADR-0004 (Campaign and Session Lifecycle), ADR-0009 (Interactive Dice Rolling)

## Purpose

This document defines the phased implementation plan for the SRD 5.2.1 rules in Tavern's Rules Engine. It answers three questions: what to implement in each phase, what SRD data to import in each phase, and what the dependency order is between engine features and data imports.

The SRD is not a linear document. It is a dependency graph — spells reference conditions, conditions reference saving throws, class features reference spells and conditions and action types. The phases in this roadmap are not defined by SRD chapters but by **gameplay capabilities**: what can a player do at the end of each phase that they could not do before?

## SRD Document Segmentation

The SRD 5.2.1 PDF (~361 pages) is segmented into the following import blocks. Each block gets its own JSON Schema in `scripts/schemas/` and is imported independently through the pipeline defined in ADR-0001.

| Block ID | SRD Section | Content | Approx. Pages | Schema File |
|---|---|---|---|---|
| `species` | Chapter 2 | Species and subspecies traits, sizes, speeds, special abilities | ~15 | `species.json` |
| `classes` | Chapter 3 | Class tables, hit dice, proficiencies, features by level, subclasses | ~80 | `class.json`, `class_feature.json`, `subclass.json` |
| `backgrounds` | Chapter 4 | Background ability bonuses, skill proficiencies, tool proficiencies, Origin feats | ~10 | `background.json` |
| `feats` | Chapter 5 | Feat prerequisites, effects, choices | ~15 | `feat.json` |
| `equipment` | Chapter 6 | Weapons (properties, damage, range), armor (AC, type), adventuring gear, tools, mounts, trade goods | ~20 | `weapon.json`, `armor.json`, `equipment.json` |
| `spells` | Chapter 7 | Spell definitions — all levels, all classes | ~100 | `spell.json` |
| `monsters` | Appendix / Bestiary | Monster stat blocks, actions, traits, legendary actions, CR | ~80 | `monster.json`, `monster_action.json`, `monster_trait.json` |
| `conditions` | Rules Glossary | Condition definitions and mechanical effects | ~5 | `condition.json` |
| `magic_items` | Chapter 8 (if present) | Magic item properties, attunement, rarity | ~20 | `magic_item.json` |
| `rules_tables` | Various | XP thresholds, proficiency bonus by level, starting wealth, spell slot tables, multiclass tables | ~5 | `rules_table.json` |

### Schema Design Principles

Schemas are the contract between the import pipeline and the Rules Engine. They define what the engine needs, not what the SRD says. Design rules:

1. **Engine-first**: Every field in a schema must correspond to something the Rules Engine will read. Flavour text is stored as a single `description` string, not parsed into structured fields.
2. **Mechanical completeness**: If a spell requires concentration, the schema must have `requires_concentration: boolean`. If a weapon has the Finesse property, the schema must encode that. Missing mechanical fields are bugs in the schema, not in the extraction.
3. **Forward-compatible**: Schemas for Phase 1 must not break when Phase 2 fields are added. Use optional fields with defaults for mechanics not yet implemented. Example: `concentration` is in the spell schema from Phase 1 even though the engine does not enforce it until Phase 2. The data is imported correctly; the engine ignores it until ready.
4. **Flat over nested where possible**: A spell's `higher_levels` scaling is a flat table (`{slot_level: int, effect: string}`), not a nested object hierarchy. Flat structures are easier to validate, easier to query, and harder to get wrong during extraction.
5. **Enum-constrained**: Fields like `damage_type`, `ability`, `school`, `condition` use closed enums. If Claude's extraction produces a value outside the enum, validation catches it before it enters the database.

### Import Order

Not all blocks can be imported independently. The dependency graph:

```
rules_tables ──→ (no dependencies — import first)
conditions   ──→ (no dependencies)
species      ──→ (no dependencies)
backgrounds  ──→ feats (Origin feat references)
equipment    ──→ (no dependencies)
classes      ──→ equipment (starting equipment), feats (ASI references)
feats        ──→ spells (Magic Initiate references), conditions (some feat effects)
spells       ──→ conditions (spell effects), equipment (material components — metadata only)
monsters     ──→ spells (innate spellcasting), conditions (trait effects), equipment (weapon attacks)
magic_items  ──→ spells (item spells), equipment (base item references)
```

Within each phase, import in topological order: dependencies before dependents.

---

## Phase 1: Playable — "A solo character can adventure"

### Exit Criterion

A single player can: create a Level 1 character (any of the 12 SRD classes), start a campaign, explore the world via narrative, enter combat with basic enemies, take and deal damage, cast cantrips and Level 1 spells, level up to Level 5, and resume the campaign across sessions. The mechanical outcomes are correct — attack rolls hit or miss at the right thresholds, damage is calculated correctly, spell slots are tracked.

### Level Cap: 5

Level 5 is the natural boundary. It is where martial classes get Extra Attack, spellcasters get Level 3 spells, and the Proficiency Bonus increases for the first time. The game changes character at Level 5 — before it, characters are fragile and limited; after it, they are competent adventurers. A campaign that reaches Level 5 has provided a complete D&D arc.

### Rules Engine Features

#### 1.1 Dice Subsystem (`core/dice.py`)

The foundation for every other mechanic.

- Standard dice: d4, d6, d8, d10, d12, d20, d100
- Dice expressions: `2d6+3`, `1d20+5`, `4d6kh3` (keep highest 3, for ability score generation)
- Advantage and disadvantage: roll 2d20, take higher/lower
- Deterministic seeding for tests
- Modifier application and threshold comparison (`roll + modifier >= target`)

**No dependencies.** This is implemented first.

#### 1.2 Ability Score Subsystem (`core/characters.py`)

The second foundation — nearly every roll in the game references an ability score.

- Six abilities: STR, DEX, CON, INT, WIS, CHA
- Modifier calculation: `floor((score - 10) / 2)`
- Ability checks: d20 + ability modifier (+ proficiency bonus if proficient)
- Saving throws: d20 + ability modifier (+ proficiency bonus if proficient in that save)
- Skill checks: d20 + ability modifier (+ proficiency bonus if proficient, + proficiency bonus again if expertise)
- Proficiency bonus by level (from `rules_tables`)
- Standard Array: [15, 14, 13, 12, 10, 8]
- Point Buy: 27-point budget, costs per score
- Random generation: 4d6 drop lowest, six times

**Depends on**: 1.1 (dice).

#### 1.3 Character Creation (`core/characters.py`)

Produces a valid Level 1 character.

- Species selection: apply traits (darkvision, speed, size, resistances, extra proficiencies)
- Class selection: apply hit die, saving throw proficiencies, armor/weapon proficiencies, skill choices, starting HP (max hit die + CON modifier)
- Background selection: apply +2/+1 or +1/+1/+1 to background's ability scores, skill proficiencies, tool proficiency, Origin feat
- Ability score assignment: chosen method → assign to abilities → apply background bonuses → enforce max 20
- Starting equipment: class equipment package or background equipment package (or 50 GP alternative)
- Languages: Common + 2 chosen from Standard Languages
- Spellcasting setup (if applicable): cantrips known, spells prepared/known, spell slots at Level 1, spell attack bonus, spell save DC
- Validation: all fields populated, no illegal combinations, scores within bounds

**Depends on**: 1.1, 1.2. **Data dependencies**: `species`, `classes` (Level 1 only), `backgrounds`, `feats` (Origin feats only), `equipment` (starting packages), `spells` (Level 0-1 for spellcasting classes).

#### 1.4 Basic Combat (`core/combat.py`)

Enough combat to fight goblins and survive.

- Initiative: d20 + DEX modifier, descending order, DEX tiebreak
- Attack rolls: d20 + ability modifier + proficiency bonus vs. AC
- Melee attacks: STR-based (or DEX for Finesse weapons)
- Ranged attacks: DEX-based, normal range / long range (disadvantage)
- Damage rolls: weapon damage dice + ability modifier
- Critical hits: natural 20, double the damage dice
- Critical misses: natural 1, always miss regardless of modifiers
- HP tracking: current HP, max HP, damage application, healing application
- Death at 0 HP: character falls Unconscious (simplified — no Death Saves yet)
- AC calculation: base AC from armor + DEX modifier (capped by armor type) + shield bonus
- Turn structure: Movement, Action, Bonus Action (if available), free object interaction

**Not included in Phase 1 combat**: Opportunity Attacks, Death Saving Throws, Grapple/Shove, Cover, Two-Weapon Fighting as a mechanical subsystem (it works as a Bonus Action but without the detailed rules), Reactions other than basic readied actions.

**Depends on**: 1.1, 1.2. **Data dependencies**: `equipment` (weapons, armor), `rules_tables` (proficiency bonus).

#### 1.5 Basic Spellcasting (`core/spells.py`)

Enough spellcasting that a Wizard or Cleric is playable.

- Spell slot tracking: slots per level per class (from `rules_tables`)
- Spell slot consumption: casting a spell uses a slot of the spell's level or higher
- Cantrips: castable unlimited times, no slot consumption
- Spell attack rolls: d20 + spellcasting ability modifier + proficiency bonus vs. AC
- Spell save DC: 8 + proficiency bonus + spellcasting ability modifier, target rolls saving throw
- Damage spells: roll damage dice as specified in spell data, apply to target
- Healing spells: roll healing dice, apply to target (cannot exceed max HP)
- Spell slot recovery: all slots recover on Long Rest (Warlock Pact Magic deferred to Phase 2)

**Not included in Phase 1 spellcasting**: Concentration tracking, Ritual Casting, Upcasting, Reaction spells (Shield, Counterspell), Area of Effect geometry, Components (material, somatic, verbal) as mechanical constraints.

**Depends on**: 1.1, 1.2, 1.4 (for spell attacks and saves in combat). **Data dependencies**: `spells` (cantrips + Level 1-3 spells for the 12 classes), `rules_tables` (spell slot tables).

#### 1.6 Conditions — Minimal Set (`core/conditions.py`)

Only the conditions required for Phase 1 combat to function.

| Condition | Why Phase 1 | Mechanical Effect |
|---|---|---|
| Unconscious | 0 HP | Falls prone, drops items, fails STR/DEX saves, attacks against have advantage, melee hits are auto-crits |
| Prone | Knocked down, common | Disadvantage on attack rolls, melee attacks against have advantage, ranged attacks against have disadvantage, costs half movement to stand |
| Grappled | Common monster ability | Speed 0, ends if grappler is incapacitated or target is moved out of reach |
| Frightened | Common monster ability, some spells | Disadvantage on ability checks and attacks while source is in line of sight, cannot willingly move closer to source |
| Poisoned | Common in low-level encounters | Disadvantage on attack rolls and ability checks |

**Not included**: Blinded, Charmed, Deafened, Incapacitated, Invisible, Paralyzed, Petrified, Restrained, Stunned, Exhaustion. These are added in Phase 2.

Condition tracking per character: active conditions list, source, duration (rounds or indefinite), auto-removal at end/start of turn where applicable.

**Depends on**: 1.2 (ability modifiers for save effects). No data dependency beyond the hardcoded condition definitions.

#### 1.7 Level-Up: Levels 1–5 (`core/characters.py`)

Character progression through the Phase 1 level cap.

- HP gain on level-up: roll hit die or take fixed value (class-dependent) + CON modifier
- Proficiency bonus increase: +2 at Levels 1-4, +3 at Level 5
- Ability Score Improvement (ASI) at Level 4: +2 to one ability or +1 to two abilities (max 20), or choose a Feat
- Subclass selection at Level 3: one subclass per class (SRD provides exactly one)
- New class features at each level (from class data)
- New spell slots (from `rules_tables`)
- New spells known/prepared (class-dependent)
- Extra Attack at Level 5 (Fighter, Paladin, Ranger, Monk, Barbarian)

**Depends on**: 1.2, 1.3, 1.5. **Data dependencies**: `classes` (features for Levels 1-5), `subclass` (Level 3 features), `feats` (for ASI alternative), `spells` (Level 2-3 spells), `rules_tables`.

#### 1.8 Rest Mechanics — Simplified (`core/characters.py`)

- Long Rest: restore all HP, restore all spell slots. Requires 8 hours (narratively, not mechanically timed).
- Short Rest: roll hit dice to heal. Warlock Pact Magic slot recovery deferred to Phase 2.

**Depends on**: 1.2, 1.5.

### SRD Data Imports — Phase 1

| Block | Scope | Estimated Records | Priority |
|---|---|---|---|
| `rules_tables` | Proficiency bonus, XP thresholds (Levels 1-5), spell slot tables (all classes, Levels 1-5), ability score point buy costs | ~10 tables | P0 — import first |
| `conditions` | 5 conditions (Unconscious, Prone, Grappled, Frightened, Poisoned) — mechanical effects only | 5 | P0 |
| `species` | All SRD species with subspecies: Human, Elf (High, Wood), Dwarf (Hill, Mountain), Halfling (Lightfoot, Stout), Dragonborn, Gnome (Forest, Rock), Half-Elf, Half-Orc, Tiefling | ~15 | P1 |
| `backgrounds` | All SRD backgrounds with ability bonuses, proficiencies, and Origin feat references | ~16 | P1 |
| `equipment` | Simple weapons, martial weapons, light/medium/heavy armor, shields, adventuring packs, starting equipment packages | ~80 | P1 |
| `feats` | Origin feats only (those selectable through backgrounds at character creation) | ~12 | P1 |
| `classes` | All 12 classes, Levels 1-5 only: class table, hit dice, proficiencies, features. One subclass per class at Level 3 | 12 classes, ~60 features | P2 |
| `spells` | Cantrips + Level 1-3 spells for all classes. Include `requires_concentration` and `ritual` fields even though engine ignores them in Phase 1 | ~120 spells | P2 |
| `monsters` | Starter set: CR 0-3 monsters commonly encountered at Levels 1-5. Goblin, Skeleton, Zombie, Wolf, Giant Rat, Bandit, Kobold, Orc, Ogre, Owlbear, Giant Spider, Bugbear, Gnoll, Gelatinous Cube, Mimic | ~30 | P3 |

Priority rationale: P0 blocks have no dependencies and are small — import them first to establish the schema pipeline. P1 blocks are needed for character creation. P2 blocks are needed for gameplay. P3 blocks (monsters) are needed for combat encounters but Claude can improvise with placeholder stats while the import is in progress.

### Phase 1 Exclusions — Explicit

These are **not** in Phase 1. Listing them explicitly prevents scope creep:

- Multiclassing
- Death Saving Throws (character dies at 0 HP — harsh but simple)
- Concentration tracking for spells
- Ritual casting
- Spell upcasting (casting at a higher slot level for increased effect)
- Reaction spells (Shield, Counterspell, Absorb Elements)
- Opportunity Attacks
- Area of Effect geometry (spells affect targets narratively, Claude decides who is in the area)
- Cover mechanics (+2/+5 AC)
- Two-Weapon Fighting as a rules subsystem
- Exhaustion levels
- Magic items
- Mounted combat, underwater combat
- Encounter building (CR calculations, XP budgets)
- Interactive dice rolling (ADR-0009) — Phase 1 uses `automatic` roll mode only

---

## Phase 2: Pareto — "80% of the SRD, 100% of common play"

### Exit Criterion

An experienced D&D player can run a full Level 1-20 campaign without encountering missing mechanics in normal play. Edge cases (mounted combat, underwater rules, obscure condition interactions) may be unimplemented, but a Wizard can Counterspell, a Fighter can make Opportunity Attacks, and Death Saving Throws work correctly. The interactive dice rolling system (ADR-0009) is functional.

### Level Cap: 20

Full character progression.

### Rules Engine Features

#### 2.1 Complete Combat Subsystem (`core/combat.py`)

- Opportunity Attacks: triggered by leaving a hostile creature's reach without Disengage
- Death Saving Throws: 3 successes = stabilize, 3 failures = death, natural 20 = regain 1 HP, natural 1 = 2 failures, damage at 0 HP = failed save (melee crit = 2 failures)
- Grapple and Shove as Actions: Athletics check vs. Athletics or Acrobatics
- Two-Weapon Fighting: Bonus Action attack with light weapon, no ability modifier to damage (unless Fighting Style)
- Cover: half cover (+2 AC, +2 DEX saves), three-quarters cover (+5 AC, +5 DEX saves)
- Dodge Action: attacks against have disadvantage, advantage on DEX saves
- Help Action: give advantage on next attack or ability check
- Ready Action: set trigger and reaction
- Object interactions: drawing weapons, opening doors, picking up items

#### 2.2 All SRD Conditions (`core/conditions.py`)

Full condition list with interaction rules:

| Condition | Key Mechanical Effect |
|---|---|
| Blinded | Cannot see, auto-fail sight checks, attacks have disadvantage, attacks against have advantage |
| Charmed | Cannot attack charmer, charmer has advantage on social checks |
| Deafened | Cannot hear, auto-fail hearing checks |
| Frightened | (already in Phase 1, enhanced with line-of-sight tracking) |
| Incapacitated | Cannot take actions or reactions |
| Invisible | Heavily obscured, advantage on attacks, attacks against have disadvantage |
| Paralyzed | Incapacitated, auto-fail STR/DEX saves, attacks have advantage, melee crits |
| Petrified | Transformed to stone, weight x10, resistance to all damage, immune to poison/disease |
| Restrained | Speed 0, attacks have disadvantage, attacks against have advantage, disadvantage on DEX saves |
| Stunned | Incapacitated, auto-fail STR/DEX saves, attacks against have advantage |
| Exhaustion | 6 levels with escalating penalties per SRD 5.2.1 rules |

Condition interaction rules: Paralyzed implies Incapacitated, Petrified implies Incapacitated, Stunned implies Incapacitated. The engine enforces these implications — applying Paralyzed automatically applies Incapacitated; removing Paralyzed removes the implied Incapacitated only if no other condition implies it.

#### 2.3 Complete Spellcasting (`core/spells.py`)

- Concentration: one spell at a time, Constitution save on damage (DC = max(10, damage/2)), concentration broken on Incapacitated/killed
- Ritual Casting: cast without spell slot, +10 minutes casting time (narratively tracked, not mechanically timed in Phase 2)
- Upcasting: cast at higher slot level for increased effect (per spell data)
- Reaction spells: Shield (+5 AC until next turn), Counterspell (ability check to counter higher-level spells), Absorb Elements, Hellish Rebuke
- Area of Effect geometry: sphere (point of origin + radius), cone (point of origin + length), cube (point of origin + side), line (point of origin + length + width), cylinder (point of origin + radius + height). Target resolution determines which creatures are affected.
- Components: Verbal (cannot cast if silenced), Somatic (need a free hand), Material (consumed vs. non-consumed, gold cost threshold for focus substitution)
- Pact Magic: Warlock's short-rest slot recovery, separate slot progression

#### 2.4 Full Level Progression: Levels 1–20 (`core/characters.py`)

- All class features for all 12 classes at all 20 levels
- All 12 SRD subclasses with full feature progression
- Multiclassing: prerequisites, proficiency gain rules, spell slot calculation for multiclass spellcasters
- Ability Score Improvements at all applicable levels (4, 8, 12, 16, 19 — class-dependent)
- Feat selection at any ASI (full SRD feat list)
- Cantrip scaling (damage increases at Levels 5, 11, 17)

#### 2.5 Rest Mechanics — Complete (`core/characters.py`)

- Short Rest: Hit Dice recovery (roll to heal), class feature recharge (Fighter's Second Wind, Warlock Pact Magic slots, Monk Ki points, etc.)
- Long Rest: Full HP, all spell slots, half of total Hit Dice recovered (minimum 1), class feature recharge (all features)
- Long Rest interruption: 1 hour of strenuous activity resets the rest timer

#### 2.6 Interactive Dice Rolling (`core/combat.py`, `api/`)

Implementation of ADR-0009:

- Player-triggered rolls with pre-roll options (Reckless Attack, Elven Accuracy, etc.)
- Self-reaction window (Lucky, Halfling Lucky, etc.)
- Cross-player reaction window with timer (default 15 seconds)
- NPC reaction decisions via Claude (Counterspell, Legendary Resistance, Shield)
- All three roll modes: interactive, automatic, hybrid
- WebSocket events for the full roll lifecycle

#### 2.7 Monster Abilities (`core/combat.py`)

- Multiattack: multiple attacks per turn following stat block patterns
- Special abilities: breath weapons (recharge mechanic), frightful presence, pack tactics
- Legendary Actions: limited pool per round, taken at end of other creatures' turns
- Legendary Resistance: auto-succeed a failed save, limited uses per day
- Lair Actions: triggered on initiative count 20
- Innate Spellcasting: spells cast without spell slots, per-day limits

### SRD Data Imports — Phase 2

| Block | Scope | Estimated Records |
|---|---|---|
| `classes` | Full Level 1-20 progression for all 12 classes, all features | ~200 features |
| `subclass` | Complete subclass feature tables | ~48 features |
| `spells` | All remaining SRD spells (Levels 4-9, plus any Level 1-3 spells not in Phase 1) | ~280 spells |
| `monsters` | Full SRD bestiary — all monsters with complete stat blocks, actions, traits | ~300 monsters |
| `feats` | All non-Origin SRD feats | ~30 feats |
| `conditions` | Remaining 8 conditions (Blinded, Charmed, Deafened, Incapacitated, Invisible, Paralyzed, Petrified, Restrained, Stunned, Exhaustion) | 10 |
| `magic_items` | SRD magic items — armor, weapons, potions, rings, wondrous items | ~50-80 items |
| `rules_tables` | Full Level 1-20 tables, multiclass spell slot table, CR/XP table | ~10 tables |

### Phase 2 Exclusions — Explicit

- Mounted combat
- Underwater combat
- Vehicle rules
- Crafting
- Downtime activities
- Disease and poison as subsystems (beyond the Poisoned condition)
- Trap mechanics (detailed DCs and damage tables)
- Encounter building (CR budget calculations)
- Hirelings and NPC followers
- Wildshape full implementation (basic form change without complete stat block replacement)

---

## Phase 3: Complete — "Every SRD rule is implemented"

### Exit Criterion

A rules lawyer can play Tavern and not find a missing SRD 5.2.1 mechanic. Every rule in the document has a corresponding engine implementation or an explicit, documented decision to handle it narratively (with rationale).

### Rules Engine Features

#### 3.1 Environment and Situational Rules

- Mounted combat: mount initiative, controlled vs. independent mounts, mount reactions
- Underwater combat: disadvantage rules for melee/ranged, swim speed, breathing, spellcasting restrictions
- Falling: 1d6 per 10 feet, max 20d6, landing on creatures
- Suffocation: CON modifier + 1 minutes of breath, then 0 HP after CON modifier rounds
- Vision and light: bright light, dim light (disadvantage on Perception), darkness (Blinded condition)
- Cover: full mechanical implementation with line-of-sight calculations

#### 3.2 Druid Wildshape

Full stat block replacement:

- Replace physical ability scores (STR, DEX, CON) with beast form
- Retain mental ability scores (INT, WIS, CHA)
- Gain beast's HP as temporary pool; excess damage carries over
- Lose access to equipment, speech, somatic/material components
- Retain class features, racial traits, proficiencies if beast form can physically perform them
- Moon Druid adjustments (higher CR forms, combat Wildshape as Bonus Action)

#### 3.3 Encounter Building

- CR-to-XP conversion table
- XP thresholds per character level (Easy, Medium, Hard, Deadly)
- Party size multipliers
- Adjusted XP for encounter groups
- This is primarily a tool for Claude's encounter design, not player-facing — but the engine provides the calculations

#### 3.4 Detailed Subsystems

- Trap mechanics: detection DCs, save DCs, damage by tier
- Disease and poison: onset, duration, save frequency, cure conditions
- Crafting: time, cost, tool requirements (if SRD specifies)
- Downtime activities: training, research, recuperation
- Hirelings: cost per day, loyalty, combat participation
- Lifestyle expenses: daily cost by tier

#### 3.5 Multiclass Edge Cases

- Spell slot calculation for three+ class combinations
- Feature interaction resolution (Extra Attack does not stack, Unarmored Defense does not stack)
- Channel Divinity shared pool for multiclass Clerics/Paladins
- Spellcasting focus rules across classes

### SRD Data Imports — Phase 3

| Block | Scope | Estimated Records |
|---|---|---|
| `monsters` | Any remaining monsters not in Phase 2, with full Lair Action blocks | ~50 |
| `magic_items` | Complete SRD magic item catalog | remaining items |
| `rules_tables` | Trap DCs, disease tables, lifestyle costs, crafting costs, hireling costs | ~15 tables |
| `equipment` | Vehicles, siege equipment, mounts (detailed stats), trade goods (prices) | ~30 |

---

## Cross-Phase Dependencies

Some features span phases. The schema must accommodate this from Phase 1:

| Feature | Phase 1 State | Phase 2 State | Phase 3 State |
|---|---|---|---|
| Concentration | Schema field exists, engine ignores | Engine enforces: CON saves, one-spell limit | No change |
| Spell components | Schema field exists, engine ignores | Engine enforces V/S/M restrictions | No change |
| Ritual tag | Schema field exists, engine ignores | Engine allows ritual casting without slot | No change |
| Multiclassing | Not supported | Full support with spell slot calculation | Edge case coverage |
| Conditions | 5 implemented | All 14 implemented with interactions | No change |
| Area of Effect | Claude decides targets narratively | Engine calculates affected targets from geometry | No change |
| Death Saves | Unconscious at 0 HP, no saves | Full save system (3 successes/failures) | No change |
| Magic items | Not in game | Basic items with attunement | Full catalog |
| Interactive rolling | Automatic mode only | All three modes (interactive, automatic, hybrid) | No change |

The critical design constraint: **Phase 1 schemas must include Phase 2 fields as optional.** This means Claude's extraction in Phase 1 captures `requires_concentration: true` for a spell even though the engine won't check it until Phase 2. The data is correct from import; only the engine behavior changes between phases.

---

## Import Pipeline Workflow

Each phase follows the same import workflow (per ADR-0001):

```
1. Define/update schema     →  scripts/schemas/{block}.json
2. Segment SRD PDF          →  scripts/srd_import/extract.py --section {block}
3. Claude extraction        →  scripts/srd_import/claude_parse.py --section {block} --schema scripts/schemas/{block}.json
4. Schema validation        →  scripts/srd_import/validate.py --output review/{block}.json
5. Human review             →  Reviewer checks review/{block}.json against SRD source
6. Database seed            →  Approved JSON → Alembic seed migration or management command
7. Engine integration test  →  Tests verify engine reads and uses imported data correctly
```

### Batch Sizing for Claude Extraction

The SRD is too large for a single Claude API call. The extraction step must chunk the content:

- **Spells**: Batch by level (all cantrips, then all Level 1 spells, etc.) — each batch is ~10-20 spells, well within context limits
- **Monsters**: Batch by CR range (CR 0-1, CR 2-3, CR 4-6, CR 7-10, CR 11-15, CR 16-20, CR 21+) — each batch is ~20-40 monsters
- **Classes**: One class per batch — each class is ~5-8 pages of features
- **Equipment**: All weapons in one batch, all armor in one batch, adventuring gear in one batch
- **Everything else**: Single batch per block (species, backgrounds, feats, conditions are small enough)

### Validation Rules Beyond Schema

Schema validation catches structural errors (wrong types, missing fields). Additional validation catches semantic errors:

- **Cross-reference integrity**: If a spell references the "Poisoned" condition, that condition must exist in the conditions data
- **Numerical plausibility**: A CR 1 monster with 300 HP is likely an extraction error
- **Completeness checks**: All 12 classes must have features at all levels in their progression range
- **Duplicate detection**: Two spells with the same name but different stats indicate an extraction error
- **Enum coverage**: Every `damage_type` in spell data must be in the damage type enum

---

## Effort Estimation

Rough estimates for calibration, not commitments:

| Phase | Engine Implementation | Data Import + Review | Total |
|---|---|---|---|
| Phase 1 | ~80-120 hours | ~20-30 hours | ~100-150 hours |
| Phase 2 | ~150-200 hours | ~40-60 hours | ~190-260 hours |
| Phase 3 | ~60-80 hours | ~15-20 hours | ~75-100 hours |

Phase 2 is the largest because it contains the complex subsystems (Concentration, AoE geometry, interactive rolling, full condition interactions, multiclassing). Phase 3 is smaller because it consists mostly of niche rules that are individually simple — the architecture to support them already exists from Phase 2.

The data import effort decreases per record over time because the pipeline and schemas stabilize. Phase 1 imports ~270 records with significant schema iteration. Phase 3 imports ~95 records with stable schemas.

---

## Review Triggers

- If Phase 1 takes longer than 3 months of active development, evaluate whether the scope should be reduced (e.g., fewer classes, fewer spells, lower level cap).
- If Claude extraction accuracy falls below 90% for a given block (measured by human review rejection rate), evaluate switching to a third-party SRD database (e.g., 5e-database) for that block.
- If a third-party SRD data library emerges that covers >80% of Tavern's schema requirements, evaluate replacing the import pipeline with a dependency (per ADR-0001 Review Trigger).
- If Phase 2 combat complexity causes the turn lifecycle to exceed 10 seconds of server-side processing (excluding Claude latency), evaluate optimizing the condition interaction engine or pre-computing common interaction chains.
- If the monster import reveals that >20% of SRD monsters require mechanics not planned for their phase (e.g., a CR 2 monster with Legendary Actions), adjust the monster batch boundaries.