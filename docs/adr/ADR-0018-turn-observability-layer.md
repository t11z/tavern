# ADR-0018: Turn Observability Layer

- **Status**: Accepted
- **Date**: 2026-04-06
- **Deciders**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/api/turns.py`, `backend/tavern/core/` (all modules), `backend/tavern/dm/` (all modules), PostgreSQL schema, WebSocket events, web client, Discord bot

## Context

Tavern has two independent processing layers — the Rules Engine (`core/`) and the DM layer
(`dm/`) — that both make consequential decisions on every turn. Today, neither layer has a
structured observability path. The consequences:

**Rules Engine blind spots**: `mechanical_results` (Game Design Spec: Mechanical Results Log)
captures the *outcomes* of engine resolution — attack rolls, damage, conditions — but not
the *decision path*. When the engine produces a wrong result, there is no record of which
branch `action_analyzer` chose, which SRD data lookup resolved, which modifier was applied
from which source, or why a spell slot validation succeeded or failed. Debugging requires
reading code and guessing inputs.

**DM layer blind spots**: `reason` fields on `SceneTransition`, `NPCUpdate`, and
`CombatClassification` are defined as "logging only" across ADR-0011, ADR-0012, and ADR-0013
— but there is no defined logging sink. These fields are populated by the LLM, written into
in-memory dataclasses, and then discarded after the turn pipeline completes. The same applies
to: which model tier was selected, whether the prompt cache was hit, how many tokens were
consumed, whether `GMSignals` parsed successfully, and what the raw `GMSignals` JSON looked
like before validation.

**Review Triggers are unobservable**: ADR-0002 defines a review trigger for Haiku
misclassification. ADR-0011 defines a 10% misclassification threshold on `confidence: "low"`
turns. ADR-0012 defines a 5% parse failure threshold on `GMSignals`. ADR-0015 defines a
15%/70% acceptance rate band for suggested actions. None of these thresholds can be measured
because no system collects the underlying data.

**No client-accessible diagnostics**: When a player reports "the game did something weird,"
the host has no way to inspect what happened internally. There is no admin panel, no debug
view, no event log accessible from any client. The only diagnostic path is reading server
logs on the host machine — which is unacceptable for a self-hosted product where the host
may not be the developer.

This ADR defines a unified observability layer that treats the Rules Engine and the DM layer
as equal first-class event sources, persists structured diagnostic data per turn, and
exposes it to authorised clients.

## Decision

### 1. Turn Event Log — a structured, per-turn diagnostic record

Every turn produces a `TurnEventLog` — a JSONB column on the `turns` table that records
the internal processing pipeline alongside the existing player-facing fields (`player_action`,
`narrative_response`, `mechanical_results`).

`TurnEventLog` is *not* player-facing. It is an operator/debug artefact, visible only to
the campaign host and server administrators.

```python
@dataclass
class TurnEventLog:
    turn_id: str                          # FK to Turn
    pipeline_started_at: datetime         # Wall clock, UTC
    pipeline_finished_at: datetime
    steps: list[PipelineStep]             # Ordered list of processing steps
    llm_calls: list[LLMCallRecord]        # All LLM calls made during this turn
    warnings: list[str]                   # Non-fatal issues (e.g., GMSignals parse fallback)
    errors: list[str]                     # Errors that were caught and recovered from
```

#### 1a. `PipelineStep` — what happened, in order

Each step records one discrete processing phase within the turn pipeline:

```python
@dataclass
class PipelineStep:
    step: str                             # Machine-readable step identifier
    started_at: datetime
    duration_ms: int
    input_summary: dict                   # Key inputs (not full payloads — summarised)
    output_summary: dict                  # Key outputs (not full payloads — summarised)
    decision: str | None                  # Human-readable one-line summary of the decision made
