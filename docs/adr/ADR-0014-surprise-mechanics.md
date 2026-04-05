# ADR-0014: Surprise Mechanics — Determination, Resolution, and First-Round Constraints

- **Status**: Accepted
- **Date**: 2026-04-05
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/core/combat.py`, `backend/tavern/api/turns.py`, database schema (combat participants)

## Context

ADR-0012 establishes that the Narrator provides a `potential_surprised_characters` list
when signalling NPC-initiated combat. ADR-0013 establishes the same for predefined
encounters. Neither ADR defines what happens with that list — who resolves the actual
Surprise determination, how, and what mechanical constraints apply to surprised characters
in the first combat round.

This ADR closes that gap.

**What Surprise is in SRD 5.2.1:**

Surprise is not a condition in the technical sense. It has no duration, no stacking, no
explicit removal trigger, and does not appear in the conditions list. In SRD 5.2.1, its
sole mechanical consequence is Disadvantage on the surprised combatant's Initiative roll.
There is no action restriction, no loss of Bonus Action or Reaction. This differs
significantly from the 2014 ruleset (SRD 5.1), where surprised characters could not act
during their first turn. Tavern implements the 5.2.1 rule.

Determination occurs once, before the initiative roll: each potentially surprised
character's passive Perception (10 + Perception modifier) is compared against the Stealth
check of the concealing party. The comparison is per-character — one member of the party
may be surprised while another is not.

**Two distinct flows produce Surprise:**

**NPC-initiated ambush**: The NPCs have already been stealthy — their approach is the
narrative reason the Narrator signalled `potential_surprised_characters`. There is no prior
interactive roll for the NPCs. The Rules Engine must resolve the NPC Stealth check
autonomously using the NPC's Stealth modifier from their stat block.

**Player-initiated ambush**: The players have attempted to sneak up on NPCs. One or more
players have already made Stealth checks interactively (ADR-0009). Those results are
already resolved and stored. The Rules Engine compares them against the NPCs' passive
Perception values.

These two flows share the same comparison logic — Stealth result vs. passive Perception
— but differ in where the Stealth value comes from. The architecture must handle both
without special-casing the turn lifecycle.

## Decision

### 1. Surprise as an initiative modifier, not a first-round action restriction

**SRD 5.2.1 Surprise rule**: A surprised combatant rolls Initiative with Disadvantage.
That is the complete mechanical consequence. There is no action restriction, no loss of
Bonus Action or Reaction, and no first-round constraint beyond the initiative roll itself.
This is a significant change from the 2014 ruleset (5e SRD 5.1), where surprised
characters could not act during their first turn. ADR-0014 implements the 5.2.1 rule
exclusively.

Surprise is stored as a `surprised` boolean on the `CombatParticipant` record. It is set
once during combat initialisation, used exactly once — when rolling initiative — and never
consulted again.

```python
@dataclass
class CombatParticipant:
    character_id: str               # PC UUID or NPC UUID
    participant_type: Literal["pc", "npc"]
    initiative_roll: int            # Raw d20 result (rolled with Disadvantage if surprised)
    initiative_result: int          # Final initiative value (roll + DEX modifier)
    surprised: bool                 # Used only during initiative rolling; ignored thereafter
    acted_this_round: bool          # Reset at start of each round
```

The `surprised` flag has no effect after initiative is resolved. It is retained on the
record for logging and audit purposes — the Narrator receives the surprised list in the
combat initialisation snapshot (§5) — but the turn lifecycle in `api/turns.py` never
reads it after initiative is established.

### 2. Surprise determination: two flows, one comparison function

The Rules Engine exposes a single comparison function in `core/combat.py`:

```python
def determine_surprise(
    potential_surprised: list[str],          # Character IDs from Narrator (ADR-0012) or
                                             # from prior Stealth check context (ADR-0009)
    stealth_results: dict[str, int],         # character_id → Stealth check result
                                             # for the concealing party
    snapshot: StateSnapshot,
) -> dict[str, bool]:                        # character_id → surprised
```

The function compares each potentially surprised character's passive Perception against
the highest Stealth result among the concealing party. Per SRD 5.2.1: if the highest
Stealth check of the concealing side exceeds a character's passive Perception, that
character is surprised.

"Highest Stealth of the concealing party" is the correct SRD interpretation — a group
Stealth check uses the lowest result, but for Surprise determination the relevant value is
whether any concealing character succeeded against each target's Perception individually.
The Rules Engine implements the RAW (Rules As Written) interpretation: each concealing
character's Stealth is compared independently against each potential target's passive
Perception; a target is surprised if *all* concealing characters beat their passive
Perception (i.e. none were detected).

**Flow A — NPC-initiated ambush:**

The Narrator signals `potential_surprised_characters = [pc_uuid_1, pc_uuid_2]`. No prior
Stealth rolls exist for the NPCs. The Engine autonomously rolls Stealth for each ambushing
NPC using their stat block's Stealth modifier (DEX modifier + proficiency if proficient,
per SRD). These rolls use the standard deterministic RNG from `core/dice.py` and are
logged as part of the turn record. `determine_surprise` is then called with these
auto-rolled results.

```
NPC Stealth rolls (auto):
  Goblin A: d20(11) + 2 = 13
  Goblin B: d20(4)  + 2 = 6

