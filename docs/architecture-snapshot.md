# Architecture Snapshot

> Last updated: 2026-04-03 — Added SRD import pipeline (scripts/schemas/, scripts/srd_import/), SRD reference models (models/srd_data.py), Alembic migration 0003, jsonschema dev dependency
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
├── core/               # Rules Engine — SRD 5.2.1 mechanics, no LLM dependency
│   ├── dice.py             # Dice rolling, advantage/disadvantage, NdX notation parser, deterministic seeds
│   ├── characters.py       # Ability modifiers, HP, spell slots, proficiency bonus, standard array validation
│   ├── combat.py           # Attack resolution, damage application, initiative, grapple/shove, death saves
│   ├── conditions.py       # 15 SRD conditions, attack/save modifiers, speed, incapacitation logic
│   └── srd_tables.py       # All SRD 5.2.1 game data: classes, species, backgrounds, spell slots, XP
├── dm/                 # DM layer — Narrator, Context Builder, LLM provider abstraction
│   ├── narrator.py         # Narrator class; model routing (Sonnet/Haiku); streaming narration and summary compression
│   └── context_builder.py  # StateSnapshot, TurnContext; builds and serializes game state for the Narrator
├── api/                # FastAPI REST endpoints and WebSocket handler
│   ├── campaigns.py        # Campaign CRUD + session lifecycle
│   ├── characters.py       # Character creation and retrieval
│   ├── turns.py            # Turn submission (202) and retrieval
│   ├── ws.py               # WebSocket endpoint + ConnectionManager
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
│   └── srd_data.py         # SRD reference tables: SrdSpecies, SrdClass, SrdClassFeature, SrdSubclass,
│                           #   SrdBackground, SrdFeat, SrdWeapon, SrdArmor, SrdEquipment, SrdSpell,
│                           #   SrdMonster, SrdMonsterAction, SrdCondition, SrdMagicItem, SrdRulesTable
├── alembic/            # Database migrations
│   ├── env.py              # Async migration runner (asyncpg)
│   ├── script.py.mako      # Migration file template
│   └── versions/
│       ├── 0001_initial.py                                     # Initial schema
│       ├── 0002_add_campaign_session_character_turn_models.py  # Campaign, Session, Character, Turn tables
│       └── 0003_add_srd_reference_tables.py                   # 15 SRD reference tables
├── auth/               # Placeholder — Phase 6 authentication (not yet implemented)
└── multiplayer/        # Placeholder — future multiplayer support

frontend/src/
├── App.tsx             # Root component — campaign/character selection, WS integration
├── main.tsx            # Vite entry point
├── types.ts            # Shared TypeScript types: Campaign, CharacterState, SessionState, WsEvent union
├── index.css           # Tavern design tokens and global resets
├── hooks/
│   └── useWebSocket.ts     # WS lifecycle, reconnect with configurable delay, JSON parsing
└── components/
    ├── CampaignHeader.tsx  # Campaign title, status, scene context
    ├── CharacterPanel.tsx  # Character sheet, HP, spell slots, conditions
    ├── ChatLog.tsx         # Turn history with narratives
    └── ChatInput.tsx       # Player action submission

scripts/
├── setup-repo.sh       # GitHub repository configuration (labels, branch protection, issue templates)
├── schemas/            # JSON Schema files — contracts between import pipeline and Rules Engine
│   ├── species.json        # Species: size, speed, darkvision, traits, subspecies
│   ├── class.json          # Class: hit die, saving throws, features by level, subclass level
│   ├── class_feature.json  # Class feature: name, class, level, optional mechanical_effect
│   ├── subclass.json       # Subclass: parent class, features by level
│   ├── background.json     # Background: ability scores, skill proficiencies, origin feat
│   ├── feat.json           # Feat: category (origin/general/fighting_style), prerequisites, effects
│   ├── weapon.json         # Weapon: category, damage_dice, damage_type, properties, range
│   ├── armor.json          # Armor: type, base_ac, dex_cap, stealth_disadvantage
│   ├── equipment.json      # Adventuring gear: category, weight, cost
│   ├── spell.json          # Spell: level, school, components, AOE, conditions_applied
│   ├── monster.json        # Monster stat block: ability scores, resistances, CR, actions
│   ├── monster_action.json # Monster action/trait: attack_bonus, damage, save_dc, recharge
│   ├── condition.json      # Condition: structured mechanical_effects (speed, saves, actions)
│   ├── magic_item.json     # Magic item: rarity, attunement, mechanical_effects
│   └── rules_table.json    # Reference table: flexible data shape per table
└── srd_import/         # SRD import pipeline (extract → parse → validate → seed)
    ├── extract.py          # Chunk SRD PDF by section into text files (uses pypdf)
    ├── claude_parse.py     # Claude-assisted extraction: chunks → structured JSON per schema
    ├── validate.py         # Schema validation, cross-references, plausibility checks, baseline diff
    ├── seed.py             # Idempotent upsert of reviewed JSON into PostgreSQL
    ├── chunks/             # Generated: PDF text chunks (gitignored)
    ├── extracted/          # Generated: raw Claude output (gitignored)
    └── review/             # Generated: validated JSON staged for human review (gitignored)

Infrastructure/
├── Dockerfile          # Multi-stage: Node 20 frontend build → Python 3.12 runtime; serves on :3000
├── docker-compose.yml  # Three services: tavern (app), postgres (16), discord-bot
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
api/ ──→ core/
api/ ──→ dm/
api/ ──→ models/
dm/  ──→ models/
core/ ──→ (no internal dependencies)
models/ ──→ (no internal dependencies)
```

> Constraint: core/ must never import from dm/ (see ADR-0001).

## External Dependencies

### Backend (pyproject.toml)

| Dependency | Purpose | Locked to |
|---|---|---|
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
| dev | pytest, pytest-asyncio, httpx, ruff, mypy, aiosqlite, pypdf, jsonschema | Development and testing |
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
| character.updated | server → client | character_id, campaign_id (HP/condition changes) |
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
| SrdSpecies | srd_species | reference data; indexed on name |
| SrdClass | srd_classes | reference data; indexed on name |
| SrdClassFeature | srd_class_features | reference data; unique on (class_name, name) |
| SrdSubclass | srd_subclasses | reference data; unique on (class_name, name) |
| SrdBackground | srd_backgrounds | reference data; indexed on name |
| SrdFeat | srd_feats | reference data; indexed on name, category |
| SrdWeapon | srd_weapons | reference data; indexed on name, category |
| SrdArmor | srd_armor | reference data; indexed on name, type |
| SrdEquipment | srd_equipment | reference data; indexed on name, category |
| SrdSpell | srd_spells | reference data; indexed on name, level, school |
| SrdMonster | srd_monsters | reference data; indexed on name, type, cr |
| SrdMonsterAction | srd_monster_actions | reference data; unique on (monster_name, name) |
| SrdCondition | srd_conditions | reference data; indexed on name |
| SrdMagicItem | srd_magic_items | reference data; indexed on name, type, rarity |
| SrdRulesTable | srd_rules_tables | reference data; unique on table_name |

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
