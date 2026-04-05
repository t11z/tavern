# Architecture Snapshot

> Last updated: 2026-04-05 — Added CharacterSheetOverlay component; extended CharacterState with optional fields (ability_scores, proficiencies, speed, species, spells, inventory, conditions, etc.); added SKILL_ABILITY_MAP and CONDITION_SUMMARIES to constants.ts
>
> This document is maintained by Claude Code per the rules in CLAUDE.md.
> It is consumed by the architecture consultant to inform decisions without
> direct code access. Keep it factual and current. Do not add rationale —
> that belongs in ADRs.

## Module Structure

```
backend/tavern/
├── main.py             # FastAPI app factory; mounts routers, static files, error handlers
├── db.py               # Async SQLAlchemy engine and session factory
├── srd_db.py           # AsyncIOMotorClient lifecycle (connect_srd_db / close_srd_db / get_srd_db)
├── core/               # Rules Engine — SRD 5.2.1 mechanics, no LLM dependency
│   ├── dice.py             # Dice rolling, advantage/disadvantage, NdX notation parser, deterministic seeds
│   ├── characters.py       # Ability modifiers, HP, spell slots, proficiency bonus, standard array validation (async)
│   ├── combat.py           # Attack resolution, damage application, initiative, grapple/shove, death saves; CombatParticipant dataclass (one combatant's initiative state; surprised flag set once, read once); CombatSnapshotCharacter dataclass (minimal per-character data for Surprise: WIS mod, Perception proficiency, feats); CombatSnapshot dataclass ({character_id: CombatSnapshotCharacter}, used instead of StateSnapshot to preserve core/→dm/ direction); determine_surprise(potential_surprised, stealth_results, snapshot: CombatSnapshot) → dict[str, bool] (all-concealers-must-succeed rule, SRD 5.2.1 RAW); _has_surprise_immunity(character_id, snapshot: CombatSnapshot) → bool (Alert feat pre-filter); roll_initiative_order(participants, *, surprised_map, dex_modifiers, seeds) → list[CombatParticipant] (Disadvantage for surprised participants)
│   ├── conditions.py       # 15 SRD conditions, attack/save modifiers, speed, incapacitation logic
│   ├── action_analyzer.py  # Keyword-based action classification (no LLM): ActionCategory enum, ActionAnalysis dataclass, analyze_action()
│   ├── spells.py           # Spell resolution orchestrator: slot validation, attack/save/auto-hit routing, damage/healing calculation, condition application
│   ├── srd_data.py         # SRD Data Access Layer: three-tier lookup (Campaign Override → Instance Library → SRD Baseline); resolve_npc_stat_block(stat_block_ref: str, campaign_id: UUID) → dict | None (three-tier monster lookup for NPC stat block population; logs warning not error on miss)
├── dm/                 # DM layer — Narrator, Context Builder, LLM provider abstraction
│   ├── narrator.py         # Narrator class; model routing (Sonnet/Haiku); streaming narration and summary compression; GMSignals delimiter buffering (stops forwarding to clients after ---GM_SIGNALS---); parse_gm_signals() integration; narrate_turn_stream() returns tuple[str, GMSignals]
│   ├── context_builder.py  # StateSnapshot, TurnContext; builds and serializes game state for the Narrator; TurnContext.stealth_rolls: dict[str, int] (Path B Surprise, ADR-0014); StateSnapshot.session_mode: str (guards CombatClassifier, ADR-0011); StateSnapshot.npcs: list[dict] (compact NPC records, ADR-0013, scene-scoped and recency-filtered last 10 turns, excludes dead/fled unless plot_significant)
│   ├── summary.py          # Rolling summary helpers: build_turn_summary_input(), trim_summary(); enforces 500-token budget
│   ├── combat_classifier.py # CombatClassifier — Haiku-based binary LLM classifier for combat initiation detection; classify(action_text: str, snapshot: StateSnapshot) → CombatClassification; called pre-narration in exploration mode only; raises RuntimeError in combat mode (ADR-0011); no dependency on core/
│   └── gm_signals.py       # GMSignals, SceneTransition, NPCUpdate dataclasses; GM_SIGNALS_DELIMITER = "---GM_SIGNALS---" constant; parse_gm_signals(raw: str) → GMSignals — safe-default on any parse failure; safe_default() → GMSignals
├── api/                # FastAPI REST endpoints and WebSocket handler
│   ├── campaigns.py        # Campaign CRUD + session lifecycle; calls Narrator for Claude-generated opening scene on create
│   ├── characters.py       # Character creation and retrieval
│   ├── turns.py            # Turn submission (202) and retrieval; wires action_analyzer + Rules Engine; broadcasts character.updated; full combat lifecycle: CombatClassifier invoked pre-narration (exploration mode only); GMSignals processed post-narration (npc_updates before scene_transition, mandatory ordering per ADR-0012); engine combat_end takes precedence over Narrator combat_end signal when both fire on same turn; player-initiated (Flow B) and NPC-initiated (Flow A) combat paths both produce identical combat.started WebSocket event
│   ├── npcs.py             # NPC roster CRUD for campaign: POST (201), GET list, GET single, PATCH; PATCH enforces immutability — returns 422 if name, species, or appearance in request body; scoped to /api/campaigns/{campaign_id}/npcs
│   ├── ws.py               # WebSocket endpoint + ConnectionManager
│   ├── srd.py              # Custom SRD content: Instance Library CRUD + Campaign Override CRUD
│   ├── dependencies.py     # Shared FastAPI dependencies (get_db_session, get_narrator, get_session_factory)
│   ├── schemas.py          # Pydantic request/response schemas
│   └── errors.py           # APIError + error handlers
├── discord_bot/        # Discord client — connects to Tavern API, translates Discord interactions
│   ├── bot.py              # TavernBot (commands.Bot subclass); loads cogs, syncs slash commands
│   ├── config.py           # BotConfig dataclass; validates required env vars on init
│   ├── __main__.py         # Entry point: python -m tavern.discord_bot
│   ├── cogs/               # discord.py Cog modules (one per command group)
│   │   ├── campaign.py         # /campaign create|info|config|recap|scene; /session start|end; /tavern delete (with confirmation)
│   │   ├── character.py        # /character create|sheet|inventory|spells; guided creation threads
│   │   ├── gameplay.py         # /action, /roll, /pass; WebSocket event → Discord message routing
│   │   ├── lfg.py              # /lfg — bind a campaign to a Discord text channel
│   │   ├── ping.py             # /tavern ping — health check for bot + API
│   │   ├── voice.py            # Voice channel integration (stub)
│   │   └── websocket.py        # WebSocketCog — persistent WS connection; dispatches bot events
│   ├── embeds/             # Pure functions: raw API dict → discord.Embed
│   │   ├── character_sheet.py  # build_character_sheet_embed, build_inventory_embed, build_spells_embed
│   │   ├── combat.py           # build_combat_embed, build_party_status
│   │   ├── lfg.py              # build_lfg_embed
│   │   ├── narrative.py        # build_narrative_embed
│   │   ├── rolls.py            # build_roll_embed, build_reaction_window_embed, ReactionWindowView, SelfReactionView
│   │   └── status.py           # build_status_embed
│   ├── models/
│   │   └── state.py            # BotState, ChannelBinding, PendingRoll, ReactionWindow — in-memory runtime state
│   └── services/
│       ├── api_client.py       # TavernAPI — async httpx client wrapping all REST endpoints
│       ├── channel_manager.py  # ChannelManager — Discord channel lifecycle helpers
│       └── identity.py         # IdentityService — Discord user ↔ Tavern user/character mapping (cached)
├── models/             # SQLAlchemy ORM models (database schema)
│   ├── base.py             # DeclarativeBase; JSONB custom type (JSONB on PostgreSQL, JSON on SQLite)
│   ├── campaign.py         # Campaign, CampaignState
│   ├── character.py        # Character, InventoryItem, CharacterCondition
│   ├── session.py          # Session
│   ├── turn.py             # Turn
│   ├── npc.py              # NPC — campaign-scoped (campaign_id FK with CASCADE); immutable fields (name, species, appearance) enforced at model layer; mutable state (hp_current, hp_max, ac, disposition, status, scene_location, motivation, creature_type, stat_block_ref, first_appeared_turn, last_seen_turn); identity-adjacent fields: role (immutable intent, set at spawn); origin: "predefined"|"narrator_spawned"; plot_significant: bool (persists in snapshot after death/flight when True); validate_immutable_update(updates: dict) classmethod — raises ValueError on immutable field update
├── alembic/            # Database migrations
│   ├── env.py              # Async migration runner (asyncpg)
│   ├── script.py.mako      # Migration file template
│   └── versions/
│       ├── 0001_initial.py                                     # Initial schema
│       ├── 0002_add_campaign_session_character_turn_models.py  # Campaign, Session, Character, Turn tables
│       ├── 0003_add_srd_reference_tables.py                   # 15 SRD reference tables (superseded)
│       └── 0004_drop_srd_reference_tables.py                  # Drop all SRD PostgreSQL tables (data now in MongoDB)
├── auth/               # Placeholder — Phase 6 authentication (not yet implemented)
└── multiplayer/        # Placeholder — future multiplayer support

frontend/src/
├── App.tsx             # Screen router: campaigns → campaign detail → character creation → game session
├── main.tsx            # Vite entry point
├── types.ts            # Shared TypeScript types: Campaign, CampaignDetail, CharacterState (extended with optional fields: species, speed, initiative_modifier, proficiency_bonus, ability_scores, ability_modifiers, proficiencies, languages, background, spell_slots_max, spells, class_features, inventory, conditions), InventoryItem, SpellEntry, SessionState, WsEvent union (incl. character.updated)
├── constants.ts        # SRD constants: classes, species, backgrounds (with eligible abilities), standard array, tone presets, SKILL_ABILITY_MAP (18 SRD skills → ability), CONDITION_SUMMARIES (15 SRD conditions → one-line summary), ABILITY_EMOJIS (6 abilities → emoji)
├── index.css           # Tavern design tokens, global resets, blink keyframe
├── hooks/
│   └── useWebSocket.ts     # WS lifecycle, reconnect with configurable delay, JSON parsing
└── components/
    ├── CampaignList.tsx    # Screen 1: campaign list + new campaign form (name, tone preset)
    ├── CampaignDetail.tsx  # Screen 2: campaign view, character list, start/rejoin session button
    ├── CharacterCreation.tsx # Screen 3: 2-step wizard (class/species/background/bonuses → standard array assignment)
    ├── GameSession.tsx     # Screen 4: game loop with sidebar, chat, WS streaming, end session; characterSheetOpen state drives CharacterSheetOverlay; normalizeCharacter() extracts species/languages/background/ability_modifiers/proficiency_bonus from features{} grab-bag and populates class_features with the remainder; applied on session.state and character.updated (merge, not replace)
    ├── CampaignHeader.tsx  # Campaign title, turn count, WS status dot
    ├── CharacterPanel.tsx  # Character card: HP bar, AC, spell slots; click opens CharacterSheetOverlay (also sets active character); hover border affordance
    ├── CharacterSheetOverlay.tsx # Full-screen modal: emoji+colored ability grid, languages section, background in header, saving throws + skills with colored modifiers, spell slots with pips and N/max count, class_features (not raw features{}), equipment, conditions; getMod() prefers server ability_modifiers over local calculation; read-only; closes on Escape or backdrop click
    ├── ChatLog.tsx         # Turn history with rules_result (monospace) + narrative; streaming cursor
    └── ChatInput.tsx       # Textarea + Act button; disabled while streaming or disconnected

scripts/
└── setup-repo.sh       # GitHub repository configuration (labels, branch protection, issue templates)

Infrastructure/
├── Dockerfile          # Multi-stage: Node 20 frontend build → Python 3.12 runtime; serves on :3000
├── docker-compose.yml  # Four services: tavern (app), postgres (16), 5e-database (MongoDB), discord-bot
└── .github/
    ├── workflows/
    │   ├── ci.yml              # Lint (ruff), type check (mypy), test (pytest) on push/PR
    │   ├── claude-review.yml   # Claude Code automated PR review
    │   └── deploy-docs.yml     # MkDocs site deploy to GitHub Pages
    └── ISSUE_TEMPLATE/
        ├── bug_report.yml
        ├── feature_request.yml
        ├── srd_correction.yml
        └── world_preset.yml
```

