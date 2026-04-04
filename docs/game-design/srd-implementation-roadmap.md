# SRD Implementation Roadmap

- **Status**: Accepted
- **Date**: 2026-04-04
- **Author**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/core/` (Rules Engine), `backend/tavern/dm/` (DM Layer), `backend/tavern/api/` (Turn Lifecycle), `frontend/` (Web Client), `backend/tavern/discord_bot/` (Discord Bot)
- **References**: ADR-0001 (SRD Rules Engine), ADR-0002 (Claude as Narrator), ADR-0004 (Campaign and Session Lifecycle), ADR-0005 (Client Architecture), ADR-0007 (Multiplayer), ADR-0009 (Interactive Dice Rolling)

## Purpose

This document defines the implementation plan for making Tavern playable and progressively complete. It tracks the critical path from the current codebase to a working game — first for a solo player, then for a group.

## Current State (as of 2026-04-04, verified by code audit)

### Rules Engine — ~65% of full SRD coverage, fully backed by MongoDB

| Module | Status | Coverage |
|---|---|---|
| `core/dice.py` | Complete | All dice notation, advantage/disadvantage, ability score generation |
| `core/conditions.py` | Complete | All 15 SRD conditions, Exhaustion (6 levels), condition interactions, speed effects, attack/save/check modifiers, `can_act()`, `concentration_is_broken()` |
| `core/combat.py` | ~90% | Attack resolution (melee/ranged/spell), cover, resistance/vulnerability/immunity, critical hits, two-weapon fighting, temp HP, instant death, Death Saving Throws, initiative, grapple, shove, opportunity attack triggers, concentration saves. No hardcoded SRD data — uses enums for damage types, cover levels, and action types only. |
| `core/characters.py` | ~85%, async | All SRD game data fetched from MongoDB via `srd_data`. Functions: ability scores (all methods), proficiency bonus, HP (L1 + level-up), spell slots (all progressions incl. multiclass), cantrips known, spells prepared, class features (all 20 levels), class proficiencies, multiclass prerequisites, starting equipment, species traits, background data, feat data, XP-to-level. All data-dependent functions are async. |
| `core/srd_data.py` | Complete | Three-tier lookup (Campaign Override → Instance Library → SRD Baseline) with baseline caching. Entity accessors for all collections (classes, levels, races/species, backgrounds, feats, spells, monsters, conditions, equipment, magic-items). Character-mechanics helpers (hit die, proficiency bonus, spell slots, cantrips, features, proficiencies, starting equipment, multiclass). Rules table builders. List/search functions with three-tier merge. |

### SRD Data — Available and consumed

The 5e-database MongoDB container (t11z/5e-database fork, v4.6.3-tavern.1) runs via Docker Compose. See ADR-0010. `core/srd_data.py` provides the complete data access layer. `core/characters.py` reads SRD reference data from MongoDB via srd_data.py. Temporary Python constants in srd_data.py fill gaps where the fork's 2024-* collections are incomplete (see ADR-0010 §7). These constants are marked for removal as the fork's data matures. `core/combat.py` has no hardcoded SRD data (damage types and action types are enums, not data lookups).

### DM Layer — Functional

| Component | Status |
|---|---|
| `dm/context_builder.py` | Complete. `StateSnapshot` and `TurnContext` dataclasses. `build_snapshot()` loads campaign + state + characters in a single query with eager loading. `serialize_snapshot()` produces Anthropic API format. `build_system_prompt()` with DM persona, hard constraints (no mechanical output, no contradicting engine, no metagaming), output rules (plain text, no Markdown), and multiplayer narration instructions. Token budget enforcement per ADR-0002. |
| `dm/narrator.py` | Complete. `AnthropicProvider` with streaming (`narrate_stream`) and non-streaming (`narrate`) narration. Model routing: Sonnet for complex/combat actions, Haiku for simple actions (keyword + word count heuristic). `compress_summary()` for rolling summary via Haiku. `LLMProvider` protocol for provider abstraction (ADR-0002 §7). Prompt caching via `cache_control: {"type": "ephemeral"}`. Response quality validation (Markdown and mechanical number detection). |
| `dm/summary.py` | **Does not exist.** Summary compression is called inline in `api/turns.py` via `narrator.update_summary()`, but the turn line passed to it is minimal ("Turn N: Character — action completed.") and loses most turn information. |

### Turn Lifecycle — Game loop exists, Rules Engine not integrated

| Component | Status |
|---|---|
| `api/turns.py` | Game loop implemented: submit action → build snapshot → create Turn record → return 202 → background task streams narrative via WebSocket → persists narrative → updates rolling summary → updates `last_played_at`. **Gap**: `rules_result` is always `None`. The Rules Engine is never called. Every action goes directly to Claude without mechanical resolution. |
| `api/campaigns.py` | Campaign CRUD complete. Session start/end with state machine (paused → active → paused). Tone presets (5 options) with `world_seed` and `dm_persona` defaults. **Gap**: Campaign creation uses static fallback text for `scene_context` — Claude does not generate an opening scene. |
| `api/characters.py` | Character creation endpoint exists (POST, returns 201). |
| `api/ws.py` | `ConnectionManager` with `broadcast()`. WebSocket endpoint sends `session.state` on connect. Emits `turn.narrative_start`, `turn.narrative_chunk`, `turn.narrative_end`, `system.error`. |

### Web Client — Skeleton

| File | Status |
|---|---|
| `App.tsx` | Main component — campaign/character selection, WS integration |
| `CampaignHeader.tsx` | Campaign title, status, scene context |
| `CharacterPanel.tsx` | Character sheet, HP, spell slots, conditions |
| `ChatLog.tsx` | Turn history with narratives |
| `ChatInput.tsx` | Player action submission |
| `hooks/useWebSocket.ts` | WS lifecycle, reconnect, JSON parsing |
| `types.ts` | TypeScript types: Campaign, CharacterState, SessionState, WsEvent |
| `index.css` | Design tokens and global resets |

Not yet functional as a playable game interface. Components exist but are not wired into a complete user flow (campaign creation → character creation → gameplay → session management).

### Discord Bot — Structurally complete, not integration-tested

| Component | Status |
|---|---|
| Cogs | `campaign.py`, `character.py`, `gameplay.py`, `lfg.py`, `ping.py`, `voice.py`, `websocket.py` |
| Embeds | `character_sheet.py`, `combat.py`, `lfg.py`, `narrative.py`, `rolls.py`, `status.py` |
| Services | `api_client.py` (HTTP client), `channel_manager.py`, `identity.py` |
| State | `models/state.py` — `BotState`, `PendingRoll`, `ReactionWindow` |

The gameplay cog is the most complete component: message interception, `/action`, `/roll`, `/history`, `/recap`, `/map`, `/pass` commands. All ADR-0009 WebSocket event listeners implemented (roll prompts, self-reactions, cross-player reactions, reaction window management with in-place message editing). Identity resolution from Discord user → Tavern character.

**Gap**: The bot has not been integration-tested against the live server. API client request/response shapes, WebSocket event routing between cogs, and the character creation thread flow may have mismatches.

### Models

`Campaign`, `CampaignState`, `Session`, `Character` (with `InventoryItem`, `CharacterCondition`), `Turn`. All with SQLAlchemy 2.x async, PostgreSQL 16.

### Infrastructure

Docker Compose: 4 services — `tavern` (FastAPI app), `postgres` (16), `5e-database` (MongoDB v4.6.3), `discord-bot`. GitHub Actions: CI (ruff, mypy, pytest), Claude Code PR review, MkDocs deploy.

---

## What Separates Us From a Playable Game

Three gaps remain between the current codebase and a playable M1:

1. **Missing engine orchestrators**: `resolve_spell()` does not exist. Rest mechanics do not exist.
2. **Rules Engine not in the turn pipeline**: `api/turns.py` sets `rules_result=None` for every action. No action analysis, no mechanical resolution, no character state mutation from engine results.
3. **Clients not wired into complete user flows**: Web client is a skeleton. Discord bot is structurally complete but untested against the live server.

Everything else — MongoDB data access, character mechanics, combat resolution, DM layer (Context Builder + Narrator + streaming), session management, WebSocket infrastructure — is built and functional.

---

## Milestones

### Milestone 1: First Playable — "A solo character can have an adventure"

**Player experience**: Create a character, start a campaign, explore narratively, fight simple enemies, take and deal damage, cast basic spells, level up, save and resume.

**Level cap**: 5 (Extra Attack, Level 3 spells, subclass at 3, first ASI at 4).

**Roll mode**: `automatic` only (ADR-0009 interactive rolling deferred to M2).

#### Remaining Work

Seven tasks, in dependency order:

```
M1-01 (resolve_spell)  ──┐
M1-02 (rest mechanics) ──┼──→ M1-03 (rules engine in turn pipeline)
                          │         │
                          │         ├──→ M1-05 (web client)
                          │         └──→ M1-06 (discord bot integration test)
