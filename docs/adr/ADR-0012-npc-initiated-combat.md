# ADR-0012: NPC-Initiated Combat via Narrator `GMSignals` Envelope

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/dm/narrator.py`, `backend/tavern/dm/context_builder.py`, `backend/tavern/api/turns.py`, `backend/tavern/api/ws.py`

## Context

ADR-0011 defines the `CombatClassifier` — a dedicated LLM call that detects when a
**player action** initiates combat. That covers one of two combat initiation paths.

The second path has no player action as a trigger: an NPC ambushes the party, a scripted
encounter fires at a plot threshold, a previously neutral creature turns hostile mid-scene.
In these cases there is no player input to classify. The Narrator, processing the scene
after a player's non-combat action (or after an NPC turn), determines that the fiction has
reached a state that requires combat mechanics to take over.

This creates a structural asymmetry. ADR-0011's classifier runs *before* narration, with
the player action as its input. NPC-initiated combat has no pre-narration trigger point —
the Narrator is the component that recognises and communicates the transition. The question
this ADR answers is: **how does the Narrator signal an NPC-initiated combat transition, and
what does the server do with that signal?**

Two design constraints shape the solution space:

**The Narrator streams.** Narrative responses are delivered token-by-token via WebSocket
(ADR-0002 §6). A signal embedded in the stream would require the server to parse the stream
in real time, interrupt it mid-delivery, and branch into combat initialisation before the
Narrator has finished. This is complex, fragile, and creates a race condition between the
streaming pipeline and the state machine.

**The Narrator must not own mechanical outcomes.** ADR-0001 is unambiguous: Claude decides
narrative, the Rules Engine decides mechanics. A combat initiation produces immediate
mechanical consequences — initiative rolls, turn ordering, combatant registration. These
cannot be triggered by a free-text signal embedded in a narrative response. They must be
triggered by a structured, post-narration handoff that the server processes deterministically.

**The Narrator will need to signal more than combat transitions.** ADR-0013 defines NPC
lifecycle events — spawns, state changes, deaths — that the Narrator must also communicate
structurally. A design that hardcodes only combat signals into the post-stream block would
require a schema change the moment NPC lifecycle support is added. The post-stream block is
therefore designed as a general-purpose `GMSignals` envelope from the start.

## Decision

### 1. The Narrator returns a `GMSignals` envelope alongside narrative text

The Narrator's API call returns two distinct outputs:

- **Narrative text**: the player-facing prose, streamed token-by-token as today.
- **`GMSignals`**: a structured JSON envelope, returned in a separate, non-streamed block
  after the stream completes. It carries all structured signals the Narrator needs to
  communicate to the server in a single post-stream payload.

The envelope always contains both top-level fields, always present, never null:

```python
@dataclass
class SceneTransition:
    type: Literal["combat_start", "combat_end", "none"]
    combatants: list[str]                        # NPC IDs entering combat; empty if type != "combat_start"
    potential_surprised_characters: list[str]    # Character IDs possibly unaware — Engine resolves final Surprise
    reason: str                                  # One sentence, logging only — never player-facing

@dataclass
class GMSignals:
    scene_transition: SceneTransition            # Always present; type="none" when no transition
    npc_updates: list[NPCUpdate]                 # Always present; empty list when no NPC lifecycle events
```

`NPCUpdate` is defined in ADR-0013. `GMSignals` is the stable envelope; its fields expand
as new signal types are introduced in subsequent ADRs without changing the delimiter or
parsing infrastructure.

### 2. Narrator call structure: two-phase response

The Narrator call produces both outputs in a single API call:

```
Phase 1 (streamed):     Narrative text — delivered token-by-token to clients
Phase 2 (non-streamed): GMSignals JSON — buffered after stream completion, never forwarded to clients
```

The Narrator's system prompt instructs Claude to produce narrative prose followed by a
clearly delimited JSON block. The server's streaming handler delivers all content before
the delimiter to clients; content after the delimiter is buffered, parsed as `GMSignals`,
and never forwarded to clients.

The delimiter is a fixed reserved string. Default (no signals):

```
---GM_SIGNALS---
{"scene_transition": {"type": "none", "combatants": [], "potential_surprised_characters": [], "reason": ""}, "npc_updates": []}
```

Combat initiation example:

```
---GM_SIGNALS---
{"scene_transition": {"type": "combat_start", "combatants": ["goblin_a", "goblin_b"], "potential_surprised_characters": ["char_uuid_1"], "reason": "Goblins spring from concealment as the party rounds the corner."}, "npc_updates": []}
```

The server validates the full envelope against the `GMSignals` schema. A malformed or
absent block is treated as a no-op `GMSignals` (both fields at safe defaults) and logged
as a Narrator format error. This fallback is safe — it causes missed signals, not
corrupted state.

### 3. Server processing sequence for NPC-initiated combat

After the Narrator stream completes and `GMSignals` is parsed:

```
1. Narrator stream completes → clients have received full narrative
2. Server parses GMSignals envelope
3. Process npc_updates first (ADR-0013) — NPC records must exist in the
   database before they can be referenced as combatants in scene_transition