## Dependency Graph

```
api/     ──→ core/   (including core/action_analyzer.py, core/spells.py, core/combat.py)
api/     ──→ dm/
api/     ──→ models/
api/     ──→ srd_db
dm/      ──→ models/
core/    ──→ srd_db   (via core/srd_data.py)
srd_db   ──→ (no internal dependencies)
models/  ──→ (no internal dependencies)
```

> Constraint: core/ must never import from dm/ (see ADR-0001).

## External Dependencies

### Backend (pyproject.toml)

| Dependency | Purpose | Locked to |
|---|---|---|
| motor | Async MongoDB driver (AsyncIOMotorClient) | >=3.0.0 |
| fastapi | Web framework, WebSocket support | >=0.115.0 |
| uvicorn[standard] | ASGI server | >=0.32.0 |
| sqlalchemy[asyncio] | ORM, async sessions | >=2.0.0 |
| asyncpg | PostgreSQL async driver | >=0.30.0 |
| alembic | Database migrations | >=1.14.0 |
| pydantic | Request/response validation | >=2.10.0 |
| python-dotenv | Environment variable loading | >=1.0.0 |
| anthropic | Claude API (Narrator) | >=0.88.0 |
| discord.py | Discord bot client (slash commands, intents, cogs) | >=2.4.0 |
| websockets | WebSocket client used by discord_bot WebSocketCog | >=13.0 |