```

**Step identifiers for the Rules Engine (`core/`):**

| `step` | Source module | What it records |
|---|---|---|
| `action_analysis` | `action_analyzer.py` | Input: player action text. Output: `ActionCategory`, matched keywords. Decision: "Classified as melee_attack" |
| `combat_classification` | `combat_classifier.py` | Input: action text + scene summary. Output: `combat_starts`, `confidence`, `combatants`. Decision: reason field from classifier |
| `spell_resolution` | `spells.py` | Input: spell name, slot level, targets. Output: attack/save result, damage/healing, conditions. Decision: "Fireball resolved as AoE save, DC 15" |
| `attack_resolution` | `combat.py` | Input: attacker, target, weapon/spell. Output: hit/miss, damage, modifiers applied. Decision: "Hit — 19 vs AC 15, 2d6+3 slashing" |
| `initiative_roll` | `combat.py` | Input: participants, surprise map. Output: initiative order. Decision: "4 participants, 1 surprised" |
| `condition_evaluation` | `conditions.py` | Input: active conditions. Output: modifiers applied to current action. Decision: "Restrained: disadvantage on attack" |
| `srd_lookup` | `srd_data.py` | Input: entity index, campaign_id. Output: resolution tier (SRD/Instance/Override), entity found. Decision: "Goblin resolved from SRD Baseline" |
| `character_state_mutation` | `characters.py` | Input: state changes (HP delta, slot consumed, condition applied). Output: before/after values. Decision: "HP 24→15, 3rd-level slot consumed (2→1)" |
| `rest_resolution` | `characters.py` | Input: rest type, hit dice spent. Output: HP recovered, slots restored. Decision: "Long rest — full HP, all slots" |
| `death_save` | `combat.py` | Input: current successes/failures. Output: roll, new successes/failures, stabilised/dead. Decision: "Roll 14 — success (2/3)" |

**Step identifiers for the DM layer (`dm/`):**

| `step` | Source module | What it records |
|---|---|---|
| `snapshot_build` | `context_builder.py` | Input: campaign state summary. Output: snapshot token count, components included. Decision: "2,340 tokens — system prompt + 3 PCs + 4 NPCs + scene + summary" |
| `model_routing` | `narrator.py` | Input: request type, snapshot complexity. Output: model tier selected, concrete model ID. Decision: "High tier — claude-sonnet-4-20250514" |
| `narration` | `narrator.py` | Input: snapshot hash (not full snapshot). Output: narrative length (chars), stream duration. Decision: "Narrated combat round — 847 chars, 3.2s stream" |
| `gm_signals_parse` | `gm_signals.py` | Input: raw post-delimiter text (truncated to 500 chars). Output: parsed GMSignals or safe default. Decision: "Parsed — scene_transition: combat_start, 2 npc_updates" |
| `npc_update_apply` | `turns.py` | Input: NPCUpdate list. Output: records created/updated, name matches. Decision: "Spawned 'Goblin Scout', updated disposition of 'Marta'" |
| `scene_transition_apply` | `turns.py` | Input: SceneTransition. Output: mode change, combatants resolved. Decision: "combat_start — 3 combatants, 1 potentially surprised" |
| `summary_compression` | `summary.py` | Input: new turn text, current summary length. Output: compressed summary length, model used. Decision: "Summary 487→492 tokens — Haiku" |
| `suggested_actions_emit` | `turns.py` | Input: raw suggestions from GMSignals. Output: validated suggestions forwarded, items dropped. Decision: "3 suggestions emitted, 0 dropped" |

The step list is extensible. New engine mechanics or DM layer components add their step
identifier without schema changes — `steps` is a JSON array, not a fixed schema.

#### 1b. `LLMCallRecord` — per-call telemetry

Every LLM API call made during a turn is recorded:

```python
@dataclass
class LLMCallRecord:
    call_type: str                        # "narration", "classification", "summary_compression",
                                          # "campaign_brief", "npc_action_choice"
    model_id: str                         # Concrete model string, e.g. "claude-sonnet-4-20250514"
    model_tier: str                       # "high" or "low"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int                # Tokens served from prompt cache (0 if no cache hit)
    cache_creation_tokens: int            # Tokens written to cache (0 if cache already warm)
    latency_ms: int                       # Wall-clock time for the full API call
    stream_first_token_ms: int | None     # Time to first streamed token (null for non-streamed)
    estimated_cost_usd: float             # Calculated from token counts and current pricing
    success: bool                         # False if the call failed and was retried or fell back
    error: str | None                     # Error message if success=false
