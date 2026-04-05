# Game Design Spec: Mechanical Results Log

**Status:** Accepted  
**Area:** Web Client UI · Discord Bot · API  
**Related ADRs:** ADR-0002, ADR-0004, ADR-0005, ADR-0009

---

## Problem

`mechanical_results` exists as a structured field in `turn.narrative_end` (per ADR-0005), but the web client has no defined, dedicated rendering zone for it. The result is that mechanical feedback surfaces inconsistently — sometimes inline in the narrative, sometimes absent, always unreliable. Players cannot verify what the engine actually resolved.

This spec formalises mechanical result display as a first-class feature across all clients and closes the data gap that makes session-persistent logs impossible.

---

## Scope

The log covers all deterministic outputs from the Rules Engine:

| Category | Examples |
|---|---|
| Attack rolls | Hit/miss, roll total vs. AC, damage by type |
| Saving throws | DC, roll total, pass/fail, half-damage modifier |
| Ability checks | Skill, DC (if applicable), roll total, outcome |
| Spell effects | Spell name, slot level consumed, targets, effect applied |
| Damage / Healing | Amount, type, HP before → after, for all affected entities |
| Conditions | Applied or removed, source, target, duration if known |
| Resource consumption | Spell slots, Hit Dice, Bardic Inspiration, Action Surge, etc. |
| Reactions | Reaction used, by whom, against which roll |
| Rolls (standalone) | Initiative, death saving throws, perception checks |
| Rest results | Short/long rest HP recovered, spell slots restored, Hit Dice spent |
| Combat transitions | Combat started (initiative order), combat ended |

Out of scope: narrative text, NPC motivations, plot events, scene descriptions. These belong in the narrative stream, not the log.

---

## Data Contract

### The current gap

`Turn.rules_result` is stored as unstructured `text` in PostgreSQL. This is insufficient for log reconstruction on reconnect. The log requires structured data.

### Required schema change

`Turn.rules_result` must be extended — or supplemented — to persist `mechanical_results` as JSONB alongside the existing text representation. The text remains for rolling summary use. The JSONB field is what the log reads.

**Migration:** Add `mechanical_results JSONB DEFAULT NULL` to the `turns` table. Turns created before the migration have `NULL` here and are rendered as a fallback entry ("No mechanical data recorded").

### `mechanical_results` entry shape

Each entry in the array is a typed event:

```json
[
  {
    "type": "attack_roll",
    "actor": "Kael",
    "target": "Goblin A",
    "roll": 14,
    "modifier": 5,
    "total": 19,
    "target_ac": 15,
    "outcome": "hit"
  },
  {
    "type": "damage",
    "actor": "Kael",
    "target": "Goblin A",
    "amount": 9,
    "damage_type": "slashing",
    "breakdown": "4+2+3",
    "hp_before": 9,
    "hp_after": 0
  },
  {
    "type": "condition_removed",
    "target": "Goblin A",
    "condition": "alive"
  }
]
```

Supported `type` values: `attack_roll`, `saving_throw`, `ability_check`, `damage`, `healing`, `condition_applied`, `condition_removed`, `spell_cast`, `resource_consumed`, `reaction_used`, `initiative_rolled`, `rest_result`, `combat_started`, `combat_ended`.

The Rules Engine is the sole producer of these entries. The Narrator never produces or modifies `mechanical_results`. This boundary is absolute (ADR-0002).

### `session.state` on connect

The `session.state` WebSocket event must include `recent_turns` with their `mechanical_results`. The client uses this to populate the log on connect and reconnect without a separate REST fetch.

```json
{
  "event": "session.state",
  "payload": {
    "campaign": { ... },
    "characters": [ ... ],
    "scene": { ... },
    "recent_turns": [
      {
        "turn_id": "uuid",
        "sequence_number": 34,
        "character_name": "Kael",
        "player_action": "I attack the goblin.",
        "mechanical_results": [ ... ],
        "created_at": "2026-04-05T19:12:00Z"
      }
    ]
  }
}
```

`recent_turns` loads the last 50 turns for the campaign (not session-scoped — across sessions, so the log survives a pause/resume). This is the same data source the rolling summary rebuilds from; the query already exists.

If 50 turns generates payload size concerns, the fallback is 20 turns. This is a tuning decision, not an architectural one.

---

## Web Client

### Layout

The log lives as a **dedicated panel** in `GameSession.tsx`, separate from the narrative chat. It does not scroll inside the narrative; it has its own scroll container.

Two viable layout positions:

**Option A — Right sidebar (recommended for desktop):** Narrative left ~60%, log panel right ~40%. On mobile: log collapses behind a tab toggle ("⚔️ Log"). This matches the existing sidebar pattern in `GameSession.tsx`.

**Option B — Bottom drawer:** Log lives below the narrative, collapsible. Higher cognitive load — players must scroll or toggle. Only recommended if right sidebar causes layout conflicts.

This spec does not mandate the exact layout — that is a Claude Code implementation decision. The constraint is: the log must be a distinct, persistent zone, not interleaved with narrative text.

### Entry rendering

Each `mechanical_results` entry renders as a compact, structured row — not prose. The web client applies its own formatting; it receives typed data (ADR-0005, plain data principle).

**Visual grammar:**

```
[sequence] [actor] → [target]   [outcome label]
           [detail line]
```

Examples:

