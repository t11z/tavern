# SRD Implementation Roadmap

- **Status**: Accepted
- **Date**: 2026-04-03
- **Author**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/core/` (Rules Engine), `backend/tavern/dm/` (DM Layer), `backend/tavern/api/` (Turn Lifecycle), `scripts/srd_import/` (Import Pipeline), `scripts/schemas/` (Data Schemas)
- **References**: ADR-0001 (SRD Rules Engine), ADR-0002 (Claude as Narrator), ADR-0004 (Campaign and Session Lifecycle), ADR-0009 (Interactive Dice Rolling)

## Purpose

This document defines the implementation plan for making Tavern playable and progressively complete. It tracks four parallel workstreams — Rules Engine completion, SRD data import, DM layer integration, and the turn lifecycle — and defines three milestones that represent player-facing capability.

## Current State (as of 2026-04-03)

The Rules Engine (`core/`) is significantly further along than the rest of the system. An honest assessment of where each layer stands:

### Rules Engine — ~65% of full SRD coverage

**Complete or near-complete:**

| Module | Status | Coverage |
|---|---|---|
| `core/dice.py` | Complete | All dice notation, advantage/disadvantage, ability score generation |
| `core/conditions.py` | Complete | All 14 SRD conditions, Exhaustion (6 levels), condition interactions (Paralyzed→Incapacitated, etc.), speed effects, attack/save/check modifiers, `can_act()`, `concentration_is_broken()` |
| `core/combat.py` | ~90% | Attack resolution (melee/ranged/spell), cover, resistance/vulnerability/immunity, critical hits, two-weapon fighting, temp HP, instant death, Death Saving Throws, initiative, grapple, shove, opportunity attack triggers, concentration saves |
| `core/characters.py` | ~85% | Ability scores (all methods), proficiency bonus, HP (L1 + level-up), spell slots (all progressions incl. multiclass), cantrips known, spells prepared, class features (all 20 levels), class proficiencies, multiclass prerequisites + proficiency gains, starting equipment, species traits, background data, feat data, XP-to-level |

**Not yet implemented in the engine:**

| Feature | Milestone | Complexity | Notes |
|---|---|---|---|
| Spell resolution flow | M1 | Medium | Individual components exist (spell attack rolls, spell save DCs via combat.py), but no `resolve_spell()` that consumes a slot, checks range, applies effects, and returns a result for the narrator |
| Character creation orchestrator | M1 | Medium | All validation functions exist, but no `create_character()` that sequences the full 10-step flow and produces a Character record |
| Concentration state machine | M2 | Low | `concentration_save_dc()` and `roll_concentration_save()` exist; missing: tracking which spell is concentrated on, auto-breaking on new concentration spell, integration with condition engine |
| Upcasting | M2 | Low | Schema field needed; engine applies scaled effect from spell data |
| Reaction spells (Shield, Counterspell) | M2 | Medium | Requires integration with ADR-0009 reaction window |
| Area of Effect geometry | M2 | High | Target resolution for sphere, cone, cube, line, cylinder — the most complex remaining engine feature |
| Ritual casting | M2 | Low | Flag check + bypass slot consumption |
| Spell component enforcement | M2 | Low | V/S/M checks against character state |
| Monster abilities | M2 | Medium | Multiattack, breath weapons (recharge), legendary actions, lair actions |
| Rest mechanics (full) | M2 | Low | Long/short rest as flows that reset HP, slots, features, hit dice |
| Wildshape | M3 | High | Full stat block replacement with carry-over rules |
| Encounter building | M3 | Low | CR/XP budget calculator — primarily a tool for Claude |
| Mounted/underwater combat | M3 | Medium | Situational rule overlays |

### SRD Data — Not yet imported

The `scripts/schemas/` directory and `scripts/srd_import/` pipeline exist as architecture (ADR-0001) but no SRD data has been extracted, validated, or seeded into the database. The Rules Engine currently uses hardcoded reference data (class tables, proficiency bonuses, etc.) embedded in the Python code.

This is the single largest gap. The engine can resolve an attack — but there are no spell definitions to cast, no monster stat blocks to fight, and no equipment definitions beyond what is hardcoded for character creation.

### DM Layer — Structure exists, not yet functional

`dm/context_builder.py` and `dm/narrator.py` exist as files. The architecture is defined in ADR-0002. The actual implementation — snapshot assembly, model routing, rolling summary compression, system prompt — is not yet built.

### Turn Lifecycle — API surface exists, game loop does not

The API has endpoints for campaigns, characters, turns, and WebSocket connections. The gameplay loop — player action → engine analysis → (optional rolls) → narrative response → state persistence — is not yet wired together.

---

## Milestones

The old phase structure assumed sequential engine development. The engine is mostly built. The new structure reflects the actual critical path: integration, data, and the DM layer.

### Milestone 1: First Playable — "A solo character can have an adventure"

**Player experience**: Create a character, start a campaign, explore narratively, fight simple enemies, take and deal damage, cast basic spells, level up, save and resume.

**What makes this the minimum**: A player can sit down, `docker compose up`, and play. The mechanics are correct for the situations that arise. Claude narrates. The experience is recognizably D&D.

**Level cap**: 5 (Extra Attack, Level 3 spells, subclass at 3, first ASI at 4).

**Roll mode**: `automatic` only (ADR-0009 interactive rolling deferred to M2).

#### Workstream A: SRD Data Import — Phase 1 Batch

Schemas must be defined and data imported for:

| Block | Scope | Est. Records | Schema File(s) | Priority |
|---|---|---|---|---|
| `rules_tables` | Proficiency bonus, XP thresholds (L1-20), spell slot tables (all classes, all levels), ability score point buy costs, starting wealth | ~10 tables | `rules_table.json` | P0 — no deps |
| `conditions` | All 14 conditions — mechanical effect definitions (engine already implements them; this is the data layer for narrator context) | 14 | `condition.json` | P0 — no deps |
| `species` | All SRD species + subspecies: Human, Elf (High/Wood), Dwarf (Hill/Mountain), Halfling (Lightfoot/Stout), Dragonborn, Gnome (Forest/Rock), Half-Elf, Half-Orc, Tiefling | ~15 | `species.json` | P1 |
| `backgrounds` | All SRD backgrounds with ability bonuses, proficiencies, Origin feat references | ~16 | `background.json` | P1 |
| `equipment` | Simple + martial weapons, light/medium/heavy armor, shields, adventuring packs, starting equipment packages | ~80 | `weapon.json`, `armor.json`, `equipment.json` | P1 |
| `feats` | Origin feats (background-selectable) | ~12 | `feat.json` | P1 |
| `classes` | All 12 classes, Levels 1-5: class table, hit dice, proficiencies, features. One subclass per class at Level 3 | 12 classes, ~60 features | `class.json`, `class_feature.json`, `subclass.json` | P2 |
| `spells` | Cantrips + Level 1-3 spells for all classes | ~120 spells | `spell.json` | P2 |
| `monsters` | Starter set: CR 0-3. Goblin, Skeleton, Zombie, Wolf, Giant Rat, Bandit, Kobold, Orc, Ogre, Owlbear, Giant Spider, Bugbear, Gnoll, Gelatinous Cube, Mimic | ~30 | `monster.json`, `monster_action.json`, `monster_trait.json` | P3 |

**Import order** (topological): `rules_tables` → `conditions` → `species` → `equipment` → `backgrounds` → `feats` → `classes` → `spells` → `monsters`.

**Critical schema design rule**: All schemas include fields for mechanics not yet enforced by the engine. A spell schema has `requires_concentration`, `ritual`, `components`, `area_of_effect` from day one. The data is correct at import time; the engine catches up in M2. This prevents re-importing when the engine adds features.

**Migration from hardcoded data**: The engine currently embeds class tables, proficiency bonuses, spell slot tables, and species/background data directly in Python. Once the database is seeded, the engine must be refactored to read from the database instead. This is a separate task per data block — not a big-bang migration. The hardcoded data serves as the validation baseline: imported data must match the hardcoded values exactly, or the discrepancy is an extraction error.

#### Workstream B: Engine Completion — M1 Features

Two new orchestration functions that compose existing primitives:

**B1. `create_character()` orchestrator**

Sequences the full character creation flow:
1. Validate ability scores (method-dependent)
2. Apply species traits
3. Apply class at Level 1 (HP, proficiencies, features, spell slots)
4. Apply background (ability bonuses, skills, tools, Origin feat)
5. Assign starting equipment
6. Initialize spellcasting (if applicable)
7. Produce a complete Character record (per ADR-0004 data model)

All validation functions exist. This is assembly, not new mechanics.

**B2. `resolve_spell()` flow**

Takes a spell definition + caster state + target(s) and produces a mechanical result:
1. Check spell slot availability and consume slot (or cantrip: skip)
2. Determine hit/save: spell attack roll (reuse `combat.resolve_attack()`) or saving throw
3. Calculate damage or healing from spell data
4. Apply conditions specified in spell effects
5. Return a structured result for the Context Builder

This reuses `combat.py` for attack/damage and `conditions.py` for effect application. The new code is the glue.

**B3. Rest mechanics**

Two functions: `apply_short_rest()` and `apply_long_rest()` that take a character state and return the updated state. Long rest: full HP, all spell slots, reset death saves. Short rest: spend hit dice to heal. Both exist conceptually in `characters.py` but are not yet assembled as state transitions.

#### Workstream C: DM Layer

**C1. System prompt** (`dm/prompts/`)

The static prompt that defines Claude's DM persona, output format constraints, and narrative rules. Per ADR-0002, this is ~800 tokens, fully cacheable. Includes campaign tone, world rules, and behavioral constraints (no blocking player actions, no inventing mechanical outcomes, etc.).

**C2. Context Builder** (`dm/context_builder.py`)

Assembles the state snapshot from:
- Character snapshot (from Character model): name, class, level, HP, conditions, key inventory, spell slots remaining
- Scene context (from CampaignState): location, NPCs present, environmental conditions, time of day
- Rolling summary (from CampaignState): compressed narrative of recent turns
- Current turn: player's action (verbatim) + Rules Engine result (human-readable)

Enforces token budgets per ADR-0002 (~2,400 tokens total, ~50% cacheable).

**C3. Narrator** (`dm/narrator.py`)

The Claude API integration:
- Sends assembled snapshot to Claude
- Handles streaming response
- Model routing: Sonnet for narrative, Haiku for acknowledgments and summary compression (per ADR-0002 §4)
- Error handling: retry logic, fallback on API failure

**C4. Rolling Summary** (`dm/summary.py`)

After each turn, compress the turn's events into the rolling summary. Haiku task. Maintains a fixed token budget (~500 tokens). Drops oldest entries when budget is exceeded.

#### Workstream D: Turn Lifecycle

**D1. Game loop integration** (`api/turns.py` + `api/ws.py`)

Wire the full turn cycle:
```
Player submits action (REST or WebSocket)
  → Engine analyzes action (what kind of check/attack/spell?)
  → Engine resolves mechanics (auto-roll in M1)
  → Context Builder assembles snapshot with engine result
  → Narrator generates narrative response (streamed via WebSocket)
  → State persisted (Turn record, updated Character, updated CampaignState)
  → Rolling summary updated
  → Client receives narrative + updated character state