PC passive Perceptions:
  Kael: 10 + 1 = 11  → Goblin B (6) did not beat 11 → Kael NOT surprised
  Mira: 10 + 0 = 10  → Goblin B (6) did not beat 10 → Mira NOT surprised
```

In this example, Goblin B's poor roll means neither PC is surprised — one concealer
failing to stay hidden alerts the targets. This is the correct SRD interpretation.

**Flow B — Player-initiated ambush:**

Players have made interactive Stealth checks (ADR-0009) before combat begins. Their
results are already stored in the turn record. The CombatClassifier (ADR-0011) fires,
determines combat starts, and passes the existing Stealth results directly into
`determine_surprise` as `stealth_results`. No new rolls are needed.

### 3. Trigger conditions for Surprise determination

`determine_surprise` is called only when `potential_surprised_characters` is non-empty.
The list is populated by three distinct paths, each with a defined source:

**Path A — NPC-initiated ambush (Narrator-sourced)**: The Narrator populates
`potential_surprised_characters` in the `GMSignals` envelope (ADR-0012) when it
determines that NPCs have approached undetected. This is a narrative judgement — the
Narrator's system prompt instructs it to set this field when the fiction describes an
ambush, a hidden attacker striking first, or any situation where one or more player
characters are plausibly unaware that combat is beginning. The Narrator sets the field;
the Engine resolves whether each candidate is actually surprised via Stealth vs. passive
Perception comparison.

**Path B — Player-initiated ambush (prior Stealth roll-sourced)**: When a player has
made a Stealth check before combat begins (via the interactive roll system, ADR-0009),
the result is stored in the preceding turn record. When the CombatClassifier (ADR-0011)
subsequently determines that combat starts, it passes the Stealth roll results from the
turn record to `determine_surprise` as `stealth_results`. The `potential_surprised_characters`
list in this path is populated by the server from the NPC roster of the current scene —
all scene-present NPCs are candidates; `determine_surprise` then filters them by comparing
against the Stealth results.

The CombatClassifier must be given access to Stealth roll results from the current turn
context. The `TurnContext` passed to the Classifier must include any `stealth_rolls`
present in the turn record. If no Stealth rolls are present, `potential_surprised_characters`
is empty and `determine_surprise` is skipped.

**Path C — Neither side is stealthy (no Surprise)**: If neither the Narrator signals
`potential_surprised_characters` nor any prior Stealth rolls exist in the turn context,
the list is empty. `determine_surprise` is not called. No participant rolls initiative
with Disadvantage. This covers standard open encounters where both sides notice each
other simultaneously — the common case.

These three paths are mutually exclusive per turn: a given combat initiation follows
exactly one path. Path A and Path B cannot both fire on the same turn because Path A
is triggered by a Narrator `GMSignals` signal (NPC-initiated combat, ADR-0012), while
Path B is triggered by the CombatClassifier (player-initiated combat, ADR-0011).

### 3. Integration with initiative rolling

Surprise determination occurs before initiative is rolled. The sequence in
`core/combat.py` is:

```
1. receive potential_surprised_characters and stealth context
2. determine_surprise() → surprised_map: dict[str, bool]
3. roll_initiative(participants) → initiative_order
4. apply surprised_map to CombatParticipant records
5. return InitiativeResult(order=initiative_order, surprised=surprised_map)
```

Initiative is rolled for all participants regardless of Surprise — a surprised character
still has an initiative count. They simply cannot act on their first turn.

### 4. Initiative rolling with Disadvantage

When `surprised = True` for a participant, `core/combat.py` rolls their initiative with
Disadvantage: two d20 rolls, taking the lower result, then adding the DEX modifier.

```python
def roll_initiative(participants: list[CombatParticipant], ...) -> list[CombatParticipant]:
    for p in participants:
        if p.surprised:
            roll = min(dice.d20(), dice.d20())   # Disadvantage
        else:
            roll = dice.d20()
        p.initiative_roll = roll
        p.initiative_result = roll + dex_modifier(p)
    return sorted(participants, key=lambda p: p.initiative_result, reverse=True)
