# ADR-0015: Narrator-Generated Suggested Actions

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/dm/gm_signals.py`, `backend/tavern/dm/narrator.py`, `backend/tavern/api/turns.py`, `backend/tavern/api/ws.py`, `frontend/src/` (web client), `backend/tavern/discord_bot/cogs/gameplay.py`

## Context

Tavern's current turn lifecycle ends at narration: the player reads Claude's response and
types a free-text action into an empty input field. This works for experienced players who
know their character's capabilities and can improvise action phrasing. It is a significant
barrier for everyone else.

A human Game Master naturally suggests options as part of narration — not as a rigid menu,
but as organic narrative prompts: "The door is ajar — you could slip through quietly, or
announce yourself loudly enough to draw out whoever is inside. What do you do?" This
guidance does not constrain the player; it surfaces possibilities the player might not have
considered and reduces the cognitive load of "what can I even do right now?"

The web client shows this gap plainly. After a rich narrative response — an NPC fleeing
with guards approaching, an open door, time pressure — the input reads "What do you do?"
and nothing else. Players with limited 5e knowledge stall here. The question is how to
bridge that gap without reducing the game to a fixed choice tree.

Two structural constraints define the design space:

**Suggestions must be narratively contextual, not mechanically enumerated.** A list of
"Attack / Cast Spell / Dash / Disengage" is a UI failure — it breaks immersion and
provides no more guidance than the SRD itself. Suggestions that emerge from the scene
("Slip through the side door", "Throw the lantern at the barrels", "Demand she stand
down") are useful precisely because they are specific to the moment.

**Suggestions must not constrain the player.** They are prompts, not options. A player
who ignores all suggestions and types something unexpected should experience no friction —
the suggestions disappear the moment the player begins typing. The Narrator already knows
how to handle unexpected player behaviour; that is its primary function.

**Suggestions are client-facing, not server-processed.** Unlike `GMSignals` fields such as
`scene_transition` and `npc_updates`, suggested actions carry no mechanical consequences.
The server does not act on them; it forwards them to clients. Clients decide how to render
them. This makes suggestions a presentation feature with a narrow API contract.

**The `GMSignals` envelope is the correct delivery mechanism.** ADR-0012 established
`GMSignals` as the general-purpose structured output channel from the Narrator. Its design
explicitly anticipates future signal types without requiring changes to the delimiter or
parsing infrastructure. `suggested_actions` is the first expansion of that envelope beyond
combat and NPC lifecycle signals.

## Decision

### 1. `suggested_actions` field added to `GMSignals`

The `GMSignals` dataclass gains a third top-level field:

```python
@dataclass
class GMSignals:
    scene_transition: SceneTransition       # ADR-0012 — unchanged
    npc_updates: list[NPCUpdate]            # ADR-0013 — unchanged
    suggested_actions: list[str]            # NEW — 0–3 narrative action suggestions