```

**D2. Session management**

Start session (create Session record, load CampaignState), end session (persist final state, update `last_played_at`), resume session (reconstruct state from CampaignState + Characters).

**D3. Campaign creation flow**

Player provides startup parameters (tone, length, optional setting/focus/difficulty) → Claude generates Campaign Brief → stored as `world_seed` → first scene narrated.

#### M1 Definition of Done

- [ ] All P0-P3 SRD data imported and validated
- [ ] `create_character()` produces valid Level 1 characters for all 12 classes
- [ ] `resolve_spell()` handles cantrips and Level 1-3 spells (damage, healing, conditions)
- [ ] System prompt, Context Builder, Narrator, and Rolling Summary functional
- [ ] Turn lifecycle: action → engine → narrator → persistence → client
- [ ] Session start/end/resume works
- [ ] Campaign creation with Claude-generated brief works
- [ ] Level-up to Level 5 works (HP, features, subclass at 3, ASI at 4)
- [ ] At least one client (Discord bot or web) can play through the full loop
- [ ] `docker compose up` → playable within 5 minutes

---

### Milestone 2: Tactical Depth — "Experienced players recognize the game"

**Player experience**: Full combat tactical depth. Interactive dice rolling. Concentration matters. Counterspell creates drama. AoE spells hit the right targets. Level 1-20 progression. Multiplayer with real-time turn coordination. Magic items.

**What this adds over M1**: Everything that makes D&D tactically interesting rather than just narratively interesting.

#### Workstream A: SRD Data Import — Full Catalog

| Block | Scope | Est. Records |
|---|---|---|
| `classes` | Full Level 1-20 progression, all features, all 12 subclasses | ~200 features, ~48 subclass features |
| `spells` | All remaining SRD spells (Levels 4-9 + any L1-3 not in M1) | ~280 spells |
| `monsters` | Full SRD bestiary with complete stat blocks | ~300 monsters |
| `feats` | All non-Origin SRD feats | ~30 feats |
| `magic_items` | SRD magic items: armor, weapons, potions, rings, wondrous items | ~50-80 items |
| `rules_tables` | Full L1-20 tables, multiclass spell slot table, CR/XP table | remaining tables |

#### Workstream B: Engine Completion — M2 Features

| Feature | Complexity | Dependencies |
|---|---|---|
| Concentration state machine | Low | `combat.py` (save exists), `conditions.py` (broken check exists) — needs tracking of active concentration spell and auto-break on new cast |
| Upcasting | Low | Spell schema `higher_levels` field + slot consumption at higher level |
| Ritual casting | Low | Schema flag + bypass slot consumption |
| Spell component enforcement | Low | V/S/M checks against character conditions (Silenced→no V, no free hand→no S) and inventory (material components) |
| Reaction spells | Medium | Integrates with ADR-0009 reaction window — Shield, Counterspell, Absorb Elements, Hellish Rebuke as spell resolutions triggered during reaction phase |
| Area of Effect geometry | High | Sphere, cone, cube, line, cylinder — given origin point and dimensions, determine which grid positions (and therefore which creatures) are affected. This is the most complex remaining engine feature |
| Monster abilities | Medium | Multiattack (sequence of attacks per stat block), breath weapons (recharge on 5-6 each round), legendary actions (pool per round, end-of-other-turns), lair actions (initiative 20), innate spellcasting (per-day spell uses without slots) |
| Interactive dice rolling (ADR-0009) | High | Player-triggered rolls, pre-roll options, self-reaction window, cross-player reaction window with timer, NPC reaction decisions via Claude, all three roll modes |
| Authentication (ADR-0006) | Medium | Anonymous, Local, Discord OAuth providers — required for multiplayer identity |
| Multiplayer turn coordination (ADR-0007) | High | Initiative-ordered turns, real-time state sync, concurrent player connections, conflict resolution |

#### Workstream C: DM Layer Enhancements

- Model routing refinement: classify response types (narrative, acknowledgment, summary, NPC reaction decision) and route to Sonnet/Haiku
- Prompt caching: leverage Anthropic API cache for static system prompt and character snapshot
- NPC reaction decisions: tightly-scoped prompts for combat reactions (Counterspell yes/no, Legendary Resistance yes/no) with 3-second timeout

#### M2 Definition of Done

- [ ] Full SRD bestiary imported
- [ ] All SRD spells imported (Levels 0-9)
- [ ] Concentration tracking enforced
- [ ] AoE spells resolve targets from geometry
- [ ] Reaction spells work in combat (Shield, Counterspell)
- [ ] Interactive dice rolling functional in at least one roll mode
- [ ] Level 1-20 progression complete (all features, all subclasses)
- [ ] Magic items with attunement
- [ ] Multiplayer: 2-5 players in real-time with turn coordination
- [ ] Authentication: at least Anonymous + Local providers

---

### Milestone 3: Complete — "Every SRD rule is implemented"

**Player experience**: A rules lawyer cannot find a missing SRD 5.2.1 mechanic. Every rule has a corresponding engine implementation or a documented, explicit decision to handle it narratively.

#### Remaining Engine Features

| Feature | Complexity |
|---|---|
| Wildshape (full stat block replacement) | High |
| Mounted combat | Medium |
| Underwater combat | Medium |
| Falling damage | Low |
| Suffocation | Low |
| Vision and light (bright/dim/darkness) | Medium |
| Encounter building (CR/XP budget calculator) | Low |
| Trap mechanics (DCs, damage tables) | Low |
| Disease and poison subsystems | Low |
| Crafting rules | Low |
| Downtime activities | Low |
| Hirelings and followers | Low |
| Multiclass edge cases (3+ class spell slots, feature stacking) | Medium |
| Vehicle rules | Low |

#### Remaining SRD Data

| Block | Scope | Est. Records |
|---|---|---|
| `monsters` | Any remaining monsters not in M2 | ~50 |
| `magic_items` | Complete catalog | remaining items |
| `rules_tables` | Trap DCs, disease tables, lifestyle costs, crafting costs | ~15 tables |
| `equipment` | Vehicles, siege equipment, detailed mount stats | ~30 |

#### M3 Definition of Done

- [ ] Every mechanical rule in the SRD 5.2.1 has either an engine implementation or an explicit exclusion with rationale
- [ ] All SRD data imported with no known extraction errors
- [ ] Test coverage for `core/` exceeds 90% of public functions
- [ ] A complete playthrough from Level 1-20 has been tested against expected mechanical outcomes

---

## SRD Document Segmentation

The SRD 5.2.1 PDF (~361 pages) is segmented into import blocks. Each block gets its own JSON Schema in `scripts/schemas/`.

| Block ID | SRD Section | Content | Approx. Pages | Schema File(s) |
|---|---|---|---|---|
| `species` | Chapter 2 | Species/subspecies traits, sizes, speeds, special abilities | ~15 | `species.json` |
| `classes` | Chapter 3 | Class tables, hit dice, proficiencies, features by level, subclasses | ~80 | `class.json`, `class_feature.json`, `subclass.json` |
| `backgrounds` | Chapter 4 | Background ability bonuses, skill/tool proficiencies, Origin feats | ~10 | `background.json` |
| `feats` | Chapter 5 | Feat prerequisites, effects, choices | ~15 | `feat.json` |
| `equipment` | Chapter 6 | Weapons, armor, adventuring gear, tools, mounts, trade goods | ~20 | `weapon.json`, `armor.json`, `equipment.json` |
| `spells` | Chapter 7 | Spell definitions — all levels, all classes | ~100 | `spell.json` |
| `monsters` | Appendix | Monster stat blocks, actions, traits, legendary actions, CR | ~80 | `monster.json`, `monster_action.json`, `monster_trait.json` |
| `conditions` | Rules Glossary | Condition definitions and mechanical effects | ~5 | `condition.json` |
| `magic_items` | Chapter 8 | Magic item properties, attunement, rarity | ~20 | `magic_item.json` |
| `rules_tables` | Various | XP, proficiency, spell slots, multiclass, starting wealth | ~5 | `rules_table.json` |

### Import Pipeline Workflow

Per ADR-0001, each block follows:

```
1. Define schema          →  scripts/schemas/{block}.json
2. Segment SRD PDF        →  scripts/srd_import/extract.py --section {block}
3. Claude extraction      →  scripts/srd_import/claude_parse.py --schema {block}
4. Schema validation      →  scripts/srd_import/validate.py
5. Baseline comparison    →  Compare against hardcoded engine data (where exists)
6. Human review           →  Reviewer checks against SRD source
7. Database seed          →  Alembic migration or management command
8. Engine refactor        →  Replace hardcoded data with DB reads
9. Integration test       →  Verify engine produces identical results with DB data
```

### Batch Sizing for Claude Extraction

- **Spells**: by level (cantrips, then L1, then L2, ...) — ~10-20 per batch
- **Monsters**: by CR range (CR 0-1, 2-3, 4-6, 7-10, 11-15, 16-20, 21+) — ~20-40 per batch
- **Classes**: one class per batch — ~5-8 pages each
- **Equipment**: weapons in one batch, armor in one batch, gear in one batch
- **Everything else**: single batch per block

### Validation Beyond Schema

- **Cross-reference integrity**: spell referencing "Poisoned" condition → condition must exist
- **Numerical plausibility**: CR 1 monster with 300 HP → likely extraction error
- **Completeness**: all 12 classes must have features at every level
- **Duplicate detection**: two spells with same name but different stats → extraction error
- **Baseline match**: imported proficiency bonus table must match `characters.proficiency_bonus()` output for all 20 levels

---

## Cross-Cutting Concerns

### Hardcoded-to-Database Migration

The engine currently embeds substantial SRD data directly in Python (class tables, spell slot progressions, species traits, background data, feat data, equipment). This was the right bootstrapping strategy — it let the engine be developed and tested without waiting for the import pipeline.

The migration happens per block:
1. Import block into database via pipeline
2. Verify imported data matches hardcoded data exactly
3. Refactor engine functions to query database instead of internal dicts
4. Remove hardcoded data
5. Verify all tests still pass with database-backed data

This is incremental. Each block migrates independently. At no point is the engine in a broken state.

### Test Strategy

Engine tests currently use the hardcoded data. After migration:
- Unit tests use a test database seeded with known fixture data
- The fixture data is a subset of the full import — enough for test coverage, small enough for fast CI
- Full-data integration tests run nightly, not on every PR

### Claude as DM for Unimplemented Mechanics

Between milestones, some mechanics will be specced but not yet implemented. The DM layer handles this gracefully:

- The system prompt tells Claude which mechanics the engine handles and which it should adjudicate narratively
- Example: In M1, AoE spells have no geometry engine. Claude decides who is hit based on the scene description. In M2, the engine calculates it
- This is the "hybrid approach" from ADR-0001 Alternatives, applied as a transitional strategy rather than a permanent architecture

The key constraint: Claude's narrative adjudication must never contradict an engine result. If the engine says "attack hits, 8 damage," Claude narrates the hit — it does not decide the attack missed. Claude only adjudicates mechanics the engine does not cover.

---

## Review Triggers

- If M1 takes longer than 6 weeks of active development, evaluate whether the SRD data import should use a third-party database (e.g., 5e-database on GitHub) as seed data instead of Claude extraction from PDF.
- If Claude extraction accuracy falls below 90% for any block (measured by human review rejection rate), switch that block to manual transcription or third-party data.
- If the hardcoded-to-database migration reveals discrepancies between engine behavior and SRD rules, file these as bugs — the engine's hardcoded data may itself contain errors that were never caught because no external validation existed.
- If AoE geometry implementation in M2 exceeds 3 sessions of effort, evaluate a simplified model (discrete zones instead of continuous geometry) as an intermediate step.
- If the turn lifecycle latency (action → narrative response) exceeds 8 seconds excluding Claude API time, profile and optimize the engine/context builder path before adding more features.