# ADR-0019: Exploration State Signals

- **Status**: Accepted
- **Date**: 2026-04-06
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/dm/gm_signals.py`, `backend/tavern/dm/context_builder.py`, `backend/tavern/dm/narrator.py` (system prompt), `backend/tavern/api/turns.py` (signal processing), `backend/tavern/models/` (CampaignState schema), database migration, web client, Discord bot
- **References**: ADR-0002 (Claude as Narrator — snapshot structure), ADR-0004 (Campaign and Session Lifecycle — `world_state` JSONB), ADR-0012 (GMSignals envelope and processing order), ADR-0013 (NPC Lifecycle — scene-scoped snapshot), ADR-0016 (World Object Persistence — scene-scoped snapshot), ADR-0017 (Scene Identifier Convention — normalisation, **§4 partially superseded by this ADR**)
- **Supersedes**: ADR-0017 §4 (Current scene tracking) — the `current_scene_id` field and write path described in ADR-0017 §4 were never implemented. This ADR defines the actual mechanism.

## Context

A playtest session exposed three categories of Narrator state coherence failures:

1. **Spatial state drift**: The player left a tavern and entered a shop. The Narrator
   described the transition, but on subsequent turns placed the player back in the tavern
   and addressed NPCs from the wrong location.

2. **NPC identity mutation**: The shopkeeper was described as three different people across
   three consecutive turns — a middle-aged woman, then a burly man, then an older man
   with one eye.

3. **NPC context bleed**: When the player addressed someone in the shop, the Narrator
   responded as a character from the tavern.

A diagnostic investigation confirmed a single architectural root cause: **there is no
mechanism in the GMSignals envelope for the Narrator to signal an exploration-mode
location change, and no code path to consume such a signal.**

The `SceneTransition` dataclass (ADR-0012) has four fields — `type` (limited to
`combat_start`, `combat_end`, `none`), `combatants`, `potential_surprised_characters`,
and `reason`. It is exclusively a combat mode transition signal. ADR-0017's Context
section references `SceneTransition.new_location` as an existing field, and ADR-0017 §4
describes `CampaignState.current_scene_id` as the storage mechanism — neither exists in
the implementation.

The actual location is stored as `CampaignState.world_state["location"]`, a JSONB key
written once at campaign creation and never updated thereafter. The Context Builder reads
this value on every turn to scope its NPC and world object queries. Because the value is
static, the queries always return entities from the opening location — regardless of
where the player has moved narratively.

The NPC spawn handler (`api/turns.py`) does not assign `scene_location` to newly spawned
NPCs from the current location. Spawned NPCs receive `scene_location = NULL` unless the
Narrator explicitly emits a separate `location_change` event — which it has no reason to
do, since the Narrator does not know the canonical location value (it reads a stale one
from the snapshot).

A secondary gap exists for time-of-day tracking. The Narrator describes time passing
narratively ("the sun sets", "hours pass"), but no structured state tracks the current
time period. Time of day is mechanically relevant in three ways: Long Rest / Short Rest
require specific durations (SRD 5.2.1), Darkvision is conditional on lighting, and
Forced March / Exhaustion rules reference elapsed travel time. A tabletop GM tracks time
intuitively; the Narrator has no equivalent mechanism.

Both gaps share the same structural problem: the Narrator describes state changes in
prose, but the GMSignals envelope lacks channels for exploration-mode state updates. This
ADR closes both gaps.

## Decision

### 1. Two new top-level fields on `GMSignals`

The `GMSignals` dataclass gains two new fields:

```python
@dataclass
class LocationChange:
    new_location: str               # Scene identifier (normalised via ADR-0017 §2)
    reason: str = ""                # One sentence, logging only — never player-facing

@dataclass
class TimeProgression:
    new_time_of_day: Literal[
        "dawn", "morning", "midday", "afternoon",
        "dusk", "evening", "night", "late_night"
    ]
    reason: str = ""                # One sentence, logging only — never player-facing

@dataclass
class GMSignals:
    scene_transition: SceneTransition       # ADR-0012 — unchanged
    npc_updates: list[NPCUpdate]            # ADR-0013 — unchanged
    suggested_actions: list[str]            # ADR-0015 — unchanged
    location_change: LocationChange | None  # NEW — exploration-mode location change
    time_progression: TimeProgression | None # NEW — time-of-day advancement
