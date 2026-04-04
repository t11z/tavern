# SRD Implementation Roadmap

- **Status**: Accepted
- **Date**: 2026-04-04
- **Author**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/core/` (Rules Engine), `backend/tavern/dm/` (DM Layer), `backend/tavern/api/` (Turn Lifecycle), `frontend/` (Web Client), `backend/tavern/discord_bot/` (Discord Bot)
- **References**: ADR-0001 (SRD Rules Engine), ADR-0002 (Claude as Narrator), ADR-0004 (Campaign and Session Lifecycle), ADR-0005 (Client Architecture), ADR-0007 (Multiplayer), ADR-0009 (Interactive Dice Rolling)

## Purpose

This document defines the implementation plan for making Tavern playable and progressively complete. It tracks the critical path from the current codebase to a working game — first for a solo player, then for a group.

## Current State (as of 2026-04-04)

### Rules Engine — ~65% of full SRD coverage

| Module | Status | Coverage |
|---|---|---|
| `core/dice.py` | Complete | All dice notation, advantage/disadvantage, ability score generation |
| `core/conditions.py` | Complete | All 14 SRD conditions, Exhaustion (6 levels), condition interactions, speed effects, attack/save/check modifiers, `can_act()`, `concentration_is_broken()` |
| `core/combat.py` | ~90% | Attack resolution (melee/ranged/spell), cover, resistance/vulnerability/immunity, critical hits, two-weapon fighting, temp HP, instant death, Death Saving Throws, initiative, grapple, shove, opportunity attack triggers, concentration saves |
| `core/characters.py` | ~85% | Ability scores (all methods), proficiency bonus, HP (L1 + level-up), spell slots (all progressions incl. multiclass), cantrips known, spells prepared, class features (all 20 levels), class proficiencies, multiclass prerequisites, starting equipment, species traits, background data, feat data, XP-to-level |
| `core/srd_data.py` | Functional | Three-tier lookup (Campaign Override → Instance Library → SRD Baseline) against MongoDB |

### SRD Data — Available, not yet consumed

The 5e-database MongoDB container is running and populated. The SRD Data Access Layer (`core/srd_data.py`) exists and implements three-tier resolution. The engine modules (`characters.py`, `combat.py`) still read from hardcoded Python dicts, not from MongoDB.

### DM Layer — Structure exists, not yet functional

`dm/narrator.py` and `dm/context_builder.py` exist as files. Model routing (Sonnet/Haiku) is implemented in the Narrator. The actual integration — snapshot assembly from live game state, system prompt, rolling summary compression — is not yet wired to produce working narration.

### Turn Lifecycle — API surface exists, game loop does not

REST endpoints for campaigns, characters, turns, and sessions exist. The WebSocket handler (`api/ws.py`) with `ConnectionManager` exists. The gameplay loop — player action → engine → narrator → persistence → client — is not yet connected end-to-end.

### Web Client — Skeleton exists

React/Vite app with TypeScript types, WebSocket hook, campaign header, character panel, chat log, and chat input components. Not yet functional as a game interface.

### Discord Bot — Cog structure exists

`discord.py` bot with WebSocket cog that handles session state, narrative streaming, and is pre-wired for reaction window events. Gameplay cog exists but the actual command handlers need the turn lifecycle to be functional on the server side.

---

## What Separates Us From a Playable Game

Five systems must work together before a player can sit down and play:

1. **Engine reads SRD data from MongoDB** instead of hardcoded Python (migration)
2. **`create_character()` and `resolve_spell()`** orchestrators that compose existing engine primitives
3. **DM Layer** (Context Builder + Narrator + Rolling Summary) produces actual narration from Claude
4. **Turn lifecycle** wires the full loop: action → engine → narrator → persistence → broadcast
5. **At least one client** renders the game and accepts player input

Items 1–4 are shared infrastructure. Item 5 diverges into two parallel client tracks.

---

## Milestones

### Milestone 1: First Playable — "A solo character can have an adventure"

**Player experience**: Create a character, start a campaign, explore narratively, fight simple enemies, take and deal damage, cast basic spells, level up, save and resume.

**What makes this the minimum**: A player can `docker compose up` and play. The mechanics are correct for the situations that arise. Claude narrates. The experience is recognizably D&D.

**Level cap**: 5 (Extra Attack, Level 3 spells, subclass at 3, first ASI at 4).

**Roll mode**: `automatic` only (ADR-0009 interactive rolling deferred to M2).

#### Workstream A: Engine Hardcoded-to-MongoDB Migration

The engine currently embeds SRD reference data in Python dicts. Each module must be refactored to query `core/srd_data.py` instead. The hardcoded data becomes the test fixture baseline — imported MongoDB data must produce identical results.

| Module | Data to migrate | Validation approach |
|---|---|---|
| `characters.py` | Class tables, spell slot progressions, species traits, background data, feat data, proficiency bonus table, starting equipment | Compare `srd_data.get_class()` output against hardcoded class dicts for all 12 classes at all 20 levels |
| `combat.py` | Weapon properties (finesse, heavy, light, etc.) | Compare weapon lookups against hardcoded weapon data |
| `conditions.py` | None — conditions are fully engine-implemented, not data-driven | N/A (condition definitions in 5e-database serve narrator context, not engine logic) |

**Scope constraint**: Only migrate data that the engine currently reads. Do not refactor modules to consume *new* data types from MongoDB in this workstream — that is engine feature work (Workstream B).

**Migration order**: `characters.py` first (most hardcoded data, most user-facing impact), then `combat.py`.

#### Workstream B: Engine Completion — M1 Features

Three orchestrator functions that compose existing primitives:

**B1. `create_character()` orchestrator**

Sequences the full character creation flow: validate ability scores → apply species traits (from MongoDB) → apply class at Level 1 → apply background → assign starting equipment → initialize spellcasting → produce a complete Character record per ADR-0004.

All validation functions exist in `characters.py`. This is assembly, not new mechanics.

**B2. `resolve_spell()` flow**

Takes a spell definition (from MongoDB) + caster state + target(s) and produces a mechanical result: check spell slot availability → determine hit/save → calculate damage or healing → apply conditions → return structured result for the Context Builder.

This reuses `combat.py` for attack/damage and `conditions.py` for effect application. The new code is the integration glue.

**B3. Rest mechanics**

`apply_short_rest()` and `apply_long_rest()` as state transitions. Long rest: full HP, all spell slots, reset death saves. Short rest: spend hit dice to heal. Conceptually present in `characters.py` but not yet assembled.

#### Workstream C: DM Layer

**C1. System prompt** (`dm/prompts/`)

The static prompt defining Claude's Game Master persona, output format constraints, and narrative rules. Per ADR-0002: ~800 tokens, fully cacheable. Includes campaign tone from `world_seed`, behavioral constraints (no blocking player actions, no inventing mechanical outcomes), and a dynamic section listing which mechanics the engine handles vs. which Claude adjudicates narratively.

**C2. Context Builder** (`dm/context_builder.py`)

Assembles the state snapshot from: Character snapshot (from Character model) + Scene context (from CampaignState) + Rolling summary + Current turn (player action + engine result). Enforces token budgets per ADR-0002 (~2,400 tokens total, ~50% cacheable).

**C3. Narrator integration** (`dm/narrator.py`)

Wire the existing Narrator class to actually call the Claude API with assembled snapshots. Streaming response handling. Model routing: Sonnet for narrative, Haiku for acknowledgments and summary compression.

**C4. Rolling Summary** (`dm/summary.py`)

After each turn, compress the turn's events into the rolling summary via Haiku. Fixed token budget (~500 tokens). Drop oldest entries when budget exceeded.

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

#### Workstream E: Client — Web (React)

Per ADR-0005, the web client is a client-side SPA consuming the headless API. M1 scope:

**E1. Campaign management UI**

Create campaign (with startup parameter form), list campaigns, resume campaign. REST calls to existing endpoints.

**E2. Character creation flow**

Guided character creation through the web UI. Calls `create_character()` via REST. Renders class/species/background selection, ability score assignment, equipment choices.

**E3. Game session UI**

The core play interface: chat log showing narrative + mechanical results, action input, character sheet sidebar (HP, conditions, spell slots, inventory). WebSocket connection for streaming narrative.

**E4. Session lifecycle controls**

Start session, end session, resume session buttons. Session state indicator.

#### Workstream F: Client — Discord Bot

Per ADR-0005, the Discord bot is a first-class client. It consumes the same API as the web client. M1 scope:

**F1. Campaign slash commands**

`/tavern create`, `/tavern launch`, `/tavern stop`, `/tavern resume`, `/tavern end`, `/tavern status`. Bot-managed channel creation (category + text + voice). Permission scoping.

**F2. Character creation in threads**

`/character create` opens a thread per player. Claude walks each player through creation via a guided conversation (Path 1 from discord-bot.md). Character sheet embeds on completion.

**F3. Gameplay loop**

Message interception in bound channels (game mode). `/action` command. Turn submission via REST. Narrative response posting from WebSocket events. Mechanical results as embeds. OOC filtering via configurable prefix.

**F4. LFG and group formation**

`/lfg` command with join buttons. Player gathering before campaign launch. Embed updates as players join.

#### M1 Definition of Done

- [ ] Engine reads all SRD reference data from MongoDB via `srd_data.py` — no hardcoded Python dicts remain for class tables, spell slots, species, backgrounds, equipment
- [ ] `create_character()` produces valid Level 1 characters for all 12 SRD classes
- [ ] `resolve_spell()` handles cantrips and Level 1–3 spells (damage, healing, conditions)
- [ ] Rest mechanics (`apply_short_rest()`, `apply_long_rest()`) function as state transitions
- [ ] System prompt, Context Builder, Narrator, and Rolling Summary produce coherent Claude narration
- [ ] Turn lifecycle: action → engine → narrator → persistence → client works end-to-end
- [ ] Session start/end/resume works
- [ ] Campaign creation with Claude-generated brief works
- [ ] Level-up to Level 5 works (HP, features, subclass at 3, ASI at 4)
- [ ] **Web client**: campaign creation → character creation → gameplay → session resume — all functional
- [ ] **Discord bot**: `/tavern create` → `/character create` → gameplay in channel → `/tavern stop` and resume — all functional
- [ ] `docker compose up` → playable within 5 minutes on either client

**Workstream dependency graph:**

```
A (MongoDB migration) ──→ B (Engine orchestrators) ──→ D (Turn lifecycle)
                                                          ↑
                          C (DM Layer) ───────────────────┘
                                                          │
                          E (Web Client) ←────────────────┤
                          F (Discord Bot) ←───────────────┘