```

This record directly operationalises the cost model from ADR-0002 (target: sub-dollar
sessions) and the review triggers from ADR-0002 (cache behaviour changes), ADR-0011
(classifier latency p95 > 800ms), and ADR-0015 (suggestion quality correlation with
model tier).

### 2. Persistence

`TurnEventLog` is stored as a JSONB column `event_log` on the existing `turns` table,
alongside `mechanical_results`.

```sql
ALTER TABLE turns ADD COLUMN event_log JSONB DEFAULT NULL;
```

**Why on `turns`, not a separate table**: The event log's lifecycle is identical to the
turn's lifecycle. It is written once at turn completion, never updated, and queried by
turn ID. A separate table adds a join with no structural benefit. The log is nullable —
turns created before the migration have `NULL` and are rendered as "No diagnostic data
available" in the inspect panel.

**Size budget**: A typical turn's `event_log` is 2–5 KB (8–12 pipeline steps, 1–3 LLM
calls, minimal warnings). A 100-turn session adds ~300 KB of diagnostic data. This is
negligible relative to the existing `narrative_response` (which averages ~2 KB per turn)
and `mechanical_results` (~1 KB per combat turn).

**Retention**: `event_log` follows the campaign lifecycle (ADR-0004). When a campaign
transitions to `abandoned`, its turn data — including event logs — is eligible for cold
storage archival. No separate retention policy.

### 3. Structured logging integration

The `TurnEventLog` is the *structured* diagnostic record. It does not replace Python's
`logging` module — it complements it.

**Relationship to `logging`:**

| Concern | `logging` (stdout/stderr) | `TurnEventLog` (JSONB) |
|---|---|---|
| Audience | Server operator reading logs | Host/admin via client inspect panel |
| Scope | All server activity (startup, requests, DB queries) | Per-turn pipeline only |
| Retention | Log rotation, ephemeral | Persistent with turn data |
| Granularity | Arbitrary detail, debug-level | Summarised — key inputs/outputs only |
| Queryable | grep/jq on log files | SQL on JSONB column |

`logging` continues to serve its current purpose. The `TurnEventLog` adds a structured,
persistent, queryable layer on top — specifically scoped to the turn pipeline, specifically
designed for client consumption.

**Logging convention** (new constraint): All modules in `core/` and `dm/` use Python's
`logging` module with a logger named `tavern.<module_path>` (e.g.,
`tavern.core.combat`, `tavern.dm.narrator`). Log levels follow standard semantics:

- `DEBUG`: Detailed processing steps (input/output of individual functions). Not persisted
  to `TurnEventLog` by default.
- `INFO`: Pipeline step completion, LLM call completion, state transitions.
- `WARNING`: Non-fatal issues — GMSignals parse fallback, NPC name match failure, classifier
  confidence "low", snapshot token count above threshold.
- `ERROR`: Caught exceptions — LLM call failure with retry, schema validation failure,
  database write failure with rollback.

### 4. Turn pipeline instrumentation

The turn pipeline in `api/turns.py` is the sole producer of `TurnEventLog` records.
Instrumentation is implemented via a context manager or accumulator pattern — each step
in the pipeline registers its `PipelineStep` with the accumulator, and the completed
`TurnEventLog` is persisted atomically with the turn record.

```
Turn pipeline (instrumented):

1. [action_analysis]           → PipelineStep
2. [combat_classification]     → PipelineStep + LLMCallRecord     (exploration only)
3. [spell_resolution]          → PipelineStep                      (if spell)
   [attack_resolution]         → PipelineStep                      (if attack)
   [condition_evaluation]      → PipelineStep                      (if conditions active)
   [srd_lookup]                → PipelineStep                      (if SRD entity referenced)
   [character_state_mutation]  → PipelineStep