```

Both new fields are nullable. `None` means no change — the default on most turns. This
differs from `scene_transition` (which uses `type: "none"` as its default) and
`npc_updates` / `suggested_actions` (which use empty lists). The nullable pattern is
chosen because these signals are sparse: most turns involve neither a location change nor
a time change. A non-null value is the signal; absence is the default.

**Why not extend `SceneTransition`?** `SceneTransition` is a combat mode transition
signal. Its `type` enum (`combat_start`, `combat_end`, `none`) governs session mode
changes with mechanical consequences (initiative rolls, combatant tracking). Location
changes and time progression are exploration-mode events with no session mode change.
Overloading `SceneTransition` would conflate two independent state dimensions and
complicate the processing pipeline — the combat path would need to filter out
non-combat signals, and the exploration path would inherit combat-specific fields
(`combatants`, `potential_surprised_characters`) that are meaningless in context.

**Why not a generic `world_state_updates` field?** A key-value mechanism for arbitrary
state updates is flexible but unvalidatable. The Narrator could emit malformed keys,
conflicting values, or state updates the server does not know how to process. Location
and time are bounded, well-defined state dimensions with clear validation rules and
clear consumers (Context Builder, Rules Engine). They earn their own typed signals.

### 2. `current_scene_id` as a dedicated column on `CampaignState`

The party's current location is promoted from `world_state["location"]` (an untyped
JSONB key) to `CampaignState.current_scene_id` (a `TEXT` column):

```sql
ALTER TABLE campaign_state ADD COLUMN current_scene_id TEXT NOT NULL DEFAULT '';
ALTER TABLE campaign_state ADD COLUMN time_of_day TEXT NOT NULL DEFAULT 'morning';

-- Migration: populate from existing JSONB
UPDATE campaign_state
SET current_scene_id = normalise_scene_id(
    COALESCE(world_state->>'location', '')
);
```

`current_scene_id` stores a normalised scene identifier (ADR-0017 §1–§2). It is the
single source of truth for the party's current location. The JSONB key
`world_state["location"]` is deprecated and no longer read by any code path after
migration.

`time_of_day` stores the current time period as one of the eight enumerated values.
Default is `morning` — matching the typical campaign opening. The value is set at
campaign creation (from the Claude-generated brief, or defaulting to `morning`) and
updated via `TimeProgression` signals thereafter.

**Why a dedicated column instead of JSONB?** Three reasons: (1) The Context Builder's
NPC and world object queries filter by `current_scene_id` on every turn — a dedicated
column supports indexing and avoids JSONB path extraction in the hot query path.
(2) `current_scene_id` has a defined format (ADR-0017) and a `CHECK` constraint is
expressible on a column but not on a JSONB key. (3) The field's lifecycle is
write-on-every-location-change, read-on-every-turn — the same access pattern as
`rolling_summary` and `turn_count`, both of which are dedicated columns.

### 3. Server processing order

The processing order in `api/turns.py` after GMSignals parsing becomes:

```
1. npc_updates          — NPC records must exist before they can be scoped to a location
2. location_change      — NEW: update current_scene_id, assign scene_location to
                          newly spawned NPCs from step 1 that have scene_location = NULL
3. time_progression     — NEW: update time_of_day
4. scene_transition     — combat mode changes (may depend on location for combatant
                          scoping)
5. suggested_actions    — forward to clients (no server-side processing)
```

**`location_change` before `scene_transition`**: A Narrator response may both move the
party to a new location and initiate combat there (e.g., "You enter the throne room —
the dragon attacks"). The NPCs spawned in step 1 need `scene_location` assigned from
the new location in step 2, and the combat transition in step 4 needs the correct
`current_scene_id` to scope combatants.

**NPC `scene_location` auto-assignment on spawn**: When `location_change` is processed,
any NPCs spawned in step 1 that still have `scene_location = NULL` are assigned
`current_scene_id` as their `scene_location`. This eliminates the need for the Narrator
to emit a separate `location_change` event per NPC — spawned NPCs are assumed to be at
the party's current location unless the Narrator explicitly assigns them elsewhere.

### 4. Narrator system prompt additions

The system prompt gains two new instruction blocks:

**Location change instructions:**

```
When the party moves to a new location — entering a building, leaving a town, descending
into a dungeon, traveling to a new area — emit a location_change in your GMSignals block.

