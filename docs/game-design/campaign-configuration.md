# Campaign Configuration

This document defines the runtime settings that a campaign owner can modify after campaign creation. For startup parameters (tone, length, setting, focus, difficulty) that are fixed at creation time, see `campaign-design.md`.

Runtime settings are stored on the Campaign entity in the database. They are modified via the REST API (`PATCH /api/campaigns/{id}/config`) or via the Discord bot (`/tavern config <key> <value>`). The web client exposes them in a campaign settings panel.

## Settings Catalog

### Gameplay

| Key | Type | Default | Options | Description |
|---|---|---|---|---|
| `rolling_mode` | enum | `interactive` | `interactive`, `automatic`, `hybrid` | How dice rolls are handled. See ADR-0009. `interactive`: player triggers every roll. `automatic`: engine rolls silently, reaction windows still open. `hybrid`: attack rolls and saving throws are interactive, damage/initiative/minor checks are automatic. |
| `turn_timeout` | integer | `120` | 30–600 (seconds) | Time a player has to submit an action or trigger a roll before the engine auto-resolves (Dodge in combat, auto-roll for pending dice). |
| `reaction_window` | integer | `15` | 5–30 (seconds) | Time other players have to submit reactions after a roll result. Shorter = faster combat, longer = more tactical deliberation. |
| `difficulty` | enum | `balanced` | `forgiving`, `balanced`, `deadly` | Affects NPC tactical intelligence and encounter scaling. Set at creation but changeable mid-campaign. Does not retroactively affect past encounters. |

### Session Management

| Key | Type | Default | Options | Description |
|---|---|---|---|---|
| `allow_late_join` | boolean | `true` | `true`, `false` | Whether new players can join mid-session. If false, players can only join between sessions. |
| `absent_character_mode` | enum | `passive` | `passive`, `auto` | What happens to characters whose players disconnect. `passive`: character fades to background, mechanically inert (ADR-0004 §7). `auto`: Claude controls the character as an NPC with conservative tactics (Dodge in combat, follow the party in exploration). |

### Discord-Specific

| Key | Type | Default | Options | Description |
|---|---|---|---|---|
| `ooc_prefix` | string | `//` | any string | Prefix for out-of-character messages that the bot should ignore. Some groups prefer `ooc:` or `#`. |
| `show_party_status` | boolean | `true` | `true`, `false` | Whether to append a compact party status line to each turn's mechanical results embed. |

## Setting Constraints

**Immutable after creation:** Tone (`dm_persona`), campaign length, setting type, play focus, and world seed cannot be changed after campaign creation. These define the campaign's identity and are baked into the rolling summary and narrative history. Changing them mid-campaign would create tonal inconsistency. If a group wants a different tone, they start a new campaign.

**Changeable anytime:** All settings in the catalog above. Changes take effect on the next turn. No retroactive effects — changing `difficulty` from `balanced` to `deadly` does not make the current combat harder, it affects future encounter generation.

**Owner-only:** All configuration changes require campaign owner role (ADR-0006 §3). Players cannot modify settings. This prevents mid-combat griefing (e.g., a player setting `turn_timeout` to 5 seconds).

## API

```
PATCH /api/campaigns/{campaign_id}/config
Authorization: Bearer <owner_token>
Content-Type: application/json

{
  "rolling_mode": "hybrid",
  "reaction_window": 10
}

Response 200:
{
  "rolling_mode": "hybrid",
  "turn_timeout": 120,
  "reaction_window": 10,
  "difficulty": "balanced",
  "allow_late_join": true,
  "absent_character_mode": "passive",
  "ooc_prefix": "//",
  "show_party_status": true
}
```

Invalid keys are rejected with 400. Invalid values (e.g., `turn_timeout: 5`) are rejected with 422 and an error message explaining the valid range.

```
GET /api/campaigns/{campaign_id}/config

Response 200: (same shape as PATCH response)
```

Read access is available to all campaign members, not just the owner. Players can see the current configuration but not change it.

## Discord Integration

The campaign owner uses `/tavern config` in the campaign's text channel:

```
/tavern config rolling_mode hybrid
→ Bot: "✅ Rolling mode set to hybrid. Attack rolls and saving throws
        are interactive. Damage and initiative are automatic."

/tavern config reaction_window 10
→ Bot: "✅ Reaction window set to 10 seconds."

/tavern config rolling_mode fast
→ Bot: "❌ Invalid value for rolling_mode. Options: interactive, automatic, hybrid."

/tavern config
→ Bot posts current configuration as embed.
```

## Web Client Integration

The web client shows a settings panel accessible from the campaign view (gear icon). Only visible to the campaign owner. Settings are grouped by category (Gameplay, Session, Display). Changes are saved via the PATCH endpoint and take effect immediately.

## Defaults Rationale

| Setting | Default | Why |
|---|---|---|
| `rolling_mode: interactive` | The tabletop feel is Tavern's differentiator. Interactive rolling is the default because it delivers the core promise. Groups that want speed switch to `hybrid` or `automatic`. |
| `turn_timeout: 120` | Two minutes is generous by digital standards but normal for tabletop. Players who need to look up spell descriptions, discuss tactics, or read the scene need time. 30 seconds would punish new players. |
| `reaction_window: 15` | Long enough to read the roll result, check your spell slots, and decide. Short enough that combat does not stall. The "all pass" shortcut (ADR-0009) means engaged groups rarely wait the full 15 seconds. |
| `absent_character_mode: passive` | Passive is safer — an auto-controlled character might use resources the player was saving, or make tactical decisions the player disagrees with. Passive keeps the character out of harm's way until the player returns. |
| `ooc_prefix: //` | Universal convention in text-based RPG communities (MUDs, play-by-post, Discord RP servers). Double-slash is easy to type and unlikely to appear in natural game dialogue. |
| `show_party_status: true` | Most groups want to see HP at a glance after each turn. Groups that find it distracting can turn it off. |