### Dependency Groups (pyproject.toml)

| Group | Dependencies | Purpose |
|---|---|---|
| dev | pytest, pytest-asyncio, httpx, ruff, mypy, aiosqlite | Development and testing |
| discord-bot | discord.py>=2.3, httpx>=0.27 | Documents discord_bot/ runtime requirements |

### Frontend (package.json)

| Dependency | Purpose | Locked to |
|---|---|---|
| react | UI framework | ^18.3.1 |
| react-dom | DOM bindings | ^18.3.1 |
| vite | Build tool + dev server proxy | ^5.4.10 |
| typescript | Type checking | ^5.6.2 |
| @vitejs/plugin-react | Vite plugin for React/JSX transform | ^4.3.3 |

## API Surface

### REST Endpoints

| Method | Path | Purpose | Status code |
|---|---|---|---|
| GET | /health | Liveness check | 200 |
| GET | /api/campaigns | List campaigns | 200 |
| POST | /api/campaigns | Create campaign | 201 |
| GET | /api/campaigns/{id} | Get campaign detail | 200 |
| PATCH | /api/campaigns/{id} | Update campaign name/status | 200 |
| DELETE | /api/campaigns/{id} | Delete campaign and all data (blocked if active) | 204 |
| POST | /api/campaigns/{id}/sessions | Start session (activates campaign) | 201 |
| POST | /api/campaigns/{id}/sessions/end | End session (pauses campaign) | 200 |
| GET | /api/campaigns/{id}/characters | List characters | 200 |
| POST | /api/campaigns/{id}/characters | Create character | 201 |
| GET | /api/campaigns/{id}/characters/{char_id} | Get character | 200 |
| PATCH | /api/campaigns/{id}/characters/{char_id} | Update character | 200 |
| POST | /api/campaigns/{id}/turns | Submit player action | 202 |
| GET | /api/campaigns/{id}/turns | List turns (paginated) | 200 |
| GET | /api/campaigns/{id}/turns/{turn_id} | Get single turn | 200 |
| POST | /api/campaigns/{id}/npcs | Create NPC | 201 |
| GET | /api/campaigns/{id}/npcs | List NPCs for campaign | 200 |
| GET | /api/campaigns/{id}/npcs/{npc_id} | Get single NPC | 200 |
| PATCH | /api/campaigns/{id}/npcs/{npc_id} | Update NPC mutable state (422 if immutable fields present) | 200 |
| GET | /api/srd/{collection} | List custom documents (Instance Library) | 200 |
| POST | /api/srd/{collection} | Create custom document | 201 |
| GET | /api/srd/{collection}/{index} | Get custom document | 200 |
| PUT | /api/srd/{collection}/{index} | Replace custom document | 200 |
| DELETE | /api/srd/{collection}/{index} | Delete custom document | 204 |
| GET | /api/campaigns/{id}/overrides/{collection} | List campaign overrides | 200 |
| POST | /api/campaigns/{id}/overrides/{collection} | Create campaign override | 201 |
| GET | /api/campaigns/{id}/overrides/{collection}/{index} | Get campaign override | 200 |
| PUT | /api/campaigns/{id}/overrides/{collection}/{index} | Replace campaign override | 200 |
| DELETE | /api/campaigns/{id}/overrides/{collection}/{index} | Delete campaign override | 204 |