```

A and C are independent of each other and can run in parallel. B depends on A. D depends on B and C. E and F depend on D but can begin UI scaffolding in parallel.

---

### Milestone 2: Tactical Depth — "Experienced players recognize the game"

**Player experience**: Full combat tactical depth. Interactive dice rolling. Concentration matters. Counterspell creates drama. AoE spells hit the right targets. Level 1–20 progression. Multiplayer with real-time turn coordination. Magic items.

**What this adds over M1**: Everything that makes D&D tactically interesting rather than just narratively interesting.

#### Engine Features

| Feature | Complexity | Notes |
|---|---|---|
| Interactive dice rolling (ADR-0009) | High | Player-triggered rolls, pre-roll options, self-reaction window, cross-player reaction window with timer, NPC reaction decisions via Claude |
| Concentration state machine | Low | Track concentrated spell, auto-break on new concentration, integrate with condition engine |
| Reaction spells (Shield, Counterspell) | Medium | Requires ADR-0009 reaction window system |
| AoE geometry | High | Target resolution for sphere, cone, cube, line, cylinder — the most complex remaining engine feature |
| Upcasting | Low | Apply scaled effect from spell data in MongoDB |
| Ritual casting | Low | Flag check + bypass slot consumption |
| Spell component enforcement | Low | V/S/M checks against character state |
| Monster abilities | Medium | Multiattack, breath weapons (recharge 5–6), legendary actions, lair actions, innate spellcasting |
| Level 6–20 progression | Medium | All class features, all subclass features, additional ASIs |
| Magic items with attunement | Medium | Attunement slots, item properties from MongoDB |
| Rest mechanics (full) | Low | Hit dice tracking, per-rest feature resets, class-specific rest features |

#### Multiplayer (ADR-0007)

| Feature | Complexity | Notes |
|---|---|---|
| Authentication (ADR-0006) | Medium | Anonymous, Local, Discord OAuth providers — required for multiplayer identity |
| Initiative-ordered combat turns | Medium | Turn prompts, timeout with Dodge default, NPC turns via Claude |
| Exploration mode (FIFO) | Low | Sequential processing of concurrent player actions |
| Real-time state sync | Medium | WebSocket broadcast of all state changes to all connected clients |
| Player presence | Low | Join/leave notifications, disconnect handling |

#### Web Client — M2 Features

| Feature | Notes |
|---|---|
| Interactive dice rolling UI | Roll button, pre-roll option checkboxes, reaction window with countdown timer |
| Multiplayer lobby | Campaign join flow, player list, initiative tracker |
| Authentication | Login/register, Discord OAuth, anonymous mode |
| Character sheet (expanded) | Level-up flow, spell management, inventory management |
| Shared display mode | Party overview, narration display, battle status — read-only, optimized for TV/laptop at table |

#### Discord Bot — M2 Features

| Feature | Notes |
|---|---|
| Interactive dice rolling | 🎲 button on roll prompts, pre-roll option buttons, reaction window embeds with countdown |
| Multiplayer turn coordination | Turn prompt embeds, initiative order display, timeout handling |
| Authentication binding | Discord OAuth identity → Tavern character mapping |
| `/tavern invite` / `/tavern kick` | Mid-campaign player management |
| Configurable rolling mode | `/tavern config rolling_mode interactive\|automatic\|hybrid` |

#### M2 Definition of Done

- [ ] Full SRD spell catalog (Levels 0–9) accessible from MongoDB and resolvable by engine
- [ ] Concentration tracking enforced across turns
- [ ] AoE spells resolve targets (geometry or simplified zone model — see review triggers)
- [ ] Reaction spells (Shield, Counterspell, Silvery Barbs) functional with reaction windows
- [ ] Interactive dice rolling functional in all three roll modes on both clients
- [ ] Level 1–20 progression complete for all 12 SRD classes and their SRD subclasses
- [ ] Magic items with attunement
- [ ] Monster abilities: multiattack, breath weapons, legendary actions
- [ ] Multiplayer: 2–5 players in real-time with initiative-based turn coordination
- [ ] Authentication: at least Anonymous + Discord OAuth providers
- [ ] Both clients support the full M2 feature set

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

#### Client Features

| Feature | Web | Discord |
|---|---|---|
| Voice input (STT) | Browser Web Speech API or Whisper | discord.py voice receive + STT provider (ADR-0008) |
| Voice output (TTS) | Browser SpeechSynthesis or ElevenLabs | TTS provider → Discord voice channel (ADR-0008) |
| Streaming narrative | Progressive text display (already in M1) | Progressive message editing (deferred from Discord V1) |
| Battle map / scene visualization | Canvas-based token display (future) | Text-based scene descriptions |

#### M3 Definition of Done

- [ ] Every mechanical rule in the SRD 5.2.1 has either an engine implementation or an explicit exclusion with rationale
- [ ] Test coverage for `core/` exceeds 90% of public functions
- [ ] Voice pipeline functional on both clients (STT + TTS)
- [ ] A complete playthrough from Level 1–20 has been tested against expected mechanical outcomes

---

## Cross-Cutting Concerns

### Claude as Game Master for Unimplemented Mechanics

Between milestones, some mechanics will be specced in the SRD but not yet implemented in the engine. The DM layer handles this gracefully:

- The system prompt tells Claude which mechanics the engine handles and which it should adjudicate narratively
- Example: In M1, AoE spells have no geometry engine. Claude decides who is hit based on the scene description. In M2, the engine calculates it
- This is the hybrid approach from ADR-0001 Alternatives, applied as a transitional strategy — not a permanent architecture

**Hard constraint**: Claude's narrative adjudication must never contradict an engine result. If the engine says "attack hits, 8 damage," Claude narrates the hit. Claude only adjudicates mechanics the engine does not cover.

### Hardcoded-to-MongoDB Migration Strategy

The engine currently embeds SRD data directly in Python. The migration happens per module:

1. Identify hardcoded data in the module
2. Write a thin adapter function in `srd_data.py` that queries the equivalent MongoDB collection
3. Verify imported data matches hardcoded data exactly — discrepancies are bugs (either in the hardcoded data or in 5e-database)
4. Refactor engine functions to call `srd_data` instead of internal dicts
5. Move hardcoded data to `tests/fixtures/` as test baselines
6. Verify all existing tests pass with MongoDB-backed data

This is incremental. Each module migrates independently. At no point is the engine in a broken state.

### Test Strategy

Engine tests currently use hardcoded data (moved to `tests/fixtures/srd_fixtures.py`). After migration:

- Unit tests use a test MongoDB instance seeded from 5e-database
- The fixture data serves as the expected-value baseline: if MongoDB returns different data, the test fails and the discrepancy must be investigated
- Full integration tests (engine + MongoDB + DM layer) run in CI on every PR

### Client Parity Principle

Per ADR-0005, both clients are first-class. Neither client gets a feature the API doesn't support. The API is the bottleneck — once the API supports a feature, both clients can implement it independently.

In practice, this means: don't wait for both clients to be ready before shipping server-side features. The first client to implement a feature becomes the testbed. The second client follows.

---

## Review Triggers

- If the 5e-database data for any collection (spells, monsters, classes) has errors or gaps that affect gameplay, evaluate contributing fixes upstream vs. using Campaign Overrides as a workaround. File upstream issues regardless.
- If the hardcoded-to-MongoDB migration reveals that engine behavior depends on assumptions not present in the 5e-database schema (e.g., the engine expects a field that doesn't exist in the MongoDB documents), this is an engine refactoring task — not a data problem.
- If AoE geometry implementation in M2 exceeds 3 sessions of effort, evaluate a simplified model (discrete zones instead of continuous geometry) as an intermediate step.
- If the turn lifecycle latency (action → narrative response) exceeds 8 seconds excluding Claude API time, profile and optimize the engine/context builder path before adding more features.
- If either client falls more than one milestone behind the other, evaluate whether to pause new server features and focus on client parity.
- If the 5e-bits/5e-database project is abandoned or significantly diverges from SRD 5.2.1, fork the MongoDB image and maintain independently — the dataset is MIT-licensed and the fork is trivial.
- If M1 takes longer than 6 weeks of active development, evaluate whether the scope should be reduced (e.g., fewer classes at launch, delayed level-up, single client only for M1).