```

`suggested_actions` is always present in the envelope. Empty list when the Narrator
produces no suggestions. Maximum 3 items. Each item is a plain-text action phrase — no
formatting, no mechanical annotation.

**Cardinality constraint**: 0 to 3 suggestions per turn. The Narrator may omit suggestions
entirely (empty list) when the scene does not warrant them — mid-combat turns where the
situation speaks for itself, turns immediately after a major revelation where player
reflection is the natural response, or turns where all plausible actions are obvious.
The system prompt instructs the Narrator to omit suggestions rather than generate filler.

**Format constraint**: Each suggestion is a first-person action phrase, 5–12 words,
present tense. Examples: "Slip through the gap before the guards arrive", "Demand the
harbormaster explain herself", "Throw your cloak over the lantern and run". No mechanical
labels ("Cast Fireball"), no parenthetical annotations ("(uses a spell slot)"), no
numbered prefixes.

### 2. Narrator system prompt additions

The Narrator's system prompt gains a new instruction section governing `suggested_actions`
in the `GMSignals` block:

- Produce 0–3 action suggestions per turn. The default is 2; omit entirely only when the
  scene makes suggestions unnecessary or intrusive.
- Suggestions must be grounded in the specific scene: location, NPCs present, objects
  described in narration, and the character's established capabilities.
- Suggestions must not assume mechanical outcomes ("Attack the guard and roll high"). They
  describe intent, not resolution.
- At least one suggestion should represent a non-combat option when combat is not already
  underway. This prevents suggestions from tunnelling the player into violence.
- The third suggestion, when present, should be unexpected — something creative or oblique
  that the player is unlikely to have thought of independently. This is the highest-value
  suggestion; it demonstrates the Narrator's scene awareness.
- Suggestions are for the player whose turn it is. In multiplayer, the Narrator receives
  the acting character's identity in the snapshot; suggestions are scoped accordingly.

**Prompt token cost**: The suggestions instruction section adds approximately 120 tokens
to the static system prompt. At Anthropic's prompt caching pricing, this cost is
negligible on cached reads (0.1x rate). The output cost is bounded by the 3-suggestion
limit: at ~10 words per suggestion, the `GMSignals` block grows by at most ~30 tokens
of output per turn.

### 3. Server processing: forward, do not interpret

After `GMSignals` is parsed from the Narrator response, the server processes fields in
mandatory order (ADR-0012 §3): `npc_updates` first, `scene_transition` second. The new
`suggested_actions` field is processed last and requires no server-side logic beyond
validation and forwarding.

The processing rule: if `suggested_actions` is a non-empty list and each item is a
non-empty string, emit a `turn.suggested_actions` WebSocket event. If validation fails
(malformed field, items exceeding character limits), log the failure, emit no event, and
continue — this is a display feature, not a mechanical one. A missed suggestion is
invisible to gameplay; a raised exception is not.

### 4. New WebSocket event: `turn.suggested_actions`

A new event is added to the WebSocket protocol (extending ADR-0005 §3 and ADR-0009 §10):

```json
{
  "event": "turn.suggested_actions",
  "campaign_id": "uuid",
  "payload": {
    "turn_id": "uuid",
    "character_id": "uuid",
    "suggestions": ["Slip through the side door", "Demand she stand down", "Throw the lantern at the barrels"]
  }
}
```

`character_id` identifies which character the suggestions are intended for. In multiplayer,
all clients receive the event, but only the client belonging to `character_id` should
render the suggestions as interactive. Other clients may render them read-only (showing
the acting player's options) or suppress them entirely — client discretion.

The event is emitted after `turn.narrative_end`. The sequence for a turn with suggestions:

```
turn.narrative_start
turn.narrative_chunk × N
turn.narrative_end
turn.suggested_actions     ← new, always after narrative_end
```

Clients that do not handle `turn.suggested_actions` are unaffected — the event is
additive and the existing turn flow is unchanged.

### 5. Web client rendering

The web client renders suggestions as clickable chips below the narrative response,
above the free-text input field. Clicking a chip populates the input field with the
suggestion text. The player may submit the pre-populated text directly or edit it before
submitting — the chip is a shortcut into the text field, not a submit button.

Chips disappear when the player begins typing in the input field (input `onFocus` or
`onChange`). This preserves the primacy of free-text input; suggestions are scaffolding
that vanishes when not needed.

Chips are displayed only to the active player. In multiplayer, other players see the
suggestions in a read-only style (greyed, non-interactive) to maintain transparency
about what options were surfaced.

The character sheet overlay (a separate client concern) does not interact with suggestion
chips. Suggestions are scoped to the narrative input area.

### 6. Discord bot rendering

The Discord bot appends suggestions as numbered quick-reply buttons on the narrative
embed after `turn.narrative_end`. Buttons are labelled with the suggestion text,
truncated at 80 characters if necessary to fit Discord's button label limit.

Clicking a button submits the suggestion as the player's action — equivalent to typing
the text and invoking `/action`. Unlike the web client, Discord buttons are one-click
submit (no edit-before-send step), because Discord's UX does not support a prefill
pattern. The button label must therefore be precise enough to stand alone as a submitted
action.

If the player types `/action <text>` while suggestion buttons are visible, the buttons
are dismissed (Discord message edit to remove components) after the action is submitted.
This prevents stale buttons from lingering after a player has already acted.

Suggestions are displayed only to the active player in combat (the player whose turn it
is). In exploration mode (concurrent input), suggestions are displayed to all connected
players as buttons — any player may use them.

### 7. Character sheet overlay (web client)

This ADR also governs the decision to add a character sheet overlay to the web client,
which is architecturally related: the overlay surfaces the same character state that
informs the Narrator's suggestions, and the two features together solve the player
guidance problem.

The overlay is triggered by clicking the character card in the sidebar. It renders as a
modal panel over the gameplay view. It reads exclusively from state already delivered to
the client via `session.state` on connect and `character.updated` events — no new API
endpoint is required.

The overlay renders:

- **Ability scores and modifiers** — all six, with passive Perception derived from WIS
- **Saving throw proficiencies** — which saves the character is proficient in
- **Skills** — all SRD skills with modifier and proficiency indicator
- **Combat stats** — HP (current/max), AC, Speed, Initiative modifier
- **Spell slots** — by level, current/max (only for spellcasting classes)
- **Prepared spells / spells known** — name, level, school, and damage expression
  where applicable (e.g. "Fireball — 3rd level — 8d6 fire")
- **Class features and racial traits** — as a flat list with short descriptions
- **Equipment** — carried items with relevant mechanical notation (weapon damage, armor AC)
- **Conditions** — active conditions with a one-line mechanical summary

The overlay is read-only. No in-overlay editing. Character state changes (long rest,
spell slot consumption) happen through gameplay actions and are reflected via
`character.updated` events, not through overlay interaction.

## Rationale

**Narrator-generated suggestions over Rules Engine enumeration**: The Rules Engine knows
which actions are mechanically legal; it cannot know which actions are narratively
interesting given the current scene. A rule-derived list ("You may: Attack, Dash, Disengage,
Cast Spell, Use Item") is a menu of action types, not a menu of actions. The Narrator
has full scene context — NPC behaviour, environmental details, narrative momentum — and
produces suggestions that are specific, immediate, and dramatically coherent. This is the
same judgment a human GM applies when they say "you could try to bluff your way past the
guard."

**`GMSignals` extension over a separate output channel**: The delimiter-and-JSON
architecture from ADR-0012 already handles structured post-stream output from the Narrator.
Introducing a second delimiter or a separate API call for suggestions would duplicate
infrastructure that exists precisely to absorb this kind of extension. Adding
`suggested_actions` to `GMSignals` costs one field in a dataclass and one instruction
section in the system prompt.

**Forward-only server processing over server interpretation**: The server has no basis for
evaluating whether a suggestion is good, contextually appropriate, or mechanically valid.
Attempting to filter or rank suggestions server-side would require either LLM judgment
(a third call per turn) or heuristics that are less capable than the Narrator that produced
the suggestions. The correct pattern is: Narrator produces, server validates schema, client
renders.

**Chip-to-text-field pattern over direct submit (web)**: Suggestions are prompts, not
commands. A player clicking "Slip through the side door" should be able to see that text
in the input and refine it to "I slip through the side door and press myself against the
wall, listening." Direct-submit removes that step. The chip pattern preserves it.
Discord's direct-submit is an acceptable tradeoff given the platform's UX constraints.

**3-suggestion maximum over an uncapped list**: More than 3 suggestions creates a
paradox-of-choice problem and begins to resemble a menu, which is the failure mode we are
avoiding. Three is enough to represent meaningfully different approaches (e.g. aggressive,
cautious, unexpected) without overwhelming the player. The Narrator's system prompt
instructs it to prefer fewer, better suggestions over more, generic ones.

**Overlay reads existing state over new API endpoint**: All character data required for
the overlay is already present in the client's local state after `session.state` on
connect and subsequent `character.updated` events. Adding an endpoint to serve the same
data creates a redundant code path, additional load, and a caching concern. The client
already owns this data.

## Alternatives Considered

**Separate Haiku call for suggestions (parallel to Narrator)**: Run a dedicated Haiku
call concurrent with the Narrator to generate suggestions, similar to the CombatClassifier
pattern from ADR-0011. Rejected because: (1) it adds a second LLM call to every turn,
increasing both cost and latency regardless of whether suggestions are actually useful;
(2) the Haiku call would require the same scene context as the Narrator — same snapshot,
same NPC data — duplicating the Context Builder invocation or creating a coupling between
the two calls; (3) the Narrator already has full scene context and is better positioned
to produce contextually grounded suggestions than a parallel call that may not have
completed narration as input.

**Suggestions embedded inline in narrative prose**: The Narrator ends narration with
"You could: (a) slip through the door, (b) demand answers, or (c) run." Rejected because
(1) it couples the suggestion format to the narrative voice, forcing Claude to produce
structured content within prose; (2) client extraction requires parsing narrative text,
re-introducing the brittleness that ADR-0002's plain-text principle was designed to avoid;
(3) it cannot be suppressed per client — a TTS client would read the options aloud as if
they were narrative.

**Fixed suggestion templates populated by Rules Engine**: Generate suggestions from
action-type templates filled with character-specific data: "Attack {nearest_enemy} with
{equipped_weapon}", "Cast {highest_damage_spell}", "Move to {nearest_cover}". Rejected
because: (1) the result is a mechanical menu regardless of template format; (2) template
coverage must grow with every new action type, class feature, and environmental category;
(3) "nearest cover" is not a concept the Rules Engine tracks; (4) the approach produces
the same failure mode as direct Rules Engine enumeration — contextually blind options.

**Player-configurable suggestion verbosity (off/minimal/full)**: Allow players to disable
or reduce suggestions via campaign settings. Deferred, not rejected. The default behaviour
(0–3 suggestions, collapsing on input focus) is already low-friction for experienced
players. A campaign-level `suggestions_enabled: bool` setting is a reasonable future
addition if playtesting reveals that experienced players find suggestions distracting even
with the auto-collapse behaviour.

## Consequences

### What becomes easier
- New players and casual players have a concrete foothold on every turn. The blank input
  field problem disappears without constraining experienced players.
- The `GMSignals` envelope absorbs the addition cleanly. No new delimiter, no new parsing
  infrastructure, no new Narrator call.
- Clients are decoupled: the web client's chip pattern and Discord's button pattern are
  independent rendering decisions. A CLI client could print suggestions as numbered lines.
  A TTS client could suppress them entirely.
- The Narrator's suggestion output is auditable in logs alongside `scene_transition` and
  `npc_updates`. If suggestions are consistently unhelpful, this is visible in session
  logs without additional instrumentation.

### What becomes harder
- The Narrator's system prompt grows. The `suggested_actions` instruction section adds
  ~120 tokens and must survive future system prompt revisions without being accidentally
  abbreviated. System prompt changes that affect the `GMSignals` block format require
  regression testing against suggestion output.
- The `turn.suggested_actions` event adds a case to every client's WebSocket event
  handler. Clients that do not yet handle this event are unaffected now, but accumulating
  unhandled events increases maintenance surface over time.
- Discord button state management is non-trivial: buttons must be dismissed after the
  player acts, and in exploration mode all players' buttons must be dismissed after any
  player acts. This requires the Discord bot to track active suggestion message IDs per
  campaign.

### New constraints
- `suggested_actions` items must be non-empty strings. An item that is an empty string
  or whitespace-only is treated as a parse failure and the entire suggestions list is
  discarded (logged, not raised).
- Maximum 3 items. Items beyond index 2 are silently dropped and logged. The Narrator
  system prompt enforces this; the server enforces it as a hard cap regardless.
- Each suggestion item must be 200 characters or fewer. Items exceeding this limit are
  dropped individually; remaining items are forwarded.
- `turn.suggested_actions` must be emitted after `turn.narrative_end`, never before.
  The GMSignals block is not available until the stream completes. This ordering is
  guaranteed by the existing streaming pipeline and must not be changed.
- Changes to the `suggested_actions` schema within `GMSignals` are breaking changes to
  the Narrator's output contract and require a MINOR version bump and system prompt
  update in the same PR (per ADR-0012's constraint on GMSignals schema changes).

## Review Triggers

- If suggestions are accepted (chip clicked / button pressed) on fewer than 15% of turns
  across a representative sample of sessions, evaluate whether the Narrator's suggestion
  quality is too generic or whether the auto-collapse UX is causing players to dismiss
  chips before reading them.
- If suggestions are accepted on more than 70% of turns, evaluate whether the feature is
  reducing player agency — players may be following suggestions instead of expressing
  genuine intent.
- If the Narrator produces malformed `suggested_actions` (empty strings, format
  violations, items exceeding the length limit) on more than 3% of turns, tighten the
  system prompt with explicit negative examples before considering schema changes.
- If Discord button dismissal after player action proves unreliable (stale buttons
  persisting), evaluate replacing component-edit dismissal with message expiry (Discord
  ephemeral messages or timed component disable).
- If playtesting reveals that experienced players find suggestions distracting, evaluate
  a campaign-level `suggestions_enabled` flag as a configuration option.