# ADR-0013: NPC Lifecycle — Definition, Persistence, and Narrator Integration

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/models/` (new `npc.py`), `backend/tavern/dm/context_builder.py`, `backend/tavern/api/turns.py`, `backend/tavern/api/campaigns.py`, database schema

## Context

The first gameplay session of Tavern revealed a fundamental consistency problem: the
Harbormaster NPC appeared under different names, physical descriptions, and personalities
across consecutive turns. The root cause is structural — the Narrator invents NPCs from
scene context on every call, with no persistent record. There is no NPC spawn moment, no
NPC record, no state to read from the snapshot.

This is not a prompt engineering problem. Instructing the Narrator to "be consistent" is
not enforceable when there is no source of truth to be consistent with. Consistency
requires persistence. Persistence requires a data model and a lifecycle.

The problem has two distinct dimensions:

**Pre-defined NPCs**: A campaign revolving around a dragon requires that dragon to exist
before the first session. Named quest-givers, recurring antagonists, and story-critical
characters must be authored in advance with fixed attributes. These NPCs are part of the
campaign's narrative contract with the player — their names, appearances, and motivations
cannot shift between sessions.

**Narrator-spawned NPCs**: A harbour guard, a random merchant, a tavern patron — these
emerge spontaneously from the Narrator's scene descriptions. They do not exist before the
moment the Narrator introduces them. But once introduced, they must persist. "The
harbormaster" who appeared in turn 3 must be the same entity in turn 7, with the same name
and appearance.

Both types land in the same data model. The difference is origin — one is authored at
campaign setup, the other is materialised by the Narrator at runtime.

A human Game Master handles this naturally: when an NPC appears, the GM writes a quick
note — name, description, role, rough stats if combat is possible. That note becomes the
source of truth for all future references to that NPC. This ADR encodes that practice as
a system component.

## Decision

### 1. NPC data model

NPCs are persisted as records in PostgreSQL. Each NPC belongs to a campaign.

```python
class NPC(Base):
    __tablename__ = "npcs"

    id: UUID                        # Primary key
    campaign_id: UUID               # Foreign key → campaigns.id
    name: str                       # Canonical name — immutable once set
    origin: Literal["predefined", "narrator_spawned"]
    status: Literal["alive", "dead", "fled", "unknown"]

    # Persistent attributes — set at spawn, immutable unless explicitly updated
    species: str | None             # e.g. "Human", "Dwarf" — SRD species or free text
    appearance: str | None          # 1-3 sentence physical description
    role: str | None                # Narrative role: "Harbormaster", "Goblin Scout", etc.
    motivation: str | None          # What this NPC wants — informs Narrator behaviour
    disposition: Literal["friendly", "neutral", "hostile", "unknown"]

    # Mutable mechanical attributes — updated by Rules Engine after each relevant action
    hp_current: int | None          # None if NPC has never entered combat
    hp_max: int | None
    ac: int | None
    creature_type: str | None       # SRD creature type for mechanical lookups
    stat_block_ref: str | None      # Optional reference to SRD monster index

    # Metadata
    first_appeared_turn: int | None # Turn number of first appearance
    last_seen_turn: int | None      # Updated each turn the NPC is mentioned
    scene_location: str | None      # Current location — narrative, not coordinates