### WebSocket

| Path | Purpose |
|---|---|
| /api/campaigns/{id}/ws | Campaign real-time event stream |

### WebSocket Events

Events currently emitted by the API server:

| Event | Direction | Payload summary |
|---|---|---|
| session.state | server → client | Campaign, characters, scene, recent_turns (on connect) |
| turn.narrative_start | server → client | turn_id (streaming begins) |
| turn.narrative_chunk | server → client | turn_id, chunk, sequence (token-by-token) |
| turn.narrative_end | server → client | turn_id, full narrative, mechanical_results, character_updates |
| system.error | server → client | message (narrator or system error) |
| combat.started | server → client | initiative_order: list[dict], surprised: list[str] |
| combat.ended | server → client | {} |
| npc.spawned | server → client | npc_id: str, name: str, role: str \| None |
| npc.updated | server → client | npc_id: str, changes: dict |

Events the discord_bot `gameplay.py` cog is ready to handle (not yet emitted by server):

| Event | Direction | Payload summary |
|---|---|---|
| player.joined | server → client | display_name, character_name |
| player.left | server → client | display_name, character_name |
| character.updated | server → client | character_id, campaign_id, hp, spell_slots (emitted by turns.py when engine mutates state) |
| turn.self_reaction_window | server → client | roll_id, turn_id, rolling_character_id, available_reactions, window_seconds |
| turn.reaction_window | server → client | roll_id, turn_id, roll_context, reactors (list of character_id + reactions), window_seconds |
| turn.reaction_used | server → client | roll_id, turn_id, reactor (character_id, reaction_id, uses_remaining) |
| turn.reaction_window_closed | server → client | roll_id, turn_id, final_result, outcome |