4. If scene_transition.type == "combat_start":
   a. Transition session to Combat mode
   b. rules_engine.roll_initiative(
          player_characters=all_active_pcs,
          npcs=scene_transition.combatants,
          potential_surprised=scene_transition.potential_surprised_characters
      ) → InitiativeResult
   c. Persist initiative order, combat mode, and combatant list
   d. Broadcast "combat.started" WebSocket event with initiative order and
      any confirmed Surprised characters
5. Persist turn (narrative + GMSignals) as normal
```

`npc_updates` is processed before `scene_transition` because a Narrator-spawned NPC
(ADR-0013) must exist in the database before it can be referenced in `combatants`. This
ordering is mandatory and must be enforced in `api/turns.py`.

The player-facing sequence is: full narrative prose → NPC records materialised →
mechanical resolution → initiative broadcast. The fiction precedes the mechanics.

### 4. Scope: NPC turns vs. player turns, and combat end

The `GMSignals` envelope applies to every Narrator call regardless of context:

- **After a player action in Exploration mode**: `scene_transition` handles the case where
  the NPC *reaction* to a non-combat player action initiates combat (e.g., player fails a
  Deception check and the guard attacks). ADR-0011's `CombatClassifier` handles the case
  where the player action *itself* initiates combat — both mechanisms can fire on the same
  turn without conflict; the Classifier runs first and sets the mode before narration.

- **After an NPC turn in Combat mode**: `scene_transition.type = "combat_end"` signals
  that the fiction has resolved through a **narrative condition** — flight, surrender,
  environmental collapse, plot intervention. This is the Narrator's path for combat end.

  A second, independent `combat_end` path exists for **engine-determined termination**:
  after every damage application in `core/combat.py`, the Rules Engine checks whether all
  NPC combatants are at 0 HP, or whether all PCs are at 0 HP / unconscious. If either
  condition is true, the Engine signals `combat_end` directly — no Narrator call, no
  `GMSignals`. The Narrator is then invoked separately to narrate the outcome.

  Both paths produce the same server-side effect: Combat mode → Exploration mode,
  combatant list cleared, initiative order discarded. If both fire on the same turn,
  the Engine signal takes precedence (see New Constraints).

### 5. What this ADR does not decide

**Surprise resolution mechanics**: How the Rules Engine determines final Surprise status
from `potential_surprised_characters` is deferred to a dedicated ADR. This ADR only
specifies that the Narrator provides candidates and the Engine resolves them.

**NPC lifecycle signals (`npc_updates`)**: Defined entirely in ADR-0013. This ADR
establishes the envelope that carries them.

**Scripted/plot-triggered encounters without a Narrator call**: Server-side timers or world
events that trigger combat directly are out of scope. Those are direct Engine calls.

## Rationale

**`GMSignals` envelope over single-purpose `scene_transition` block**: A post-stream block
carrying only combat signals would require a schema change and delimiter rename the moment
NPC lifecycle support (ADR-0013) is added. The envelope costs nothing at the parsing layer
— the server deserialises one JSON object regardless of how many fields it carries — and
avoids a breaking change to the Narrator's output contract within weeks of its introduction.

**Post-stream signal over in-stream marker**: Parsing a marker mid-stream requires the
server to scan each chunk and branch execution while the streaming pipeline is still
running. This creates a race condition between client delivery and state machine transition.
Post-stream parsing is sequential, deterministic, and does not affect streaming latency.

**Delimiter-based extraction over two calls**: Two separate calls — one for narration, one
for signals — double API calls per turn with no structural benefit. Both require the same
context. Tool use was considered and rejected to preserve provider abstraction (ADR-0002
§7).

**Narrator as authority for NPC-initiated combat over a post-narration classifier**: A
classifier that reads the Narrator's own output to detect whether combat started is
redundant indirection. The Narrator already has full scene context and is better placed to
make the determination directly.

**`npc_updates` processed before `scene_transition`**: A Narrator-spawned NPC must exist
as a database record before it can appear in `combatants`. Reversing the order would
produce a foreign-key violation or silent data loss. The ordering is load-bearing, not
conventional.

## Alternatives Considered

**Embed `[COMBAT_START: goblin_a, goblin_b]` in the narrative stream**: Rejected because
(1) it requires real-time stream parsing with mid-stream branching; (2) the marker can
appear in narrative prose without being a signal; (3) it entangles the streaming delivery
path with state machine control.

**Second classifier call after narration**: Rejected because it adds a full LLM call to
every turn regardless of whether a transition occurs. Redundant when the Narrator can
declare the transition directly.

**Separate narration and signals calls**: Rejected because it doubles API calls per turn.
Both calls require identical context. The delimiter approach achieves the same separation
within a single call.

**Server-side heuristics on narrative text**: Rejected for the same reason as extending
`action_analyzer` for player-initiated combat (ADR-0011). Keyword heuristics on narrative
prose are unreliable — the Narrator describes combat in flavour text throughout exploration
mode.

## Consequences

### What becomes easier
- NPC ambushes, scripted encounters, and NPC reactions all follow the same server-side
  processing path as player-initiated combat (ADR-0011). The `combat.started` WebSocket
  event is emitted identically in both cases; clients require no new handling.
- The `GMSignals` envelope absorbs future structured signal types (NPC lifecycle, weather
  events, plot flags) without changing the delimiter, the parsing infrastructure, or the
  streaming handler.
- The fiction-before-mechanics sequence is encoded in the architecture, not dependent on
  implementation discipline.
- `reason` fields make Narrator decisions auditable in logs without exposing internal
  reasoning to players.

### What becomes harder
- The Narrator's system prompt gains a mandatory structural constraint: every response must
  terminate with a `---GM_SIGNALS---` block. This must survive all future system prompt
  revisions. Omission silently degrades to safe defaults — but causes missed signals.
- The streaming handler in `api/turns.py` must buffer the tail of the stream to detect the
  delimiter. This adds a small memory cost and implementation complexity.
- Narrator output evaluation and logging must strip the `GMSignals` block before assessing
  narrative quality. Any pipeline treating Narrator output as pure prose will include the
  JSON block unless explicitly filtered.

### New constraints
- `---GM_SIGNALS---` is a reserved string. It must not appear in any system prompt text,
  character name, location name, or narrative content. This must be documented in the
  Narrator system prompt design notes.
- `GMSignals` JSON must be validated against schema before use. Validation failure is a
  logged error defaulting to safe no-op values — never an unhandled exception.
- `npc_updates` must be processed before `scene_transition` in `api/turns.py`. This
  ordering is mandatory and must be enforced by code structure, not convention.
- The `potential_surprised_characters` list must contain only character IDs present in the
  current scene snapshot. IDs not present are silently dropped and logged.
- If Engine-determined `combat_end` and Narrator-determined `combat_end` fire on the same
  turn, the Engine signal takes precedence. The Narrator's `scene_transition` is discarded
  and logged. This rule must be enforced in `api/turns.py`.
- Changes to the `GMSignals` schema are breaking changes to the Narrator's output contract
  and require a MINOR version bump and system prompt update in the same PR.

## Review Triggers

- If delimiter-based extraction produces parse failures on more than 5% of turns containing
  non-empty signals, evaluate whether the system prompt constraint is being followed
  reliably or whether the delimiter string creates ambiguity in specific narrative contexts.
- If the fiction-before-mechanics sequence consistently produces player confusion —
  ambush description appearing before the initiative screen — evaluate emitting a
  `combat.pending` WebSocket event immediately after `GMSignals` is parsed, before
  initiative rolls complete.
- If scripted plot-triggered encounters bypassing the Narrator become a common pattern,
  evaluate standardising a server-side `combat_start` path in a follow-up ADR.
- If the Narrator-determined `combat_end` path proves unreliable — Narrator fails to emit
  the signal when fiction clearly warrants it — evaluate tightening the system prompt with
  explicit examples before considering architectural changes.