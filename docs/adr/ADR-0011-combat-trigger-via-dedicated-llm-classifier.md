# ADR-0011: Combat Trigger via Dedicated LLM Classifier

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/dm/` (new `combat_classifier.py`), `backend/tavern/api/turns.py`, `backend/tavern/core/action_analyzer.py`

## Context

ADR-0007 defines the `Exploration → Combat` state transition as a first-class concept in
Tavern's turn model. Once in combat mode, the Rules Engine owns initiative ordering, turn
sequencing, and timeout handling. The problem is that nothing currently decides *when* that
transition fires.

The existing `core/action_analyzer.py` classifies player actions into `ActionCategory` values
using keyword matching — no LLM dependency. It is designed for routing (should the Rules
Engine process this as an attack? a spell? a skill check?) but not for context-sensitive state
transition decisions. "I grab the cutlass" and "I slash at the harbormaster with the cutlass"
both contain weapon keywords, but only the second unambiguously initiates combat. Keyword
matching alone cannot distinguish them reliably.

The game session that motivated this ADR demonstrated the failure mode: a player attacked an
NPC with a weapon, wounded her, and called guards — the Narrator described all of it
vividly — but the system never transitioned to combat mode. No initiative was rolled. No turn
order was established. Combat resolution was entirely narrative, bypassing the Rules Engine.
This contradicts the core constraint from ADR-0001: mechanical outcomes are the Rules Engine's
domain, not Claude's.

The question this ADR answers: **who decides that combat has begun, and how?**

Three candidate owners exist:

1. **The Rules Engine (`action_analyzer.py`)** — deterministic, but cannot account for
   narrative context. "I draw my sword" is hostile in a tavern brawl, neutral in a
   weapon-inspection scene.

2. **The Narrator (inline signal)** — Claude embeds a structured marker (`[COMBAT_START]`)
   in the narration response. The server parses it. This conflates narrative generation with
   state control, making the Narrator's output a side-channel for mechanical state transitions.
   It also violates ADR-0001's principle: the mechanical consequence (mode transition +
   initiative roll) would be initiated by a Claude response, not by a deterministic component.

3. **A dedicated LLM classifier** — a separate, purpose-built call that asks only one
   question: "Does this action begin combat?" The classifier runs before narration, its
   output controls the server's state machine, and the Narrator receives the correct mode
   in its context.

Option 3 is the correct decomposition. Classifying narrative intent is genuinely an LLM
task — it requires reading action text in context. But that classification must be isolated
from narration so that each call has a single, auditable responsibility.

## Decision

### 1. A `CombatClassifier` module in the DM layer

A new module `dm/combat_classifier.py` is responsible for one task: given a player action and
the current game state, determine whether combat begins and who the combatants are.

The classifier is not part of the Rules Engine (`core/`). It uses an LLM and therefore
belongs in `dm/`. It is not part of the Narrator. It has no narration responsibility and
must not produce any player-facing text.

### 2. Call sequence within the turn lifecycle

The classifier runs **after** `action_analyzer` and **before** the Narrator call. The turn
lifecycle in `api/turns.py` becomes:

```
1. Receive player action
2. action_analyzer.analyze_action() → ActionAnalysis
3. [If session in Exploration mode]
   combat_classifier.classify(action, snapshot) → CombatClassification
   If combat_classification.combat_starts:
       Transition session to Combat mode
       rules_engine.roll_initiative(participants) → initiative_order
       Persist initiative order and mode transition
4. rules_engine.resolve(action, action_analysis) → RulesResult
5. context_builder.build_snapshot(..., mode=current_mode) → StateSnapshot
6. narrator.narrate(snapshot) → narrative
7. Persist turn, broadcast narrative
```

The classifier is only invoked when the session is in `Exploration` mode. In `Combat` mode,
the turn model (ADR-0007) already controls action flow — no classification is needed.

### 3. Classifier interface

```python
@dataclass
class CombatClassification:
    combat_starts: bool
    combatants: list[str]   # NPC IDs or names present in the scene
    confidence: Literal["high", "low"]
    reason: str             # One sentence, for logging only — never player-facing

class CombatClassifier:
    async def classify(
        self,
        action_text: str,
        snapshot: StateSnapshot,
    ) -> CombatClassification: ...