## Database Models

| Model | Table | Key relations |
|---|---|---|
| Campaign | campaigns | has one CampaignState, has many Session, has many Character |
| CampaignState | campaign_states | belongs to Campaign (unique FK) |
| Session | sessions | belongs to Campaign, has many Turn |
| Character | characters | belongs to Campaign, has many InventoryItem, has many CharacterCondition, has many Turn |
| InventoryItem | inventory_items | belongs to Character |
| CharacterCondition | character_conditions | belongs to Character |
| Turn | turns | belongs to Session, belongs to Character |
| NPC | npcs | belongs to Campaign (cascade delete); immutable identity fields (name, species, appearance); mutable state fields (hp_current, hp_max, ac, disposition, status, scene_location, motivation, creature_type, stat_block_ref, first_appeared_turn, last_seen_turn); role set at spawn; origin and plot_significant flags |

SRD reference data is no longer stored in PostgreSQL. It is served from the
t11z/5e-database MongoDB container via ``core/srd_data.py``.

### MongoDB Collections (5e-database)

| Collection | Contents |
|---|---|
| 2024-classes | SRD 5.2.1 class documents (barbarian, wizard, …) |
| 2024-levels | Per-class-per-level documents (spell slots, features, unified level-3 subclass selection) |
| 2024-species | Species documents (dragonborn, dwarf, elf, gnome, goliath, halfling, human, orc, tiefling) |
| 2024-backgrounds | Background documents with ability bonuses, Origin Feats, skill/tool proficiencies |
| 2024-feats | Feat documents including Origin Feats |
| 2024-spells | Spell documents |
| 2024-monsters | Monster stat blocks |
| 2024-conditions | Condition documents |
| 2024-equipment | Equipment documents |
| 2024-magic-items | Magic item documents |
| custom_{collection} | Instance Library: custom/homebrew documents per collection |
| campaign_overrides | Campaign-scoped overrides: { campaign_id, collection, index, data } |

