# Architecture Snapshot

> Last updated: 2026-04-04 — Implemented playable M1 web client (4-screen SPA)
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
│   ├── combat.py           # Attack resolution, damage application, initiative, grapple/shove, death saves
│   ├── conditions.py       # 15 SRD conditions, attack/save modifiers, speed, incapacitation logic
│   ├── action_analyzer.py  # Keyword-based action classification (no LLM): ActionCategory enum, ActionAnalysis dataclass, analyze_action()
│   ├── spells.py           # Spell resolution orchestrator: slot validation, attack/save/auto-hit routing, damage/healing calculation, condition application
│   ├── srd_data.py         # SRD Data Access Layer: three-tier lookup (Campaign Override → Instance Library → SRD Baseline)
├── dm/                 # DM layer — Narrator, Context Builder, LLM provider abstraction
│   ├── narrator.py         # Narrator class; model routing (Sonnet/Haiku); streaming narration, summary compression, campaign brief generation (Haiku)
│   └── context_builder.py  # StateSnapshot, TurnContext; builds and serializes game state for the Narrator
├── api/                # FastAPI REST endpoints and WebSocket handler
│   ├── campaigns.py        # Campaign CRUD + session lifecycle; calls Narrator for Claude-generated opening scene on create
│   ├── characters.py       # Character creation and retrieval
│   ├── turns.py            # Turn submission (202) and retrieval; wires action_analyzer + Rules Engine; broadcasts character.updated
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
│   │   ├── campaign.py         # /campaign create|info|config|recap|scene; /session start|end
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
├── types.ts            # Shared TypeScript types: Campaign, CampaignDetail, CharacterState, SessionState, WsEvent union (incl. character.updated)
├── constants.ts        # SRD constants: classes, species, backgrounds (with eligible abilities), standard array, tone presets
├── index.css           # Tavern design tokens, global resets, blink keyframe
├── hooks/
│   └── useWebSocket.ts     # WS lifecycle, reconnect with configurable delay, JSON parsing
└── components/
    ├── CampaignList.tsx    # Screen 1: campaign list + new campaign form (name, tone preset)
    ├── CampaignDetail.tsx  # Screen 2: campaign view, character list, start/rejoin session button
    ├── CharacterCreation.tsx # Screen 3: 2-step wizard (class/species/background/bonuses → standard array assignment)
    ├── GameSession.tsx     # Screen 4: game loop with sidebar, chat, WS streaming, end session
    ├── CampaignHeader.tsx  # Campaign title, turn count, WS status dot
    ├── CharacterPanel.tsx  # Character card: HP bar, AC, spell slots; clickable to set active
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
| POST | /api/campaigns/{id}/sessions | Start session (activates campaign) | 201 |
| POST | /api/campaigns/{id}/sessions/end | End session (pauses campaign) | 200 |
| GET | /api/campaigns/{id}/characters | List characters | 200 |
| POST | /api/campaigns/{id}/characters | Create character | 201 |
| GET | /api/campaigns/{id}/characters/{char_id} | Get character | 200 |
| PATCH | /api/campaigns/{id}/characters/{char_id} | Update character | 200 |
| POST | /api/campaigns/{id}/turns | Submit player action | 202 |
| GET | /api/campaigns/{id}/turns | List turns (paginated) | 200 |
| GET | /api/campaigns/{id}/turns/{turn_id} | Get single turn | 200 |
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

SRD reference data is no longer stored in PostgreSQL. It is served from the
5e-bits/5e-database MongoDB container via ``core/srd_data.py``.

### MongoDB Collections (5e-database)

| Collection | Contents |
|---|---|
| classes | SRD class documents (barbarian, wizard, …) |
| levels | Per-class-per-level documents (spell slots, features) |
| races | Species documents (5e-database legacy name; exposed as ``species`` in Tavern's API) |
| backgrounds | Background documents |
| feats | Feat documents |
| spells | Spell documents |
| monsters | Monster stat blocks |
| conditions | Condition documents |
| equipment | Equipment documents |
| magic-items | Magic item documents |
| custom_{collection} | Instance Library: custom/homebrew documents per collection |
| campaign_overrides | Campaign-scoped overrides: { campaign_id, collection, index, data } |

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

## Known Deviations

| ADR | Deviation | Reason | Temporary? |
|---|---|---|---|
| 0006 | No auth middleware on any endpoint | Auth not yet implemented | Yes — Phase 6 |

## Architecture Questions

| Date | Question | Context |
|---|---|---|
| — | — | — |