```

Both d20 results are logged in the turn record when Disadvantage applies — consistent
with the logging standard for all Disadvantage rolls in the system (ADR-0009).

After initiative is established, surprised participants act and react normally on every
turn, including their first. There is no turn-lifecycle enforcement of Surprise beyond
the initiative roll. The `api/turns.py` turn handler does not check `surprised` at any
point after combat initialisation.

### 5. Narrator context for Surprise

The Narrator receives the Surprise outcome as part of the combat initialisation context
injected into the snapshot for the first round. The snapshot includes:

```
Combat initiated. Round 1.
Initiative order: Goblin A (15), Kael (12), Goblin B (9), Mira (7)
Surprised: none
```

or

```
Combat initiated. Round 1.
Initiative order: Goblin A (18), Goblin B (14), Kael (9), Mira (6)
Surprised: Kael, Mira (cannot act this round)
```

The Narrator uses this to narrate the ambush appropriately — describing the moment of
shock, the NPCs acting before the PCs can react. The Narrator does not determine who is
surprised; it receives the Engine's determination and narrates it.

### 6. Alert feat and immunity to Surprise

The Alert feat (SRD 5.2.1) grants immunity to Surprise. Characters with the Alert feat
are automatically removed from `potential_surprised_characters` before `determine_surprise`
is called. This is a pre-filter in the Engine, not a special case inside the comparison
function.

Other sources of Surprise immunity (e.g. class features in non-SRD content loaded via the
Instance Library) are handled by the same pre-filter mechanism: the Engine checks the
character's feature list against a registered set of Surprise-immunity flags before
passing them to `determine_surprise`.

## Rationale

**Flag on `CombatParticipant` over entry in `conditions.py`**: The conditions system
(ADR-0001 §1) tracks conditions with durations, interactions, and removal triggers.
Surprise in SRD 5.2.1 has none of these — it is consumed at the moment of initiative
rolling and has no further mechanical effect. Adding it to the conditions system would
introduce a condition with zero duration and zero ongoing effect — a category of one that
adds overhead without benefit. A boolean flag on the participant record is set once, read
once, and ignored thereafter.

**Single `determine_surprise` function over two separate code paths**: The comparison
logic — Stealth result vs. passive Perception — is identical for both flows. Splitting it
would duplicate logic and create a maintenance surface. The difference between flows is
only in how `stealth_results` is populated before the function is called. Keeping the
function unified ensures both flows produce identical outcomes for identical inputs.

**Autonomous NPC Stealth rolls over Narrator-provided values**: The Narrator could provide
NPC Stealth results alongside `potential_surprised_characters`. Rejected because Stealth
rolls are mechanical outcomes — they must be deterministic, seeded, and auditable (ADR-0001
§1). Narrator-provided values would be invented, unverifiable, and inconsistent with the
Rules Engine's authority over mechanical outcomes. The Engine rolls autonomously using the
NPC's stat block modifier.

**"All concealers must beat passive Perception" over "any concealer beats"**: This is the
SRD RAW interpretation: a group is detected if any member is detected. A single loud
goblin ruins the ambush for all goblins. The alternative ("surprise if any concealer
succeeds") would make Surprise nearly inevitable whenever multiple NPCs are ambushing,
which is both mechanically wrong and unfun.

**Disadvantage on initiative only, no action restriction**: SRD 5.2.1 limits Surprise
to a single mechanical consequence — Disadvantage on the initiative roll. The 2014
ruleset (5e SRD 5.1) additionally blocked Actions, Bonus Actions, and Reactions in the
first round, but 5.2.1 removes these restrictions entirely. Implementing the 2014 rule
would be a homebrew deviation from the target SRD version. Surprised characters in
Tavern can act, use Bonus Actions, and react normally — they simply roll initiative at a
disadvantage, making them more likely to act later in the order.

## Alternatives Considered

**Surprise as a condition in `core/conditions.py`**: Model Surprise like Incapacitated —
a condition with a duration. Rejected because Surprise in SRD 5.2.1 has no duration —
it is consumed at initiative rolling and has no further effect. The conditions system is
designed for ongoing states with turn-based tracking. A condition that exists only to
modify a single roll before the first turn begins is not a condition in any meaningful
sense.

**Narrator determines final Surprise (not just candidates)**: The Narrator signals
`surprised_characters` (final, not potential) directly. Rejected because Surprise
determination requires mechanical computation — Stealth modifiers, Perception values,
dice rolls. These are Rules Engine responsibilities (ADR-0001). Allowing the Narrator to
determine final Surprise would let Claude decide a mechanical outcome, violating the
layer boundary.

**Implementing the 2014 Surprise rule (no action in round 1)**: Apply the SRD 5.1
Surprise rule — surprised characters cannot take Actions, Bonus Actions, or Reactions in
their first turn. Rejected because Tavern targets SRD 5.2.1 exclusively. The 5.2.1 rule
is unambiguous: Surprise causes Disadvantage on the initiative roll, nothing more. The
2014 rule would be undocumented homebrew.

**Interactive Surprise determination (player rolls Perception)**: Rather than using
passive Perception, prompt the player to make an active Perception check when an ambush
occurs. Rejected because SRD 5.2.1 uses passive Perception for Surprise determination
specifically. Active checks are used when a character is actively searching — not when
they are caught off guard. Deviating from RAW here would require a documented homebrew
decision.

**Group Stealth check (lowest result determines all)**: Use the lowest Stealth roll among
the concealing party as the single value compared against all targets. This is the SRD
group check mechanic, but it applies to group skill checks for tasks — not to Surprise
determination. Surprise uses individual comparisons. Implementing group check semantics
here would be mechanically incorrect.

## Consequences

### What becomes easier
- Surprise determination is a pure function: given the same inputs, it always produces
  the same outputs. It is trivially unit-testable and replayable via deterministic seeds.
- Both ambush flows (NPC-initiated, player-initiated) share the same code path from the
  point of `determine_surprise` onward. No special handling in the turn lifecycle.
- The Alert feat and other Surprise-immunity features are handled by a pre-filter with a
  clear extension point — adding new immunity sources does not change `determine_surprise`.
- The Narrator always receives a definitive Surprise outcome in the snapshot. It does not
  need to infer or guess — the Engine has already decided.

### What becomes harder
- Autonomous NPC Stealth rolls in Flow A require stat block access at combat initialisation
  time. The Engine must resolve `stat_block_ref` for all ambushing NPCs before calling
  `determine_surprise`. If an NPC has no stat block and no Stealth modifier, the Engine
  defaults to DEX modifier only (no proficiency) and logs the gap.
- The turn lifecycle is unchanged by Surprise — no new conditions in `api/turns.py`, no
  round-boundary events. The only added complexity is in `core/combat.py`'s
  `roll_initiative` function, which must correctly apply Disadvantage when `surprised` is
  set.
- The `CombatParticipant` dataclass is a new or extended record. If initiative order is
  currently stored as a simple list, it must be upgraded to carry per-participant metadata.

### New constraints
- `determine_surprise` must be called before `roll_initiative` in all combat initialisation
  paths. The surprised map must be attached to `CombatParticipant` records before the
  initiative order is broadcast to clients.
- The `surprised` flag must not be read by `api/turns.py` at any point after initiative
  is established. Its only valid read site is `core/combat.py` during `roll_initiative`.
  Any code path outside `roll_initiative` that branches on `surprised` is a bug.
- NPC Stealth rolls performed autonomously in Flow A must be persisted in the turn record
  with their dice results and modifiers, identical to any other Engine roll. They must not
  be silently discarded after use.
- If an NPC has no resolvable stat block and no explicit Stealth modifier, the Engine uses
  DEX modifier only (no proficiency bonus). This fallback must be logged as a data warning,
  not silently applied.
- The `TurnContext` passed to the CombatClassifier (ADR-0011) must include any Stealth
  roll results present in the current turn record. This is the mechanism by which Path B
  Surprise determination receives its input. If `TurnContext` does not carry this data,
  Path B silently degrades to Path C — no Surprise, no error. This silent degradation
  must be logged as a missing-context warning.
- Paths A, B, and C are mutually exclusive. The server must not attempt to merge
  `potential_surprised_characters` from both a Narrator signal and a prior Stealth roll
  context in the same combat initiation.
- The Alert feat and all registered Surprise-immunity features must be checked as a
  pre-filter before `determine_surprise` is called, never inside it.

## Review Triggers

- If the "all concealers must beat passive Perception" interpretation produces player
  complaints that Surprise is too rare or too easily broken by a single low-rolling NPC,
  evaluate a documented homebrew option (campaign-level setting) that uses the "highest
  concealer beats passive Perception" interpretation instead. This would be a campaign
  override, not a system-wide change.
- If autonomous NPC Stealth rolls in Flow A are frequently missing stat block data (NPC
  spawned by Narrator without `stat_block_ref`), evaluate making `stat_block_ref` mandatory
  for any NPC flagged in `potential_surprised_characters` at the ADR-0013 validation layer.
- If the Disadvantage-only Surprise rule feels insufficiently impactful to players —
  ambushes feel the same as normal combat — evaluate a campaign-level homebrew option that
  restores the 2014 action restriction (no Actions/Bonus Actions/Reactions in the first
  surprised turn). This would be an explicit opt-in deviation from SRD 5.2.1, documented
  as such in the campaign settings.
- If non-SRD Surprise-immunity features (from Instance Library content) become numerous
  enough that the pre-filter registry requires active maintenance, evaluate a declarative
  feature-flag system on the character model rather than a hardcoded registry.