4. [snapshot_build]            → PipelineStep
5. [model_routing]             → PipelineStep
6. [narration]                 → PipelineStep + LLMCallRecord
7. [gm_signals_parse]          → PipelineStep
8. [npc_update_apply]          → PipelineStep                      (if npc_updates non-empty)
9. [scene_transition_apply]    → PipelineStep                      (if scene_transition non-none)
10. [summary_compression]      → PipelineStep + LLMCallRecord
11. [suggested_actions_emit]   → PipelineStep                      (if suggestions non-empty)
12. Persist Turn + event_log   → atomic commit
```

The accumulator is passed through the pipeline, not injected as a global. Each module
function that produces a `PipelineStep` receives the accumulator as a parameter and
registers its step. This keeps the instrumentation explicit and avoids hidden state.

**Performance budget**: Step registration is in-memory dict construction — microseconds.
The JSONB serialisation at persist time adds <1ms. Total overhead per turn: <5ms. This
is negligible relative to the LLM call latency (500ms–5s).

### 5. Session-level telemetry aggregation

Session-level metrics are computed from `TurnEventLog` data on demand, not pre-aggregated.
The query patterns are:

| Metric | Query | Operationalises |
|---|---|---|
| Total LLM cost per session | `SUM(llm_calls[*].estimated_cost_usd)` across session turns | ADR-0002 cost target |
| Cache hit rate | `SUM(cache_read_tokens) / SUM(input_tokens)` | ADR-0002 cache review trigger |
| Classifier confidence distribution | `COUNT WHERE combat_classification.confidence = "low"` | ADR-0011 10% threshold |
| GMSignals parse failure rate | `COUNT WHERE gm_signals_parse.output_summary.fallback = true` | ADR-0012 5% threshold |
| Suggestion acceptance rate | External — tracked client-side (see §7) | ADR-0015 15%/70% band |
| p95 classifier latency | `PERCENTILE(combat_classification.duration_ms, 0.95)` | ADR-0011 800ms threshold |
| Model tier distribution | `COUNT GROUP BY model_routing.output_summary.model_tier` | ADR-0002 Haiku routing rate |
| Avg narration latency | `AVG(narration.duration_ms)` | General performance |
| Avg turn pipeline duration | `AVG(pipeline_finished_at - pipeline_started_at)` | General performance |

These queries run against the JSONB column using PostgreSQL's JSON path operators. No
materialised views or pre-computed tables at this stage — the query volume (one host
checking one campaign) does not justify the complexity.

### 6. WebSocket events for live telemetry

Two new WebSocket events enable live observability in clients:

#### `turn.event_log`

Emitted after `turn.narrative_end` and `turn.suggested_actions`, only to connections
with host/admin privileges (see §8).

```json
{
  "type": "turn.event_log",
  "payload": {
    "turn_id": "uuid",
    "sequence_number": 34,
    "pipeline_duration_ms": 3420,
    "steps": [ ... ],
    "llm_calls": [ ... ],
    "warnings": ["GMSignals: suggested_actions item 3 exceeded 200 chars, dropped"],
    "errors": []
  }
}
```

Non-admin clients never receive this event. The payload is the full `TurnEventLog`.

#### `session.telemetry`

Emitted on session start (alongside `session.state`) and every 10 turns thereafter,
only to connections with host/admin privileges.

```json
{
  "type": "session.telemetry",
  "payload": {
    "session_id": "uuid",
    "turns_processed": 34,
    "total_cost_usd": 0.12,
    "total_input_tokens": 48200,
    "total_output_tokens": 12400,
    "cache_hit_rate": 0.47,
    "avg_narration_latency_ms": 2840,
    "avg_pipeline_duration_ms": 3420,
    "classifier_invocations": 28,
    "classifier_low_confidence_count": 2,
    "gm_signals_parse_failures": 0,
    "model_tier_distribution": {"high": 30, "low": 4}
  }
}
```

This is a running aggregate, not a per-turn snapshot. It is cheap to compute (iterate
in-memory over the session's turns) and provides the session-level view that the host
needs without querying the database.

### 7. Client inspect panel

#### Web client

The inspect panel is a **host-only UI element** in `GameSession.tsx`. It is not visible
to regular players. Visibility is controlled by the same privilege mechanism that gates
session management controls.

**Layout**: A collapsible drawer or tab (alongside the Mechanical Results Log from the
Game Design Spec), labelled "🔍 Inspect" or equivalent. The panel has two views:

**Turn detail view**: When the host selects a turn (click on narrative message or log
entry), the panel shows that turn's `TurnEventLog`:

- Pipeline steps as a vertical timeline, each step expandable to show `input_summary`,
  `output_summary`, and `decision`
- LLM calls as cards showing model, tokens, cost, latency, cache status
- Warnings/errors highlighted at the top
- Total pipeline duration and cost for the turn

**Session overview**: Aggregated telemetry from `session.telemetry`:

- Running cost counter ("Session cost: $0.12")
- Cache hit rate gauge
- Narration latency sparkline (last 20 turns)
- Classifier confidence distribution (pie or bar)
- GMSignals parse success rate
- Model tier distribution

**Player-Facing Behavior**: Regular players see no change. The inspect panel is invisible
unless the connected user is the campaign host. The host sees a small toggle icon near
the session controls. When expanded, the panel provides a real-time, turn-by-turn view
of what both the Rules Engine and the Narrator did — and why — without exposing internal
data to other players.

#### Discord bot

A `/inspect` slash command, available only to the user who created the campaign:

- `/inspect turn [number]` — Returns an ephemeral embed with the turn's pipeline steps,
  LLM call summary, and warnings.
- `/inspect session` — Returns an ephemeral embed with the session telemetry summary.
- `/inspect cost` — Shortcut for session cost and token usage.

Ephemeral messages ensure diagnostic data is visible only to the host, not the channel.

### 8. Access control

The `TurnEventLog` contains internal system details — model IDs, token counts, prompt
sizes, cost data, raw GMSignals JSON. This is operator information, not player information.

Access control rules:

- **`turn.event_log` WebSocket event**: Emitted only to WebSocket connections authenticated
  as the campaign creator (ADR-0006 Phase 6) or server admin. Before auth is implemented:
  emitted to all connections but flagged with `admin_only: true` for future filtering.
- **`session.telemetry` WebSocket event**: Same access control as `turn.event_log`.
- **`GET /api/campaigns/{campaign_id}/turns/{turn_id}/event_log`**: New REST endpoint,
  host/admin only. Returns the `event_log` JSONB for a specific turn.
- **`GET /api/campaigns/{campaign_id}/sessions/{session_id}/telemetry`**: New REST endpoint,
  host/admin only. Returns computed session telemetry.
- **Discord `/inspect` command**: Restricted to the campaign creator via the existing
  ownership check in the Discord bot.

Before ADR-0006 auth is implemented, the interim policy mirrors the existing Known Deviation:
all endpoints are unprotected, but the client UI hides the inspect panel behind the host
controls. This is a UI-level guard, not a security boundary — consistent with the current
no-auth state of the entire API.

### 9. Instrumenting `core/` without violating dependency direction

`core/` must not import from `dm/` (CLAUDE.md dependency direction rule). The observability
layer must not create a new dependency.

**Solution**: The accumulator is a plain dataclass defined in a new module
`backend/tavern/observability.py` — a top-level module that neither `core/` nor `dm/`
depends on. Instead, `api/turns.py` (which already imports from both layers) creates the
accumulator, passes it into each function call, and collects the results.

`core/` functions do not know about the accumulator. Instead, they return enriched result
objects that include diagnostic metadata alongside their existing return values. Example:

```python
# Before (core/combat.py):
def resolve_attack(attacker, target, weapon) -> AttackResult:
    ...

