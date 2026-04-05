# ADR-0017: Scene Identifier Convention

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/dm/` (Context Builder, GMSignals), database schema (`npcs.scene_location`, `world_objects.scene_location`), `backend/tavern/core/` (Rules Engine scene queries), `backend/tavern/api/` (SceneTransition handling)
- **References**: ADR-0002 (Claude as Narrator — scene context in snapshot), ADR-0013 (NPC Lifecycle — `scene_location` field), ADR-0016 (World Object Persistence — `world_objects.scene_location`)

## Context

Scene location is a shared key across multiple data models and system components in
Tavern. It appears as:

- `npcs.scene_location` — determines which NPCs appear in the Narrator snapshot
- `world_objects.scene_location` — determines which world objects appear in the snapshot
  (ADR-0016)
- `SceneTransition.new_location` in GMSignals — the Narrator's signal for scene changes
- The Context Builder's scene-scoping queries — used to filter both NPCs and world objects
  for the current scene

None of these usages share a formal definition. `scene_location` is documented as a
"narrative, not coordinates" free-text string in ADR-0013, but no format, casing,
character set, or validation rule is specified. The Narrator produces scene identifiers
via GMSignals; the server stores and queries them as-is. This creates a concrete failure
mode: if the Narrator emits `"Guard Room B"` on one turn and `"guard_room_b"` on the
next, an NPC or world object written with the first value is invisible to the snapshot
query using the second. The mismatch is silent — no error is raised, objects simply
disappear from the Narrator's view.

This is not a hypothetical risk. LLMs produce inconsistent casing and spacing without
explicit constraints. The system prompt can instruct the Narrator to use a specific
format, but instruction compliance is probabilistic. The authoritative fix is server-side
normalisation at write time, combined with a defined canonical format that both the
Narrator's system prompt and the server enforce.

ADR-0013 deferred this definition; ADR-0016 added a second consumer of the same
undefined convention and explicitly flagged the dependency. This ADR closes the gap.

## Decision

### 1. Canonical scene identifier format

A scene identifier is a `snake_case` ASCII string with the following rules:

- **Characters**: lowercase letters (`a–z`), digits (`0–9`), and underscores (`_`).
  No spaces, hyphens, dots, slashes, or Unicode.
- **Length**: 1–64 characters.
- **Structure**: free-form within the above constraints. No required prefix, suffix, or
  hierarchy separator. Examples: `town_square`, `guard_room_b`, `dungeon_level_2_entrance`,
  `tavern_common_room`.
- **Uniqueness scope**: scene identifiers are unique within a campaign, not globally.
  The same identifier may appear in different campaigns without conflict.

Valid examples:
```
town_square
guard_room_b
dungeon_level_2_entrance
tavern_common_room
crypt_of_the_ancient_king
room_17
```

Invalid examples:
```
Guard Room B          ← uppercase, spaces
guard-room-b          ← hyphens
dungeon/level_2       ← slash
große_halle           ← non-ASCII
                      ← empty string
a_very_long_scene_identifier_that_exceeds_the_maximum_allowed_length_of_64_characters
```

### 2. Server-side normalisation at write time

The server normalises all incoming scene identifiers before writing to the database.
Normalisation is applied at every point where a scene identifier enters the system:

- `SceneTransition.new_location` in GMSignals processing (`api/turns.py`)
- `NPCUpdate.new_location` in GMSignals processing (`api/turns.py`)
- `world_object_spawn.scene_location` in GMSignals processing (`api/turns.py`)
- Campaign management API: predefined NPC `scene_location` on creation and update
- Campaign management API: world object `scene_location` on GM-created objects

Normalisation function (defined once in `core/scene.py`, used everywhere):

```python
import re

def normalise_scene_id(raw: str) -> str:
    """
    Normalise a scene identifier to canonical snake_case.
    Raises ValueError if the result is empty or exceeds 64 characters.
    """
    normalised = raw.strip().lower()
    normalised = re.sub(r'[\s\-]+', '_', normalised)   # spaces and hyphens → underscore
    normalised = re.sub(r'[^a-z0-9_]', '', normalised)  # strip all other non-conforming chars
    normalised = re.sub(r'_+', '_', normalised)          # collapse consecutive underscores
    normalised = normalised.strip('_')                   # strip leading/trailing underscores

    if not normalised:
        raise ValueError(f"Scene identifier '{raw}' normalises to an empty string.")
    if len(normalised) > 64:
        raise ValueError(
            f"Scene identifier '{raw}' normalises to '{normalised}' ({len(normalised)} chars), "
            f"exceeding the 64-character limit."
        )
    return normalised