```

**Immutability rule**: `name`, `species`, and `appearance` are set at spawn and never
changed by the Narrator in subsequent turns. Changes to these fields require an explicit
campaign management action (player or GM via API), not a Narrator signal. This prevents
the harbormaster inconsistency by design — the Narrator can only read these fields, not
overwrite them.

**Mechanical attributes are optional**: An NPC that never enters combat does not need HP
or AC. These fields are populated on first combat involvement, either from the SRD monster
index (via `stat_block_ref`) or from Narrator-provided values at spawn.

### 2. NPC origin: predefined vs. narrator-spawned

**Predefined NPCs** are created via the campaign management API before or during campaign
setup. The campaign creation flow supports an optional NPC roster. Predefined NPCs have
`origin = "predefined"` and may carry full stat blocks, detailed motivations, and
mechanical attributes from the start.

The Context Builder includes all predefined NPCs relevant to the current scene in the
snapshot, regardless of whether they have appeared yet. This gives the Narrator access to
their canonical attributes before introducing them.

**Narrator-spawned NPCs** are created at runtime via the `npc_updates` field of the
`GMSignals` envelope (ADR-0012). When the Narrator introduces a new NPC that has no
existing record, it emits an `NPCUpdate` with `event = "spawn"` containing the NPC's
initial attributes. The server materialises the record before processing `scene_transition`.

Once spawned, a narrator-spawned NPC is treated identically to a predefined NPC from the
server's perspective. The `origin` field is informational only.

### 3. `NPCUpdate` schema

```python
@dataclass
class NPCUpdate:
    event: Literal["spawn", "status_change", "disposition_change", "location_change"]
    npc_id: str | None              # UUID for existing NPCs; None for spawns (server assigns)
    npc_name: str | None            # Required for spawn; used to match existing NPCs by name
                                    # if npc_id is not yet known to the Narrator
    reason: str                     # One sentence, logging only — never player-facing

    # Spawn-only fields (ignored for other events)
    species: str | None
    appearance: str | None
    role: str | None
    motivation: str | None
    disposition: Literal["friendly", "neutral", "hostile", "unknown"] | None
    hp_max: int | None
    ac: int | None
    stat_block_ref: str | None      # SRD monster index, e.g. "goblin", "bandit"

    # Status/disposition/location fields (used for non-spawn events)
    new_status: Literal["alive", "dead", "fled", "unknown"] | None
    new_disposition: Literal["friendly", "neutral", "hostile", "unknown"] | None
    new_location: str | None