```
Turn 34  Kael → Goblin A                          HIT
         Attack: 19 (14+5) vs AC 15
         Damage: 9 slashing (4+2+3)
         Goblin A: 9 HP → 0 HP · Defeated

Turn 34  Mira — Fireball (3rd-level slot)         CAST
         Targets: Goblin B, Goblin C, Skeleton D
         DEX save DC 15
         Goblin B: 12 — Fail · 24 fire damage · Defeated
         Goblin C: 17 — Save · 12 fire damage · 3 HP remaining
         Skeleton D: 4 — Fail · 24 fire damage · Defeated
         Spell slot consumed: 3rd (1 remaining)

Turn 35  Aldric — Short Rest                      REST
         Hit Die: 1d10 (rolled 7) + 2 CON = 9 HP
         HP: 22 → 31 / 38

Turn 35  Kael — Death Saving Throw                FAIL
         Roll: 8 — Fail (1/3 failures)
```

Colour coding:
- Green: hit, pass, heal, success
- Red: miss, fail, damage taken, defeated
- Amber: condition applied, resource consumed, half-damage
- Neutral/grey: combat transitions, roll results without clear valence

No icons beyond what CSS can produce without external assets. The existing Tavern design tokens apply.

### Grouping

Entries group by turn. All `mechanical_results` from a single turn appear under one collapsible turn header. By default, the last 5 turns are expanded; older turns are collapsed. The player can expand/collapse any turn group.

When a new `turn.narrative_end` arrives, its `mechanical_results` are prepended (or appended, depending on scroll direction) to the log and the new turn group is auto-expanded.

### Empty state

If `mechanical_results` is empty or `null` for a turn (e.g., pure narrative action with no mechanical resolution, or a turn from before the migration), the turn group shows: "No mechanical results recorded."

The turn header still appears so players can see the turn sequence is contiguous.

### Scroll behaviour

Log starts at the bottom (most recent turn visible). New entries appear at the bottom and the log auto-scrolls, unless the player has manually scrolled up — in which case auto-scroll is suspended until the player returns to the bottom. This is the standard chat scroll contract and applies identically here.

---

## Discord Bot

The Discord bot already has a Mechanical Results Embed defined in `discord_bot/embeds/combat.py` and in the `discord-bot.md` game design spec. This feature does not change that design.

The only required change: the embed must be populated from `turn.narrative_end`.`mechanical_results` exclusively — not assembled from narrative text parsing or heuristics. The typed entries are the source of truth.

**Embed rendering per entry type:**

| Type | Embed line format |
|---|---|
| `attack_roll` + `damage` | `Kael → Goblin A: 19 (14+5) vs AC 15 — Hit · 9 slashing · 0 HP` |
| `saving_throw` | `Goblin B: DEX save 12 vs DC 15 — Fail · 24 fire damage` |
| `ability_check` | `Aldric: Perception 18 — Success` |
| `condition_applied` | `Mira: Poisoned (3 rounds)` |
| `resource_consumed` | `Kael: Action Surge used (0 remaining)` |
| `rest_result` | `Short Rest: Aldric +9 HP (1d10+2)` |
| `combat_started` | `⚔️ Initiative: Kael 19 · Aldric 15 · Goblin A 11 · Goblin B 8` |

The embed posts once per turn, attached to the narrative message. It does not update in-place for normal turn results (only reaction windows update in-place, per the existing reaction system spec).

If `mechanical_results` is empty, no embed is attached. The narrative message stands alone.

---

## API Changes

### New REST endpoint

```
GET /api/campaigns/{campaign_id}/turns?limit=50&offset=0
```

Returns paginated turn records with `mechanical_results`. Used by the web client if the `session.state` payload is insufficient (e.g., player wants to scroll further back in log history). Not required for V1 of this feature — `session.state` with 50 turns covers the common case. Defer until a player requests deeper history.

### Changes to existing endpoints

`turn.narrative_end` WebSocket event: no payload change required. `mechanical_results` is already specified as part of this event (see architecture snapshot). The change is that the server must now also persist this array to `Turn.mechanical_results` (JSONB) at the same time it persists `Turn.narrative_response`.

`session.state` WebSocket event: extend `recent_turns` to include `mechanical_results` per turn. Currently `recent_turns` payload shape is not fully specified — this spec defines it.

---

## Implementation Notes for Claude Code

This spec requires three coordinated changes that can be implemented in parallel:

**Track A — Backend (no frontend dependency):**
1. Add `mechanical_results JSONB DEFAULT NULL` to `turns` table via Alembic migration.
2. In `api/turns.py`, persist `mechanical_results` from the engine result to the Turn record.
3. Extend `session.state` broadcast to include `recent_turns` with `mechanical_results`.

**Track B — Frontend (depends on Track A data being available):**
1. Add `MechanicalLog` component to `GameSession.tsx`.
2. Populate from `session.state`.`recent_turns` on connect.
3. Append from `turn.narrative_end`.`mechanical_results` on each new turn.
4. Render typed entries per the visual grammar defined above.

**Track C — Discord Bot (depends on Track A data being available):**
1. Verify `combat.py` embed builder reads from `mechanical_results` typed entries.
2. Remove any narrative text parsing used to construct embed content.

Tracks B and C can begin against the existing `turn.narrative_end` event (which already carries `mechanical_results`) before Track A is complete. The log will work for the current session but not persist across reconnects until Track A is deployed.

---

## Out of Scope for V1

- Filtering the log by entry type (e.g., "show only damage")
- Exporting the log
- Sharing log entries to Discord from the web client
- Log entries for NPC-vs-NPC actions (these are Claude-narrated, not engine-resolved)
- A REST endpoint for deep history pagination (defer until user demand)