```

This means the Narrator can emit `"Guard Room B"` and the server stores `"guard_room_b"`.
Subsequent emissions of `"guard_room_b"` or `"Guard Room B"` resolve to the same
identifier. The normalisation is idempotent — applying it to an already-canonical
identifier is a no-op.

**ValueError handling**: If normalisation produces an empty string or exceeds 64
characters, the containing GMSignals event is rejected and logged as a Narrator error.
The turn is not aborted — only the malformed event is discarded, identically to the
handling of malformed GMSignals in ADR-0013.

### 3. Narrator system prompt constraint

The Narrator's system prompt includes an explicit instruction for scene identifier format:

```
When emitting scene_location values in GMSignals, use lowercase snake_case identifiers:
letters, digits, and underscores only. No spaces, no hyphens. Examples:
  "town_square", "guard_room_b", "dungeon_entrance".
Use the same identifier consistently for the same physical location throughout the
campaign. If you are unsure of a location's identifier, use the value from the most
recent scene_location you received in the snapshot.
```

The system prompt instruction and the server-side normalisation are complementary. The
instruction reduces inconsistency from the source; the normalisation eliminates residual
inconsistency before it reaches the database. Neither alone is sufficient: instruction
compliance is probabilistic; normalisation without instruction allows arbitrary input that
may be ambiguous (e.g. `"guard_room"` vs. `"guard_room_b"` are two distinct locations
after normalisation, not variants of the same one).

### 4. Current scene tracking

The active scene for a session is stored in `CampaignState` as `current_scene_id: str`,
normalised at write time. The Context Builder reads `current_scene_id` when building
snapshot queries:

```python
# NPCs in scene
npcs = await db.execute(
    select(NPC).where(
        NPC.campaign_id == campaign_id,
        or_(
            NPC.scene_location == state.current_scene_id,
            NPC.last_seen_turn >= (current_turn - RECENCY_WINDOW)
        )
    )
)

# World objects in scene
world_objects = await db.execute(
    select(WorldObject).where(
        WorldObject.campaign_id == campaign_id,
        WorldObject.scene_location == state.current_scene_id,
        WorldObject.status.notin_(['destroyed'])
    )
)
```

Both queries use exact string equality against the normalised `current_scene_id`. Because
all stored values are normalised, the match is reliable.

### 5. Scene identifier in the snapshot

The active scene identifier is surfaced in the Narrator snapshot as part of the scene
context block, so the Narrator can reference it when emitting GMSignals:

```
Scene: guard_room_b
Location description: A stone guardroom with a heavy oak door to the north and an iron
portcullis to the east. Weapon racks line the south wall.
```

Including the canonical identifier in the snapshot gives the Narrator a ground-truth
reference to echo back in its signals, reducing the frequency of normalisation-required
corrections.

## Rationale

**`snake_case` over free-text with case-insensitive comparison:**
Case-insensitive comparison (`ILIKE` in PostgreSQL, or `lower()` on both sides) would
tolerate `"Guard Room B"` vs. `"guard_room_b"` without normalisation. Rejected because
it addresses only the casing problem, not the space/hyphen problem — `"guard room b"` and
`"guard_room_b"` differ after lowercasing. A normalisation step is needed regardless;
if normalisation is already applied, case-insensitive comparison adds complexity without
benefit. The canonical format is simpler to reason about and test.

**`snake_case` over `kebab-case`:**
Both are valid lowercase identifier formats. `snake_case` is consistent with Python
naming conventions used throughout the codebase, and with the existing SRD data index
format in the 5e-database (`"longsword"`, `"goblin"`, `"fireball"`). Using the same
convention reduces cognitive load.

**`snake_case` over hierarchical paths (`dungeon/level_2/guard_room_b`):**
Hierarchical paths were considered for future campaign map support — a path encodes
nesting relationships (dungeon → level → room). Rejected for this ADR because: (1) no
map or spatial feature exists or is planned in the current roadmap; (2) slash characters
in identifiers complicate URL routing and JSONB key usage; (3) hierarchy can be expressed
in a flat identifier when needed (`dungeon_level_2_guard_room_b`) without introducing a
separator with special semantics. If spatial/hierarchical scene navigation is added, a
superseding ADR should address the format change.

**Server-side normalisation over prompt-only enforcement:**
Relying solely on the Narrator's system prompt to produce canonical identifiers is
insufficient — LLM output is probabilistic, and a single formatting deviation silently
corrupts scene-scoped queries. Server-side normalisation is deterministic and
unconditional. The prompt instruction remains valuable as a first line of defence (it
reduces the frequency of normalisation-required corrections and keeps the Narrator's
self-referencing consistent), but the server is the authority.

**64-character limit over unlimited length:**
Unlimited identifiers allow degenerate cases (`"the_dimly_lit_guard_room_on_the_second_
level_of_the_dungeon_of_the_ancient_lich_king"`). 64 characters accommodates any
reasonable scene name while keeping database index size bounded and snapshot rendering
predictable.