# After (core/combat.py):
def resolve_attack(attacker, target, weapon) -> AttackResult:
    # AttackResult gains optional diagnostic fields:
    # .modifiers_applied: list[str]
    # .srd_lookup_tier: str | None
    # .decision_summary: str
    ...
```

`api/turns.py` reads these diagnostic fields from the result objects and constructs the
`PipelineStep` entries. `core/` remains unaware of the observability layer — it simply
returns richer result objects. This is the same pattern as `CombatClassification.reason`:
the module produces metadata, the pipeline consumer decides where to send it.

`dm/` functions can follow the same pattern. `narrator.py` already returns
`tuple[str, GMSignals]` — it extends to include `LLMCallRecord` metadata in the return
value. `context_builder.py` returns snapshot token counts alongside the snapshot.

## Rationale

**Single JSONB column over normalised event tables**: The event log is write-once, read-rarely,
variable-structure data. Normalising pipeline steps and LLM calls into separate tables with
foreign keys adds join complexity for a query pattern that is always "give me everything for
this turn." JSONB handles variable step lists, optional fields, and schema evolution without
migrations. If query performance on JSONB becomes an issue (it won't at Tavern's scale), GIN
indexes on specific JSON paths are a targeted remedy.

**Enriched return values over injected accumulator**: Passing an accumulator into `core/`
functions would either create an import dependency (if the accumulator type is defined
outside `core/`) or require `core/` to define its own observability types (which is scope
creep for a deterministic rules engine). Enriching return values keeps `core/` self-contained:
it already returns result dataclasses, and adding diagnostic fields to those dataclasses is a
natural extension. The pipeline orchestrator in `api/turns.py` decides what to do with them.

**JSONB on `turns` over a separate logging table**: The event log is 1:1 with turns. A
separate table would require a foreign key, a join on every inspect query, and a separate
migration. The only benefit would be if event logs needed independent lifecycle management
(e.g., deleting logs while keeping turns). They don't — diagnostic data follows the turn's
lifecycle.

**Per-turn persistence over in-memory-only metrics**: In-memory metrics are lost on server
restart. A self-hosted server that restarts (deployment, crash, update) loses all session
telemetry. Persisting to the turn record means diagnostic data survives restarts, session
boundaries, and is available for post-session analysis. The storage cost (300 KB per 100
turns) is trivial.

**WebSocket events over polling**: The inspect panel needs live data as each turn completes.
Polling the REST endpoint every N seconds would add unnecessary load and lag. The WebSocket
path already exists and delivers turn-scoped events — adding `turn.event_log` is consistent
with the existing event model (ADR-0005).

**Session-level aggregation on demand over pre-computed materialised views**: At Tavern's
scale (one host inspecting one campaign at a time), computing session aggregates from the
JSONB column is fast enough. Materialised views would add maintenance complexity, stale-data
risk, and migration burden for a query that takes <50ms on 100 turns.

## Alternatives Considered

**OpenTelemetry / Jaeger tracing**: Full distributed tracing with spans, traces, and a
collector pipeline. Rejected — Tavern is a single-process Python application. There is
nothing distributed to trace. OTel's value is in correlating events across service
boundaries; Tavern has one service. The infrastructure overhead (collector sidecar, trace
storage, trace viewer) is disproportionate. If Tavern evolves to a multi-service
architecture (e.g., separate Rules Engine service), reconsider.

**Separate observability database (ClickHouse, TimescaleDB)**: A dedicated time-series or
analytics database for telemetry data. Rejected — this adds a fifth service to Docker
Compose for a feature that serves a single-digit number of concurrent inspectors. PostgreSQL
JSONB handles the query patterns at Tavern's scale. If the project grows to thousands of
concurrent campaigns and session telemetry becomes a cross-campaign analytics concern,
reconsider.

**Client-side-only diagnostics (browser DevTools network tab)**: Rely on the host inspecting
network traffic and server logs manually. Rejected — this is the status quo. It requires
technical sophistication that a self-hosted RPG server host should not need. It also cannot
show Rules Engine internals, which are server-side only and invisible in network traffic.

**Logging to files with a separate log viewer**: Write structured JSON logs to files, provide
a separate web UI (Kibana, Grafana Loki) for viewing. Rejected — this is enterprise
infrastructure for a self-hosted indie RPG server. Docker Compose already has 4 services.
Adding an ELK/Loki stack doubles the deployment complexity. The integrated inspect panel
serves the same purpose within the existing application.

**Separate `event_log` table with foreign key to `turns`**: Normalised storage with
`turn_id`, `step_type`, `step_data` rows. Rejected — the access pattern is always "get all
steps for one turn." A normalised table turns this into a multi-row fetch with ordering
concerns. The JSONB column returns the complete, ordered log in a single field read.

## Consequences

### What becomes easier

- Debugging Rules Engine bugs: when a player reports "my attack should have hit," the host
  can inspect the turn's `attack_resolution` step and see the exact modifiers, AC lookup,
  and roll that produced the miss.
- Debugging Narrator issues: when the Narrator ignores a scene transition or spawns an
  unexpected NPC, the host can inspect `gm_signals_parse` and `npc_update_apply` to see
  what the Narrator actually emitted and how the server processed it.
- Operationalising ADR review triggers: classifier confidence distribution, GMSignals parse
  failure rate, model routing distribution, and cost per session are all directly queryable
  from persisted data.
- Cost monitoring: the host sees session cost in real time. This was a promise in ADR-0002
  ("session costs are predictable and transparent") that had no implementation path until now.
- Bug reports improve: instead of "something weird happened on turn 34," the host can attach
  the turn's event log — a structured record of exactly what happened.
- Narrative quality analysis: the event log provides the raw data for the planned offline
  batch analysis pipeline (narrative quality testing). `LLMCallRecord` links each narration
  to its model, token budget, and latency, enabling quality-vs-cost correlation.

### What becomes harder

- Every `core/` result dataclass gains diagnostic fields. These fields are optional and
  default to `None`, but they add surface area to types that were previously minimal. Tests
  must not assert on diagnostic fields unless specifically testing observability.
- The turn pipeline in `api/turns.py` gains instrumentation code at every step. This must
  not obscure the pipeline's control flow. The accumulator pattern keeps instrumentation
  visually separate from business logic, but code reviewers must be vigilant about
  entanglement.
- The `turn.event_log` WebSocket event is host-only. Before auth is implemented (ADR-0006),
  this is a UI-level guard only. A determined player could listen for the event via a custom
  client. This is an acceptable interim risk — the data is diagnostic, not secret.

### New constraints

- `TurnEventLog` must be persisted atomically with the turn record. If the turn persists
  but the event log does not (or vice versa), the diagnostic data is unreliable. Both
  fields are written in the same database transaction.
- `input_summary` and `output_summary` in `PipelineStep` must not contain full prompt
  text, full narrative text, or player PII. They are *summaries* — token counts, entity
  names, decision outcomes. The full prompt is never persisted in the event log.
- `estimated_cost_usd` in `LLMCallRecord` is a best-effort calculation based on
  published pricing at deployment time. It is not a billing system. The host should
  treat it as an estimate, not an invoice.
- New pipeline steps added in future ADRs or mechanics must include a corresponding
  step identifier in this table. This is a convention, not enforced by schema — but
  the Claude Code PR review workflow should flag pipeline changes that lack
  instrumentation.
- The `/inspect` Discord command must use ephemeral responses exclusively. Diagnostic
  data must never be posted to a public channel.

## Review Triggers

Automated triggers in this ADR are runtime assertions in the turn pipeline or endpoint
handlers, not CI jobs. The turn pipeline has the immediate context (which turn, which steps
were oversized) that a retroactive batch check would lack. Trend analysis is deferred to
the inspect panel's session overview, which makes monotonic growth visually obvious.

- If `event_log` JSONB size exceeds 20 KB on any single turn (indicating a runaway step
  list or excessively detailed summaries), evaluate whether `input_summary`/`output_summary`
  fields are being over-populated and tighten the summarisation rules. Implementation:
  post-persist `WARNING` log in `api/turns.py` after `event_log` serialisation —
  `len(json_bytes) > 20480`.
- If the inspect panel shows that `estimated_cost_usd` deviates from actual API billing by
  more than 20% over a 100-turn sample, update the pricing constants or add a provider
  callback for real-time pricing.
- If host adoption of the inspect panel is near-zero after 3 months of availability (no
  `/inspect` commands, no panel opens tracked via client telemetry), evaluate whether the
  feature is discoverable enough or whether the data it shows is not useful in practice.
- If the JSONB query performance for session-level aggregation exceeds 200ms on sessions
  with 200+ turns, evaluate adding a GIN index on `turns.event_log` or introducing
  pre-computed session summaries. Implementation: timed query execution in the session
  telemetry endpoint — `WARNING` log if wall-clock exceeds 200ms.
- If the number of pipeline step types exceeds 30, evaluate whether a step type registry
  (enum or constants module) is needed to prevent typos and ensure consistency across
  modules.