M1-04 (campaign brief) ──┘
                     M1-07 (summary module) — anytime after M1-03
```

**M1-01: Spell Resolution Flow** — New file `core/spells.py` with `resolve_spell()`. Composes `srd_data.get_spell()` + `combat.resolve_attack()` for spell attacks + saving throw resolution + damage/healing calculation + condition application. M1 scope: cantrips + Level 1–3 spells. No AoE geometry (Claude adjudicates), no concentration state machine (flag only), no component enforcement.

**M1-02: Rest Mechanics** — `apply_short_rest()` and `apply_long_rest()` in `core/characters.py`. Short rest: spend hit dice to heal. Long rest: full HP, all spell slots, hit dice recovery (half level, min 1), death save reset. Returns result dataclasses, does not mutate database state.

**M1-03: Rules Engine Integration in Turn Pipeline** — The critical path task. Adds `core/action_analyzer.py` for keyword-based action classification (melee attack, ranged attack, cast spell, ability check, narrative). Modifies `api/turns.py` to run classified actions through the engine before narration. Populates `rules_result` in `TurnContext`. Applies engine results to character database state (HP, spell slots, conditions). Broadcasts `character.updated` WebSocket events. M1 constraint: NPC state is narrative-only (engine resolves player attacks against NPCs but does not persist NPC HP — Claude manages NPC survival narratively).

**M1-04: Campaign Creation with Claude Brief** — Modifies `api/campaigns.py` to call Claude (Haiku) during campaign creation, generating a campaign brief, opening scene description, and initial world_state fields. Graceful fallback to static text on API failure.

**M1-05: Web Client** — Transform the skeleton into a playable solo game interface. Four screens: campaign list/creation, character creation (class + species + background + ability scores), game session (streaming chat + character panel + action input), session controls. No auth, no multiplayer, no interactive rolling.

**M1-06: Discord Bot Integration Test** — Primarily verification and bugfix, not greenfield. Smoke test the full flow: `/tavern create` → `/character create` → gameplay → `/tavern stop`. Fix WebSocket event routing, API client mismatches, character creation thread flow, narrative posting.

**M1-07: Rolling Summary Module** — New file `dm/summary.py` with `build_turn_summary_input()` (structured turn line from action + rules result + narrative excerpt) and `trim_summary()` (500-token budget enforcement). Replaces the current minimal summary line in `api/turns.py`.

#### M1 Definition of Done

- [ ] `resolve_spell()` handles cantrips and Level 1–3 spells (damage, healing, conditions)
- [ ] Rest mechanics (`apply_short_rest()`, `apply_long_rest()`) function as state transitions
- [ ] Turn pipeline: action → analysis → engine resolution → snapshot → narration → persistence works end-to-end with `rules_result` populated for mechanical actions
- [ ] Campaign creation generates a Claude-authored opening scene
- [ ] Rolling summary captures action, rules result, and narrative excerpt per turn
- [ ] **Web client**: campaign creation → character creation → gameplay → session resume — all functional
- [ ] **Discord bot**: `/tavern create` → `/character create` → gameplay in channel → `/tavern stop` and resume — all functional
- [ ] `docker compose up` → playable within 5 minutes on either client

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
| Interactive dice rolling | 🎲 button on roll prompts, pre-roll option buttons, reaction window embeds with countdown (event listeners already implemented — server must emit events) |
| Multiplayer turn coordination | Turn prompt embeds, initiative order display, timeout handling |
| Authentication binding | Discord OAuth identity → Tavern character mapping |
| `/tavern invite` / `/tavern kick` | Mid-campaign player management |
| Configurable rolling mode | `/tavern config rolling_mode interactive\|automatic\|hybrid` |

#### M2 Definition of Done

- [ ] Full SRD spell catalog (Levels 0–9) resolvable by engine
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

Between milestones, some mechanics will be specced in the SRD but not yet implemented in the engine. The DM layer handles this via the system prompt:

- The system prompt tells Claude which mechanics the engine handles and which it should adjudicate narratively
- Example: In M1, AoE spells have no geometry engine — Claude decides who is hit based on the scene description. In M2, the engine calculates it.
- NPC HP tracking in M1 is narrative — the engine resolves player attacks ("14 damage to Goblin A") but does not persist NPC state. Claude decides narratively when NPCs are defeated.

**Hard constraint**: Claude's narrative adjudication must never contradict an engine result. If the engine says "attack hits, 8 damage," Claude narrates the hit. Claude only adjudicates mechanics the engine does not cover.

### Test Strategy

- Engine unit tests run against a test MongoDB instance seeded from 5e-database
- `tests/fixtures/srd_fixtures.py` contains original hardcoded data as expected-value baselines
- Integration tests (engine + MongoDB + DM layer + API) run in CI on every PR
- Discord bot integration tests are manual (require a live Discord server)

### Client Parity Principle

Per ADR-0005, both clients are first-class. The API is the bottleneck — once the API supports a feature, both clients can implement it independently. Don't wait for both clients to be ready before shipping server-side features.

---

## Review Triggers

- If the fork's 2024-* data has errors or gaps that affect gameplay: fix in the fork, release a new tavern-suffixed tag, and submit the fix as an upstream PR. Campaign Overrides are for per-deployment customisation, not for SRD corrections. File upstream issues regardless.
- If AoE geometry implementation in M2 exceeds 3 sessions of effort, evaluate a simplified model (discrete zones instead of continuous geometry) as an intermediate step.
- If the turn lifecycle latency (action → narrative response) exceeds 8 seconds excluding Claude API time, profile and optimize the engine/context builder path before adding more features.
- If either client falls more than one milestone behind the other, evaluate whether to pause new server features and focus on client parity.
- If the 5e-bits/5e-database project is abandoned or significantly diverges from SRD 5.2.1, fork the MongoDB image and maintain independently — the dataset is MIT-licensed and the fork is trivial.
- If M1 takes longer than 6 weeks of active development, evaluate whether the scope should be reduced (e.g., fewer classes at launch, delayed level-up, single client only for M1).
- If the action analyzer in M1-03 misclassifies actions frequently (>20% of mechanical actions routed as narrative), evaluate adding a lightweight LLM classification step — but only after keyword-based classification has been proven insufficient.