## Alternatives Considered

**UUID-based scene identifiers assigned by the server:**
Assign a UUID to each scene when first referenced; the Narrator uses the UUID in
subsequent GMSignals. Rejected because UUIDs are opaque — the Narrator would need to
receive and echo back a server-assigned UUID before the scene has any persistence, adding
a round-trip or requiring the Narrator to invent identifiers that the server later
confirms. Name-based identifiers are self-describing and allow the Narrator to reference
locations it has not yet visited without prior server registration.

**Campaign-defined scene registry (explicit scene list):**
Require the GM to pre-register all scenes before a campaign session. Rejected for the
same reason as player-managed NPC roster in ADR-0013: it eliminates emergent world
creation. The Narrator should be able to introduce a new location spontaneously; the
server persists it on first reference. A scene registry would be appropriate for a
campaign with a fixed map, and could be added as an optional feature in a future ADR.

**Free-text with no normalisation, relying on rolling summary for continuity:**
Accept that the Narrator may use inconsistent identifiers and rely on the rolling summary
to maintain narrative coherence. Rejected because the failure mode is data corruption,
not just narrative inconsistency: NPCs and world objects are silently excluded from
snapshots when their `scene_location` does not match the current scene identifier. This
produces narrator hallucination of object availability — the exact problem ADR-0016 was
written to solve.

**Case-insensitive database collation:**
Configure PostgreSQL to use a case-insensitive collation for `scene_location` columns.
Rejected because it handles only casing, not the space/hyphen/punctuation problem. It
also makes the column behaviour non-standard and surprising to contributors who expect
`TEXT` columns to use byte-for-byte comparison.

## Consequences

### What becomes easier
- Scene-scoped snapshot queries for NPCs and world objects are exact-match string
  comparisons against a normalised column value. No `ILIKE`, no `lower()`, no
  case-handling logic in query code.
- The Narrator receives its own scene identifier in the snapshot, giving it a reliable
  reference for GMSignals. Self-referencing is accurate without requiring the Narrator to
  remember what it emitted in a prior turn.
- Scene identifier bugs are detectable in logs: normalisation errors and collisions
  produce log entries at known points in the processing pipeline.
- The convention is consistent with Python naming and SRD data index formats already
  present in the codebase.

### What becomes harder
- `normalise_scene_id()` must be called at every entry point where a scene identifier is
  written. Missing a call site silently re-introduces the inconsistency problem. The
  function must be tested and its usage enforced in code review.
- The 64-character limit will occasionally require GMs or the Narrator to use abbreviated
  identifiers for very long location names. This is a minor usability cost.
- The system prompt gains an additional constraint block. Prompt length grows marginally;
  the constraint must be validated against real Narrator output to confirm compliance rate.

### New constraints
- `core/scene.py` is the single definition of `normalise_scene_id()`. No inline
  normalisation is permitted elsewhere. All scene identifier writes are routed through
  this function.
- `npcs.scene_location` and `world_objects.scene_location` columns in PostgreSQL must
  store only normalised values. A database constraint (`CHECK` or application-enforced
  invariant) should be added to detect violations during testing.
- The Narrator system prompt is a breaking change surface: any edit to the scene
  identifier instruction must be treated as a snapshot format change per ADR-0002 §3.
- Future ADRs that introduce new models with a `scene_location` field must reference
  ADR-0017 and apply `normalise_scene_id()` at all write paths.

## Review Trigger

- If scene identifier collisions (two distinct physical locations normalising to the same
  identifier within a campaign) occur more than once per 10 sessions in practice, evaluate
  adding a campaign-scoped scene registry that makes collisions detectable at spawn time.
- If the 64-character limit produces user-facing friction (GMs reporting that their
  location names are being rejected or truncated), raise the limit to 128 characters. No
  other part of the system is sensitive to this value.
- If hierarchical scene navigation (campaign map, room-graph traversal) is added to the
  roadmap, evaluate a superseding ADR that introduces a path-based identifier format and
  a migration strategy for existing flat identifiers.
- If `normalise_scene_id()` call sites proliferate beyond 10 distinct locations in the
  codebase, evaluate moving normalisation to the SQLAlchemy model layer (a `@validates`
  decorator on `scene_location` columns) to enforce it at the ORM boundary rather than
  requiring explicit call sites.