```

**Name-based matching**: The Narrator does not have access to NPC UUIDs — it operates on
names. When referencing an existing NPC in `npc_updates`, the Narrator provides `npc_name`.
The server resolves `npc_name` to a UUID via a case-insensitive lookup within the campaign.
If no match is found and `event = "spawn"`, a new record is created. If no match is found
for a non-spawn event, it is logged as a Narrator error and the update is discarded.

**`stat_block_ref` resolution**: `stat_block_ref` is an index into the SRD data
layer — resolved via `srd_data.get_monster(index, campaign_id)`, which applies the
full three-tier lookup from ADR-0001 §3 (Campaign Override → Instance Library → SRD
Baseline). This means `stat_block_ref` can reference any of the following:

- A standard SRD creature from the 5e-database (e.g. `"goblin"`, `"bandit"`).
- A custom creature imported into the Instance Library by the player (e.g. `"mind-flayer"`,
  `"beholder"`) — covering non-SRD creatures from licensed sourcebooks.
- A campaign-specific override of a standard creature (e.g. an elite goblin variant with
  modified HP and a custom ability).

The Instance Library import mechanism is the existing `POST /api/srd/{collection}`
endpoint (ADR-0001 §2). ADR-0013 consumes it; it does not define it.

**Stat block precedence**: When `stat_block_ref` resolves to a record, the stat block
values are applied as defaults. Narrator-provided fields in the `NPCUpdate` (e.g.
`hp_max`, `ac`) override the stat block selectively — only the fields explicitly
provided by the Narrator are overridden; all other fields fall back to the stat block.
This allows the Narrator to spawn an "Elite Goblin" with `stat_block_ref = "goblin"`
and `hp_max = 18` without needing to reproduce the full stat block. If `stat_block_ref`
does not resolve to any record across all three tiers, Narrator-provided values are used
as-is and the absence is logged as a warning.

### 4. NPC state in the snapshot

The Context Builder includes NPC data in the state snapshot passed to the Narrator. NPC
inclusion is scene-scoped: only NPCs whose `scene_location` matches the current scene, or
whose `last_seen_turn` is within the last N turns, are included. NPCs with
`status = "dead"` or `status = "fled"` are excluded unless they are predefined NPCs with
plot significance (flagged by a `plot_significant: bool` field).

The NPC snapshot format is compact — name, role, disposition, status, and appearance are
included; full motivation and mechanical stats are omitted unless the session is in Combat
mode, in which case HP and AC are added for active combatants.

```
NPCs in scene:
- Harbormaster Vex (Human, Harbormaster) — neutral — "A broad-shouldered woman in her fifties with sun-weathered skin."
- Guard Aldric (Human, Harbour Guard) — hostile — "A young guard with a fresh wound on his sword arm."
```

This format is intentionally minimal. The Narrator does not need the full data model — it
needs enough to reference NPCs consistently. Mechanical detail is reserved for combat
context where it is actually needed.

### 5. NPC death and status transitions

NPC death can be signalled by two sources:

- **Rules Engine**: when an NPC's HP reaches 0 via damage resolution, the Engine sets
  `status = "dead"` directly. No `GMSignals` event is needed.
- **Narrator**: for narrative deaths (an NPC killed off-screen, an NPC that fled and is
  presumed dead) the Narrator emits `NPCUpdate(event="status_change", new_status="dead")`.

Engine-determined death takes precedence. If the Engine sets an NPC to `dead` and the
Narrator subsequently emits a `status_change` for the same NPC in the same turn, the
Engine value is retained and the Narrator update is discarded and logged.

The same dual-source pattern applies to `fled`: the Narrator signals narrative flight;
there is no Engine equivalent (fleeing is not a mechanical outcome in SRD 5.2.1 terms,
only a narrative one).

### 6. Campaign setup API

The campaign creation and management API gains an NPC roster endpoint:

```
POST   /api/campaigns/{id}/npcs          Create predefined NPC
GET    /api/campaigns/{id}/npcs          List all NPCs in campaign
GET    /api/campaigns/{id}/npcs/{npc_id} Get NPC
PATCH  /api/campaigns/{id}/npcs/{npc_id} Update NPC (immutable fields excluded)
```

`PATCH` accepts updates to mutable fields (`motivation`, `disposition`, `hp_current`,
`scene_location`, `status`) and to mechanical attributes. It explicitly rejects changes to
`name`, `species`, and `appearance` — these require a separate override endpoint that logs
the change as a campaign event.

## Rationale

**Persistent records over prompt-engineered consistency**: Instructing the Narrator to
maintain NPC consistency without a data source to read from is an unenforceable contract.
The Narrator has no memory between turns (ADR-0002). Any consistency constraint that
cannot be injected via the snapshot is aspirational, not architectural. Persistent records
are the only mechanism that actually solves the problem.

**Immutable core attributes over full mutability**: Allowing the Narrator to update `name`
and `appearance` via `npc_updates` would reintroduce the inconsistency problem through a
different path — the Narrator could simply overwrite its own previous descriptions. Locking
these fields forces consistency at the data layer. A player who wants to rename an NPC can
do so via the API; the Narrator cannot.

**Name-based NPC matching over UUID passing**: The Narrator operates on names, not
identifiers. Requiring the Narrator to produce UUIDs in `npc_updates` would either require
injecting a UUID-to-name mapping into every snapshot (cost: tokens) or would produce
frequent hallucinated UUIDs (cost: data integrity). Name-based matching within a campaign
is unambiguous for named NPCs. Collision (two NPCs with the same name) is prevented by
the spawn path: if a name already exists, no new record is created — the existing record
is referenced.

**Scene-scoped NPC snapshot over full roster**: Including all campaign NPCs in every
snapshot would grow the snapshot token cost linearly with campaign length. A campaign with
50 NPCs would add ~2,000 tokens to every request. Scene-scoping keeps the snapshot
bounded and ensures the Narrator receives contextually relevant NPCs, not an exhaustive
registry.

**`stat_block_ref` over full stat block in spawn**: Requiring the Narrator to produce a
complete stat block at spawn — all ability scores, all features, all actions — would
produce unreliable and inconsistent mechanical data. A reference index resolved via the
three-tier lookup (ADR-0001 §3) is more reliable: it uses authoritative SRD data for
standard creatures, player-imported data for licensed non-SRD creatures, and campaign
overrides for custom variants. Narrator-provided field overrides allow targeted
customisation (e.g. elite HP values) without full stat block reproduction. This design
reuses existing infrastructure rather than introducing a parallel import mechanism.

## Alternatives Considered

**NPC consistency via system prompt constraints only**: Instruct the Narrator to always use
the same name and description for recurring NPCs. Rejected because the Narrator has no
memory between turns — the constraint is unenforceable without a data source. The session
transcript that motivated this ADR was produced with a functioning system prompt; the
problem is architectural, not instructional.

**NPC records only for combat participants**: Create NPC records only when an NPC enters
combat, using their mechanical attributes as the primary reason for persistence. Rejected
because the consistency problem manifests in exploration before any combat occurs — the
harbormaster was inconsistent across dialogue turns with no combat involvement.

**Player-managed NPC roster only, no Narrator-spawned NPCs**: Require players to define
all NPCs in advance via the campaign API. Rejected because it eliminates the spontaneous
emergence that makes open-world tabletop RPGs compelling. A player should not need to
pre-define every harbour guard before a session.

**NPC state in `world_state` JSONB blob**: Store NPC data as unstructured JSON inside the
existing `CampaignState.world_state` field rather than in a dedicated table. Rejected
because: (1) it makes NPC queries impossible without full deserialization; (2) it provides
no schema validation; (3) it cannot support the immutability constraints on core
attributes; (4) it conflates NPC lifecycle with general world state, making both harder to
reason about.

## Consequences

### What becomes easier
- NPC consistency is enforced at the data layer. The Narrator reads names and appearances
  from the snapshot — it cannot introduce inconsistency by reinventing them.
- Pre-defined NPCs — dragons, recurring villains, quest-givers — can be fully authored
  before the first session with complete mechanical and narrative attributes.
- NPC state (alive, dead, fled, disposition changes) is auditable in the campaign history.
  Players can review how NPCs changed across sessions.
- Combat initialisation (ADR-0012) can reference NPC IDs from the database rather than
  relying on the Narrator to produce consistent identifiers.
- The snapshot's NPC section is bounded by scene scope, keeping token costs predictable
  as campaigns grow.

### What becomes harder
- The database schema gains a new `npcs` table. Every campaign operation that touches NPCs
  requires a JOIN or a separate query. The Context Builder's `build_snapshot()` gains
  complexity: it must now query NPCs by scene location and recency.
- The `GMSignals` parsing path in `api/turns.py` must handle NPC name resolution, stat
  block lookup, and record creation before processing `scene_transition`. This is
  non-trivial transactional logic: if NPC creation fails, the turn must not leave the
  database in a partial state.
- The Narrator's system prompt gains new instructions: how to reference existing NPCs (by
  name, consistently), when to emit spawn events (first appearance only), and which fields
  to populate. This increases system prompt complexity and must be validated against
  real session behaviour.
- Campaign setup gains a new UI surface (NPC roster). For the web client, this is a new
  page or modal. For the Discord bot, it is new slash commands.

### New constraints
- `name`, `species`, and `appearance` on an NPC record are immutable after creation. No
  code path — including the `PATCH /npcs/{id}` endpoint — may update these fields without
  logging a campaign event. This constraint must be enforced at the model layer, not only
  at the API layer.
- NPC creation from `npc_updates` must occur within the same database transaction as the
  turn record creation. Partial writes — turn persisted but NPC not created, or vice versa
  — are not acceptable.
- The Narrator must not emit `spawn` events for NPCs that already exist in the campaign.
  The server enforces this via name-based deduplication, but the system prompt must also
  instruct the Narrator to check the NPC snapshot before spawning. Duplicate spawn events
  are logged and discarded.
- NPC mechanical attributes (`hp_current`, `ac`) updated by the Rules Engine must use the
  same transaction pattern as character state updates (ADR-0004): atomic with the Turn
  record, never partial.
- The `plot_significant` flag on predefined NPCs must be set explicitly at campaign setup.
  It must not be inferred automatically — the system cannot reliably determine narrative
  significance without player input.

## Review Triggers

- If the name-based NPC matching produces frequent collisions (two distinct NPCs sharing a
  name within a campaign), evaluate adding a disambiguation suffix at spawn time (e.g.,
  "Guard" → "Guard (Harbour, Turn 3)") or requiring the Narrator to use more specific
  names when introducing characters.
- If the scene-scoped NPC snapshot consistently omits NPCs that the Narrator needs to
  reference (cross-scene continuity failures), evaluate expanding the recency window beyond
  the last N turns or adding an explicit "carry-forward" flag for NPCs the Narrator marks
  as narratively active.
- If Narrator-provided `hp_max` and `ac` at spawn are frequently incorrect or
  inconsistent for common creature types, evaluate making `stat_block_ref` mandatory for
  any NPC that could enter combat, with a validation step that rejects spawns without a
  valid SRD reference or explicit mechanical values.
- If the NPC roster campaign setup UI creates significant friction for players who want to
  run spontaneous sessions without pre-authoring NPCs, evaluate a "quick campaign" mode
  that defers all NPC definition to the Narrator and accepts the consistency trade-off
  explicitly.
- If the `npcs` table grows beyond 500 records per campaign (indicating very long or
  NPC-dense campaigns), evaluate archiving NPCs with `status = "dead"` that are not
  `plot_significant` into a cold-storage structure to keep active-NPC queries fast.