The new_location value must be a snake_case identifier: lowercase letters, digits, and
underscores only. Use the same identifier consistently for the same physical location.
Examples: "harborside_supply", "the_drowned_anchor", "dungeon_level_2".

Emit location_change only when the party's physical location changes. Do not emit it for
movement within the same location (walking across a tavern, moving to a different table).

If the party returns to a previously visited location, reuse the same identifier.
Your current location is shown in the Scene: field of your context — reference it if
you are unsure what identifier to use for the current location.
```

**Time progression instructions:**

```
When significant time passes in the narrative — hours of travel, waiting until nightfall,
a long rest, the passage of an afternoon — emit a time_progression in your GMSignals
block.

The new_time_of_day value must be one of exactly eight values:
  dawn, morning, midday, afternoon, dusk, evening, night, late_night

Your current time of day is shown in the Time: field of your context. Advance time
consistently: if it is currently morning and the party travels for several hours, the
new time should be midday or afternoon, not night.

Do not emit time_progression on every turn. Most turns occur within a single time period.
Emit it only when the narrative describes meaningful time passing.

Do not emit time_progression for Short Rests or Long Rests — those are mechanical events
handled by the Rules Engine. Only emit it for narrative time passage outside of rest
mechanics.
```

**Prompt token cost**: Both instruction blocks add approximately 180 tokens to the static
system prompt. At prompt caching pricing (0.1x rate on cache reads), this is negligible.
The output cost is bounded by the signal structure — at most ~30 additional tokens per
turn when both signals are emitted.

### 5. Snapshot format changes

The scene context block in the serialised snapshot gains the `Time:` field and the
`Scene:` field now reads from `current_scene_id` instead of `world_state["location"]`:

```
Scene: harborside_supply
Time: morning
Location description: A cramped shop on the waterfront, shelves laden with diving
  equipment and maritime supplies.

NPCs in scene:
- Shopkeeper Vara (Human, Maritime Supplier) — neutral — "A middle-aged woman with
  sun-darkened skin and keen eyes."