### SRD Data Source
 
Tavern's SRD data comes from `t11z/5e-database`, a fork of `5e-bits/5e-database` (MIT license). The fork exists to complete the `2024-*` MongoDB collections with SRD 5.2.1 data that upstream has not yet published. See ADR-0010.
 
**Image registry:** `ghcr.io/t11z/5e-database`
**Version scheme:** `v{upstream}-tavern.{patch}` (e.g., `v4.6.3-tavern.1`)
**Upstream sync:** Manual, on new upstream releases. Merge upstream → verify against Tavern test suite → release new tavern-suffixed tag.
**Upstream contributions:** Every document added to the fork is a candidate for a PR to `5e-bits/5e-database`.

## ADR Status

| ADR | Title | Status |
|---|---|---|
| 0000 | ADR Process and Template | Accepted |
| 0001 | SRD Rules Engine | Accepted |
| 0002 | Claude as Narrator | Accepted |
| 0003 | Tech Stack | Accepted |
| 0004 | Campaign and Session Lifecycle | Accepted |
| 0005 | Client Architecture | Accepted |
| 0006 | Authentication and Authorization | Accepted |
| 0007 | Multiplayer and Real-Time Communication | Accepted |
| 0008 | Discord Bot Voice Pipeline | Accepted |
| 0009 | Interactive Dice Rolling and Reaction System | Accepted |
| 0010 | SRD Data Source Fork and 2024 Dataset Migration | Accepted |
| 0011 | Combat Trigger via Dedicated LLM Classifier | Accepted |
| 0012 | NPC-Initiated Combat | Accepted |
| 0013 | NPC Lifecycle | Accepted |
| 0014 | Surprise Mechanics | Accepted |
| 0015 | Narrator-Generated Suggested Actions | Accepted |
| 0016 | World Object Persistence | Accepted |
| 0017 | Scene Identifier Convention | Accepted |

## Known Deviations

| ADR | Deviation | Reason | Temporary? |
|---|---|---|---|
| 0001 | Python constants for XP thresholds in srd_data.py | Data not yet in fork's 2024-levels collection | Yes — remove when fork includes XP data |
| 0006 | No auth middleware on any endpoint | Auth not yet implemented | Yes — Phase 6 |

## Architecture Questions

| Date | Question | Context |
|---|---|---|
| — | — | — |