```

`combatants` contains only NPCs — player characters are always included in combat when it
starts. The `reason` field is logged for debugging and observable misclassification analysis;
it is never sent to any client.

### 4. Classifier prompt design

The classifier call is tightly scoped:

- **Model**: Haiku. The decision is binary with structured output. Sonnet-class reasoning is
  not required and would add unnecessary latency and cost.
- **System prompt**: One paragraph. States the task explicitly: classify whether the player
  action initiates combat. Lists what constitutes combat initiation: a direct attack on a
  creature, casting a harmful spell at a creature, or an action that makes peaceful resolution
  immediately impossible. Lists what does not: drawing a weapon without attacking, threatening
  dialogue, observing a hostile creature.
- **Output format**: JSON only. No preamble, no explanation in the response body. The
  classifier system prompt must instruct the model to return only a JSON object matching the
  `CombatClassification` schema.
- **Input**: The player's action text (verbatim) + current scene context from the snapshot
  (present NPCs, location, active threats). No rolling summary, no character stats. The
  classifier does not need campaign history — it needs only the immediate scene.
- **Token budget**: Input ~300 tokens, output ~80 tokens. Latency target: <500ms.

### 5. `confidence` field and handling

The `confidence` field is `"high"` when the action unambiguously initiates or does not
initiate combat. It is `"low"` when the action is genuinely ambiguous (e.g., "I shove the
guard"). `"low"` confidence does not block the decision — the classifier still returns
`combat_starts: true` or `false`. It flags the turn for logging and for misclassification
rate monitoring per the Review Triggers below.

No player-facing behaviour changes based on `confidence`. It is an observability signal.

### 6. Relationship to ADR-0001

ADR-0001 prohibits Claude from deciding mechanical outcomes. The combat classifier decides
a **state transition condition**, not a mechanical outcome. The mechanical consequences of
the transition — initiative rolls, turn ordering, damage resolution — are entirely executed
by the Rules Engine after the classifier returns. The classifier answers "does this
situation qualify as combat?" The Rules Engine answers "what are the mechanical results?"

This is the same division of labour as a human Game Master who calls "roll initiative" at
the table. The GM recognises the fiction has reached combat; the dice and the rules resolve
what happens.

### 7. NPC-initiated combat

Player actions are not the only combat trigger. An NPC ambush, a trap, or a plot event can
initiate combat without a player action being the cause. These cases are handled by the
Narrator via a structured output field in the narration response — specifically, a
`scene_transition` field that the server reads after the Narrator call completes.

This is the one case where the Narrator signals a state transition. It is architecturally
acceptable because NPC-initiated combat has no preceding player action — there is no
classifier input to provide. The Narrator's `scene_transition` signal is explicit, narrow,
and documented in ADR-0002's system prompt constraints as the only permitted mechanical
signal the Narrator may emit.

NPC-initiated combat via `scene_transition` is out of scope for this ADR. It requires a
separate decision about the `scene_transition` output schema and is deferred to ADR-0012.

## Rationale

**Dedicated classifier over inline Narrator signal**: Embedding a `[COMBAT_START]` marker in
the Narrator's free-text response creates a parsing dependency on Claude's output format.
Claude can and will occasionally omit the marker, embed it mid-sentence, or produce it when
combat should not start. A dedicated call with a JSON-only system prompt is auditable,
testable, and has a single failure mode (wrong JSON) rather than a combinatorial space of
format violations.

**Dedicated classifier over `action_analyzer` extension**: `action_analyzer` is keyword-based
by design (ADR-0001 §1: "Deterministic Rules Engine in Python"). Extending it to handle
contextual combat detection would require either hardcoding elaborate heuristics — which
fail on natural language variation — or introducing an LLM dependency into `core/`, which
violates the Rules Engine's no-LLM constraint. The DM layer is the correct home for any
component that requires LLM judgment.

**Haiku over Sonnet for the classifier**: The classifier's task is binary classification with
structured output. It does not require extended reasoning, creative generation, or complex
inference chains. Haiku handles this class of task reliably. Using Sonnet would add ~1-2
seconds of additional latency per turn in exploration mode with no quality benefit.

**Classifier before Narrator, not after**: If the Narrator runs first, it produces narration
assuming a mode that the system has not yet transitioned into. The Narrator would narrate
combat without the combat context (initiative order, turn structure) present in the snapshot.
The classifier must run before narration so that the snapshot passed to the Narrator reflects
the actual game mode.

**`combatants` list as classifier output**: The Rules Engine needs to know which NPCs to
include in initiative. This information exists in the scene context that the classifier
already receives. Extracting it in the classifier call avoids a second LLM call or a
heuristic NPC-extraction step downstream.

## Alternatives Considered

**Extend `action_analyzer` with hostility detection**: Add an `INITIATES_COMBAT` category to
the existing keyword classifier. Rejected because keyword matching cannot handle natural
language ambiguity at acceptable accuracy. "I approach the guard menacingly" does not
contain attack keywords but may initiate combat. "I draw my sword to show him" does contain
weapon keywords but does not. A keyword classifier for this problem would require a
rule set as complex as an LLM prompt, with worse coverage and no observability into why a
given classification was made.

**Embed `[COMBAT_START: npc_a, npc_b]` in Narrator response**: Claude produces narration and
signals combat start in the same response. Rejected for three reasons: (1) it makes the
Narrator's output a side-channel for state machine control, which entangles the two
responsibilities; (2) the server would parse structured data out of a free-text stream,
creating a brittle dependency on Claude's output format; (3) it violates the principle from
ADR-0001 that mechanical state transitions are not Claude's domain. A signal that triggers
initiative rolls is a mechanical state transition.

**Player-confirmed combat**: After a potentially hostile action, the server sends the player
a confirmation prompt ("Combat has started — is that your intent?"). Rejected because it
breaks narrative immersion, adds a round-trip before every combat initiation, and creates
ambiguity about what happens to the action if the player says no. Tabletop GMs do not ask
players to confirm intent after they say "I attack the guard."

**Threshold-based escalation**: Track a per-NPC "hostility score" that increments on
threatening actions and triggers combat at a threshold. Rejected because the threshold would
need to be campaign-dependent, NPC-dependent, and narrative-context-dependent — effectively
re-inventing LLM judgment in a brittle heuristic form. It also makes combat initiation
probabilistic and non-transparent to the player.

## Consequences

### What becomes easier
- Combat always begins with an initiative roll. The turn model from ADR-0007 applies
  immediately and deterministically once the classifier fires.
- The Narrator always receives the correct game mode in its snapshot. Narration in
  exploration vs. combat mode can be tuned independently via the system prompt.
- Misclassification is auditable: `CombatClassification.reason` and `confidence` are logged
  per turn. If the classifier repeatedly misclassifies a pattern of action (e.g., "I
  shove"), the system prompt can be updated without touching any other component.
- The classifier is independently testable: given an action text and a snapshot fixture,
  assert that `combat_starts` matches expected. No Narrator, no Rules Engine needed.

### What becomes harder
- Every player action in Exploration mode now requires two LLM calls before narration:
  the classifier and the Narrator. The classifier adds ~300-500ms of latency per turn in
  exploration. This is acceptable — exploration turns are not time-pressured — but it is
  a real cost.
- The classifier is a new component to maintain. Its system prompt is a contract: changes
  must be tested against the misclassification baseline before deployment.
- NPC-initiated combat is explicitly deferred. Until ADR-0012 is written and implemented,
  there is no mechanism for an NPC ambush to trigger the combat mode transition. The
  Narrator will describe the ambush narratively without the Rules Engine taking over.

### New constraints
- The classifier must be invoked exclusively in `api/turns.py`, within the turn lifecycle,
  before the Narrator call. No other component may call the classifier directly.
- The classifier system prompt is part of the system's mechanical contract. Changes to it
  require a MINOR version bump (per CONTRIBUTING.md versioning rules) and must be accompanied
  by a regression test run against the misclassification baseline.
- `dm/combat_classifier.py` must have no dependency on `core/`. It may read from the
  snapshot (which is assembled by the Context Builder from core data) but must not import
  or call Rules Engine functions directly.
- The classifier JSON output must be validated against the `CombatClassification` schema
  before use. A malformed response must be treated as `combat_starts: false` with
  `confidence: "low"` and logged as a classifier error — never as an unhandled exception
  that aborts the turn.

## Review Triggers

- If misclassification rate (tracked via logged `confidence: "low"` turns and manual
  review) exceeds 10% of exploration turns over any 100-session sample, revisit the
  classifier system prompt before considering architectural changes.
- If classifier latency consistently exceeds 800ms (p95), evaluate parallelising the
  classifier call with the `action_analyzer` step, which is currently sequential.
- If the `combatants` list extracted by the classifier is frequently incorrect (missing
  NPCs, hallucinated NPCs), evaluate moving combatant extraction to a post-classification
  Rules Engine step that reads NPC IDs from the scene snapshot directly rather than relying
  on the classifier to name them.
- If NPC-initiated combat (deferred to ADR-0012) proves difficult to implement cleanly via
  the `scene_transition` Narrator signal, revisit whether the classifier should also handle
  NPC-turn evaluation — accepting the cost of running the classifier on NPC turns.
- If a future provider abstraction (ADR-0002 §7) makes the Haiku/Sonnet distinction
  provider-specific, evaluate whether the classifier should use the provider's dedicated
  classification endpoint (if one exists) rather than a chat completion call.