```

The `Scene:` and `Time:` fields are always present. The Narrator reads them to determine
its current context and to reference the correct identifier when emitting `location_change`
or `time_progression` signals.

### 6. WebSocket events

Two new optional WebSocket events:

```json
{
  "type": "turn.location_change",
  "payload": {
    "turn_id": "uuid",
    "campaign_id": "uuid",
    "new_location": "harborside_supply"
  }
}
```

```json
{
  "type": "turn.time_progression",
  "payload": {
    "turn_id": "uuid",
    "campaign_id": "uuid",
    "new_time_of_day": "afternoon"
  }
}
```

Both events are emitted after `turn.narrative_end`, in the same position as
`turn.suggested_actions`. They are informational — clients may use them to update UI
elements (location indicator, time-of-day display, ambient lighting changes) but are
not required to handle them.

Emission sequence:

```
turn.narrative_start
turn.narrative_chunk × N
turn.narrative_end
turn.location_change         ← NEW, only if location changed
turn.time_progression        ← NEW, only if time changed
turn.suggested_actions       ← existing
```

### 7. Relationship to ADR-0017

ADR-0017's normalisation rules (§1, §2, §3) are unchanged and apply fully to
`LocationChange.new_location`. The `normalise_scene_id()` function in `core/scene.py`
is called on `LocationChange.new_location` before writing to `current_scene_id`.

ADR-0017 §4 (Current scene tracking) described `CampaignState.current_scene_id` as a
field and showed NPC/world object queries using it. The field and queries described in
§4 were architecturally correct but never implemented — location was stored in
`world_state["location"]` (a JSONB key) and never updated after campaign creation. This
ADR implements what ADR-0017 §4 described, with one deviation: the field is `TEXT NOT
NULL DEFAULT ''` rather than `str` with no default, and the migration path handles
existing campaigns.

ADR-0017 §4 is superseded by this ADR's §2 and §3. All other sections of ADR-0017
remain in effect.

ADR-0017's Context section references `SceneTransition.new_location` — a field that was
never added to `SceneTransition` (ADR-0012). This ADR introduces `LocationChange` as a
separate signal type rather than extending `SceneTransition`, for the reasons stated in
§1. The ADR-0017 Context section's reference to `SceneTransition.new_location` is
acknowledged as describing intent that was fulfilled by a different design.

## Alternatives Considered

**Extend `SceneTransition` with `type: "location_change"` and a `new_location` field.**
Rejected because `SceneTransition` governs session mode changes (exploration ↔ combat)
with mechanical consequences. Location changes have no session mode impact. Overloading
the type enum would require every consumer of `SceneTransition` (combat initiation,
initiative rolling, combatant scoping) to filter out a case that is semantically
unrelated to their purpose. The processing order would become ambiguous: does a
`location_change` SceneTransition update `current_scene_id` before or after the combat
logic that reads it? Separate signals avoid the question.

**Keep location in `world_state` JSONB and add a write path.** Rejected for three reasons:
(1) The Context Builder's NPC and world object queries run on every turn and filter by
location — a JSONB path extraction (`world_state->>'location'`) in the `WHERE` clause is
less efficient than a column comparison and cannot be indexed without a generated column.
(2) JSONB keys have no schema enforcement — a typo in the key name (`"locaton"`) would
silently create a parallel state. (3) The existing `world_state` JSONB is documented
(ADR-0004) as semi-structured data for "NPC dispositions, quest flags, faction
relationships, environmental conditions" — party location is structured data with a
defined format and a defined consumer, not a semi-structured grab bag.

**Track time as a continuous clock (hours since campaign start).** Rejected because it
imposes a simulation fidelity that tabletop RPGs do not operate at. A GM says "a few
hours pass" without knowing whether that means 2 or 4. A continuous clock would force
the Narrator to commit to exact durations, creating false precision that would
accumulate error. The 8-value enum matches GM intuition: time periods are narrative
landmarks, not timestamps. The enum also bounds the state space — validation is a set
membership check, not a range comparison.

**Combine location and time into a single `scene_state` signal.** Rejected because
location and time change independently. The party can move without time passing (entering
an adjacent room) and time can pass without the party moving (waiting in a tavern until
nightfall). A combined signal would require the Narrator to emit both values when only
one changed, introducing unnecessary coupling and increasing the chance of stale-value
errors (emitting the current time when only location changed, but getting the current
time wrong).

**Narrator infers location from rolling summary only (no signal).** Rejected because this
is the current architecture, and it produced the failures that motivated this ADR. The
rolling summary preserves location mentions (the Haiku compression prompt explicitly
lists locations as preserved content), but the summary cannot update `current_scene_id`,
cannot scope the NPC query, and cannot scope the world object query. The summary is a
narrative aid for the Narrator, not a state management mechanism. Relying on it for
state management is an architectural category error.

## Consequences

### What becomes easier

- NPC consistency across location changes is enforced by the data layer. When the player
  enters Harborside Supply and the Narrator spawns a shopkeeper, the shopkeeper's
  `scene_location` is automatically set to `harborside_supply`. On the next turn, the
  Context Builder's NPC query returns the shopkeeper — not Korven from the tavern. The
  Narrator reads the shopkeeper's canonical appearance from the snapshot and cannot
  reinvent it.
- The snapshot's `Scene:` and `Time:` fields give the Narrator reliable context on every
  turn. The Narrator does not need to infer location from the rolling summary or guess
  the time of day.
- World object queries (ADR-0016) benefit immediately. Objects at `harborside_supply` are
  visible when the player is there, and objects at `the_drowned_anchor` are not —
  without any changes to the world object system.
- Time-of-day in the snapshot enables consistent environmental narration. If the snapshot
  says `night`, the Narrator describes darkness, torchlight, and stars — not sunshine.
  This consistency is currently impossible because time of day is not tracked.
- The observability layer (ADR-0018) gains two new pipeline steps (`location_change_apply`,
  `time_progression_apply`) that make location and time changes auditable in the turn
  event log.
- Future mechanics that depend on time of day (Darkvision relevance, rest eligibility,
  random encounter probability by time period) have a reliable state value to read.

### What becomes harder

- The Narrator's system prompt grows by ~180 tokens. The `location_change` and
  `time_progression` instruction blocks must survive future system prompt revisions. The
  system prompt is now the interface contract for five signal types (scene_transition,
  npc_updates, suggested_actions, location_change, time_progression) — changes to any
  one require regression testing against all five.
- The GMSignals parser gains two new fields to validate and two new nullable types to
  handle. The safe-default behaviour (treat `None` as no change) is simple, but the
  parser must distinguish between "field absent" (no change) and "field present but
  malformed" (log error, treat as no change).
- The processing pipeline in `api/turns.py` gains two new steps between `npc_updates` and
  `scene_transition`. The ordering is load-bearing (§3) and must be enforced by code
  structure.
- Campaign creation must set `current_scene_id` from the opening brief's location value,
  normalised via `normalise_scene_id()`. If the brief generator produces a location name
  that normalises to an empty string, campaign creation must handle the error.
- The database migration must populate `current_scene_id` for existing campaigns. For
  campaigns where `world_state["location"]` normalises to an empty string (or is absent),
  the migration should set `current_scene_id` to a fallback value (e.g., `"unknown"`).

### New constraints

- `current_scene_id` and `time_of_day` are written only by the signal processing pipeline
  in `api/turns.py`. No other code path — including the campaign management API — may
  update these values directly. This ensures that all location and time changes pass
  through normalisation, validation, and logging.
- `LocationChange.new_location` must be normalised via `normalise_scene_id()` (ADR-0017
  §2) before writing to `current_scene_id`. Normalisation failure (empty string, >64
  characters) causes the `location_change` signal to be discarded and logged — the turn
  is not aborted.
- `TimeProgression.new_time_of_day` must be one of the eight enumerated values. Any other
  value causes the `time_progression` signal to be discarded and logged.
- NPCs spawned via `npc_updates` on the same turn as a `location_change` are assigned
  `current_scene_id` (post-update) as their `scene_location` if they have
  `scene_location = NULL` after spawn processing. This assignment happens in step 2 of
  the processing pipeline (§3).
- The `Time:` instruction explicitly excludes rest mechanics from `time_progression`. Rest
  time advancement is handled by the Rules Engine when processing rest actions — the
  Rules Engine updates `time_of_day` directly based on rest duration. This avoids double
  time advancement (Narrator + Engine both advancing time for the same rest).
- Changes to the `GMSignals` schema are breaking changes per ADR-0012. This ADR constitutes
  a MINOR version bump. The system prompt and the `parse_gm_signals()` parser must be
  updated in the same PR.

## Review Triggers

- If `location_change` signals are emitted on fewer than 30% of turns where the Narrator's
  narrative text describes the party moving to a new location (assessed via manual audit
  of 50 turns), the system prompt instructions are insufficient. Evaluate adding explicit
  examples of when to emit vs. when not to emit, or adding a post-narration classifier
  that detects movement descriptions and warns when no `location_change` was emitted.

- If `time_progression` signals cause time-of-day to advance inconsistently (e.g., jumping
  from `morning` directly to `night` without intermediate steps, more than once per 20
  turns), evaluate adding a transition validation rule that rejects non-adjacent time
  jumps — or document that non-adjacent jumps are intentional (e.g., "you sleep through
  the day").

- If the 8-value time enum proves too coarse for gameplay (players need to distinguish
  "early morning" from "late morning" for mechanical purposes), evaluate expanding to a
  12-value or 16-value enum. The system prompt instruction and the `CHECK` constraint are
  the only surfaces that need updating.

- If NPC `scene_location` auto-assignment (§3, step 2) causes incorrect NPC placement
  (e.g., an NPC described as being in a different location than where the party moved to),
  evaluate requiring the Narrator to emit explicit `scene_location` on spawn events rather
  than relying on auto-assignment. This would increase system prompt complexity but
  eliminate false assumptions.

- If `world_state["location"]` is still read by any code path 3 months after this ADR is
  implemented, the deprecation is incomplete. Audit and remove the remaining read sites.