# Game Design Spec: Discord Bot

- **Status**: Accepted
- **Date**: 2026-04-03
- **Author**: [@t11z](https://github.com/t11z)
- **Scope**: `backend/tavern/discord_bot/` — interaction design, command surface, channel management, embed layout, voice overlay, multiplayer coordination, interactive rolling
- **References**: ADR-0003 (Tech Stack), ADR-0004 (Campaign Lifecycle), ADR-0005 (Client Architecture), ADR-0006 (Auth), ADR-0007 (Multiplayer), ADR-0008 (Voice Pipeline), ADR-0009 (Interactive Dice Rolling)

## Design Principles

### Text-First, Voice-Optional

Every game interaction — campaign management, character creation, turn submission, dice rolling, reactions — works fully through text channels. No player is ever required to join a voice channel. Voice is an optional overlay that adds STT input and TTS output on top of the text baseline. See ADR-0008 for voice architecture.

### Bot-Managed Channels

The bot creates and manages Discord channels for campaigns. Players do not manually create channels or configure permissions. The bot handles channel lifecycle — creation, permission scoping, archival, deletion. This reduces friction and ensures correct configuration.

### Tabletop Feel

Dice rolling is player-triggered. Reactions are prompted interactively. Combat flows through initiative order with turn prompts. The Discord experience replicates the cadence of sitting at a table, not the feel of watching an automated resolver. See ADR-0009 for the interactive rolling architecture.

## Bot Identity

The bot appears as **Tavern** with the Tavern logo as avatar. It posts narrative responses as its own messages, creating the feel that the bot is the Game Master. System messages (errors, turn prompts, session management) use plain text or minimal embeds to distinguish them from narrative content. The bot has no personality of its own — it is a transparent conduit to Claude's narrator.

## Player Journeys

### Journey 1: Text-Only Group

```
1. GATHER
   Owner (in any channel): /lfg "Shattered Coast, Saturday 8pm, Level 1"
   Bot posts LFG embed with Join button + details
   Alice clicks ⚔️ Join
   Bob clicks ⚔️ Join
   Embed updates: "3/5 players: Owner, Alice, Bob"

2. LAUNCH
   Owner: /tavern launch (or clicks Launch button on embed)
   Bot creates:
     📁 Category: "Tavern: Shattered Coast"
       💬 #shattered-coast
       🔊 shattered-coast-voice (created but unused in text-only)
   Bot sets permissions: only campaign members can see/post
   Bot posts session banner in #shattered-coast
   Bot asks: "Move everyone to the new channel?" [Yes] [No]

3. CREATE CHARACTERS
   Bot posts: "Create your characters! Use /character create"
   Each player runs /character create
   Bot opens a thread per player for guided creation (Path 1)
   Claude walks each player through class, species, background...
   On completion: character sheet embed posted in main channel

4. PLAY
   Channel is now in Game Mode — messages are in-character actions
   
   Alice types: "I look around the tavern"
   Bot submits turn → typing indicator → Claude narrates
   Bot posts narrative as message + mechanical embed if relevant

   // OOC messages with // or (parentheses) are ignored
   Bob types: // brb 5 min
   Bot ignores this

5. COMBAT
   Encounter triggers → Bot posts initiative order embed
   Bot: "⚔️ It's Kael's turn!" (@mentions Kael's player)
   
   Alice types: "I attack the goblin with my sword"
   Bot: "⚔️ Kael attacks Goblin A — Roll for attack! (d20+5 vs AC 15)"
        [🎲 Roll] [⚡ Reckless Attack + Roll]
   Alice clicks 🎲 Roll
   Bot: "🎲 Kael rolls: 14 (d20) + 5 = 19 vs AC 15 — Hit!"
        "Roll for damage! (2d6+3 slashing)"
        [🎲 Roll]
   Alice clicks 🎲 Roll
   Bot: "🎲 Damage: 4+2 (2d6) + 3 = 9 slashing"
   Claude narrates: "Your blade catches the goblin across its ribs..."
   Bot posts mechanical results embed

   --- Reaction example ---
   Bot: "⚔️ Goblin A attacks Mira! 🎲 17+4 = 21 vs AC 15 — Hit!"
        ⚡ REACTIONS (15s)
        Mira: [🛡️ Shield] [⏭️ Pass]
        Vex: [🎵 Silvery Barbs] [⏭️ Pass]
   Mira clicks 🛡️ Shield
   Bot: "🛡️ Mira casts Shield! AC → 20. 21 vs 20 — still hits."
        Vex: [🎵 Silvery Barbs] [⏭️ Pass] (15s)
   Vex clicks 🎵 Silvery Barbs
   Bot: "🎵 Vex casts Silvery Barbs! Goblin rerolls: 8+4 = 12 vs 20 — Miss!"
   Claude narrates the scene

6. END SESSION
   Owner: /tavern stop
   Bot posts session summary (turns, time, highlights)
   Channel exits Game Mode — normal chat resumes
   Channels persist for between-session discussion

7. END CAMPAIGN
   Owner: /tavern end → confirmation prompt
   Bot posts campaign summary
   Bot: "Archive channels?" [📁 Archive (read-only, delete in 30d)] [🗑️ Delete now] [📌 Keep]
```

### Journey 2: Voice Group

Steps 1-3 are identical to Journey 1. The difference begins at step 4:

```
4. ENABLE VOICE
   Players join 🔊 shattered-coast-voice
   Any player: /tavern voice on
   Bot joins the voice channel
   Bot posts: "🎤 Voice enabled — speak or type your actions"

5. PLAY WITH VOICE
   Alice SPEAKS: "I look around the tavern"
   Bot transcribes via STT
   Bot posts echo: > 🎤 Alice: I look around the tavern
   Bot submits as turn (identical to typed)
   Claude narrates → text posted in channel AND spoken via TTS

   Bob has no mic, TYPES: "I check the door for traps"
   Processed identically — Bob hears TTS output, reads text

6. COMBAT WITH VOICE
   Roll prompts appear in text channel (same as Journey 1)
   Players can speak "/roll" or click the button — both work
   Reaction prompts appear as embeds with buttons (not voice-triggered)
   Claude's narrative plays as TTS + posted as text

7. DISABLE VOICE (anytime)
   Any player: /tavern voice off
   Bot leaves voice channel
   Game continues text-only — no interruption
```

### Journey 3: Hybrid Group (some voice, some text)

```
Setup: Alice and Bob in voice channel. Charlie on mobile, text only.

- Alice speaks actions → echoed in text, Charlie reads them
- Bob speaks actions → same
- Charlie types actions → Alice and Bob hear TTS narrative, Charlie reads it
- Roll prompts: everyone uses text-channel buttons (voice does not replace UI)
- Reaction windows: everyone sees embeds in text channel, clicks buttons
- No player is disadvantaged. No player misses content.
```

### Journey 4: Late Joiner

```
Campaign is mid-session. Owner invites Dave.

Owner: /tavern invite @Dave
Bot: "Dave has been invited to Shattered Coast!"
Dave can now see #shattered-coast
Bot (to Dave): "Welcome! Use /character create to join the adventure."
Bot (to Dave): DMs a brief recap (last 5 turns summary)
Dave creates character → joins the session
Bot informs Claude: "A new adventurer appears..."
Claude narrates Dave's entrance
```

## Channel Architecture

### Bot-Managed Channel Lifecycle

The bot creates and manages all campaign-related channels. The server operator grants the bot `Manage Channels` and `Move Members` permissions.

**On campaign launch** (`/tavern launch`):

1. Bot creates a Category named "Tavern: [Campaign Name]"
2. Bot creates a text channel `#[campaign-slug]` under the category
3. Bot creates a voice channel `[campaign-name]-voice` under the category
4. Bot sets permissions: category visible only to campaign members + bot
5. Bot posts session banner and character creation prompt in the text channel
6. Bot offers to move players to the new channel

**Permission model:**

| Who | Text channel | Voice channel |
|---|---|---|
| Campaign members | Read + Write | Connect + Speak |
| Bot | Read + Write + Manage Messages + Embed Links | Connect + Speak + Move Members |
| Everyone else | Hidden | Hidden |

**Fallback if bot lacks Manage Channels permission:**

The bot detects missing permissions on startup and disables channel management. In this mode, it falls back to manual binding: the owner creates channels manually and uses `/tavern bind #channel` to bind a campaign to an existing channel. The bot posts a warning: "I don't have permission to create channels. Ask a server admin to grant Manage Channels, or use /tavern bind."

### Channel Lifecycle After Campaign

| Event | Bot action |
|---|---|
| `/tavern stop` (session pause) | Channels persist. Game Mode deactivated. Normal chat resumes. |
| `/tavern start` (session resume) | Game Mode reactivated in existing channels. |
| `/tavern end` (campaign complete) | Bot asks: Archive / Delete / Keep. |
| Archive chosen | Channels set to read-only. Deleted after 30 days. |
| Delete chosen | Channels deleted immediately. |
| Keep chosen | Channels persist as normal channels. Bot removes campaign binding. |
| Bot removed from server | Channels persist but lose bot-managed permissions. No cleanup. |

### Multi-Campaign per Server

A server can run multiple campaigns. Each gets its own category with its own channels. The bot tracks campaign-channel bindings in memory, recovered from the API on restart. No limit on concurrent campaigns beyond Discord's 500-channel-per-server limit.

## Slash Command Surface

### Group Formation

| Command | Description | Who |
|---|---|---|
| `/lfg <description>` | Post a Looking For Group embed. Description includes world, schedule, level, player count. Other users join by clicking the ⚔️ button. | Anyone |
| `/tavern launch` | Launch the campaign from an LFG post. Creates channels, binds campaign, starts session. Can also be triggered from the LFG embed's Launch button. | LFG creator (becomes owner) |

### Campaign Management

| Command | Description | Who |
|---|---|---|
| `/tavern start` | Resume a paused campaign session. Reactivates Game Mode in the bound channel. | Owner |
| `/tavern stop` | Pause the session. Saves state. Deactivates Game Mode. | Owner |
| `/tavern end` | Permanently end the campaign. Posts summary. Offers channel cleanup. | Owner |
| `/tavern invite @user` | Invite a player mid-campaign. Grants channel access. | Owner |
| `/tavern kick @user` | Remove a player. Revokes channel access. | Owner |
| `/tavern status` | Campaign status: name, world, session count, players, scene summary. | Any member |
| `/tavern config <key> <value>` | Configure campaign settings (e.g., `rolling_mode interactive\|automatic\|hybrid`). | Owner |
| `/tavern bind #channel` | Manually bind a campaign to an existing channel (fallback mode). | Owner |

### Character Management

| Command | Description | Who |
|---|---|---|
| `/character create` | Start character creation. Opens guided conversation in a thread (Path 1). | Any member |
| `/character sheet` | Post your character sheet as embed. | Any member |
| `/character sheet @user` | View another player's character sheet. | Any member |
| `/character inventory` | Detailed inventory embed. | Any member |
| `/character spells` | Spells and spell slots embed. | Spellcasters |

### Gameplay

| Command | Description | Who |
|---|---|---|
| `/roll` | **Context-dependent.** If a turn roll is pending: triggers the pending roll (no expression needed). If no roll is pending: requires a dice expression (e.g., `/roll 2d6+3`) for a standalone roll. | Any member |
| `/action <text>` | Explicitly submit an action. Equivalent to typing in the channel. | Active player |
| `/pass` | Pass on a reaction during a reaction window. | Player with pending reaction |
| `/history [n]` | Last N turns as condensed embed (default: 5). | Any member |
| `/recap` | Narrative recap from Claude (Haiku call). | Any member |
| `/map` | Current scene description and points of interest (text-based). | Any member |

### Voice Control

| Command | Description | Who |
|---|---|---|
| `/tavern voice on` | Enable voice. Bot joins voice channel. STT + TTS activate. | Any member |
| `/tavern voice off` | Disable voice. Bot leaves voice channel. | Any member |
| `/tavern voice status` | Voice status: channel, providers, players in voice. | Any member |

### Meta

| Command | Description | Who |
|---|---|---|
| `/tavern help` | Available commands + documentation link. | Anyone |
| `/tavern ping` | Health check (bot + API connectivity). | Anyone |

## Interactive Rolling in Discord

### Roll Prompts

When the engine requires a roll (ADR-0009), the bot posts an embed with action buttons:

```
┌──────────────────────────────────────────┐
│ ⚔️ Kael attacks Goblin A                 │
│ Roll for attack! (d20 + 5 vs AC 15)     │
│                                          │
│ [🎲 Roll] [⚡ Reckless Attack + Roll]    │
│                                          │
│ ⏱️ 120s                                  │
└──────────────────────────────────────────┘
```

Only the active player's button clicks are accepted. Other players see the embed but cannot interact.

### Roll Results

```
┌──────────────────────────────────────────┐
│ 🎲 Kael rolls for attack                 │
│                                          │
│ 🎲 14 (d20) + 5 = 19 vs AC 15 — HIT!   │
│                                          │
│ Roll damage! (2d6 + 3 slashing)          │
│ [🎲 Roll]                                │
└──────────────────────────────────────────┘
```

Critical hits (natural 20) and critical misses (natural 1) get distinct styling — gold border for crits, red for fumbles.

### Reaction Windows

When the engine opens a reaction window, the bot posts an embed that tags eligible reactors:

```
┌──────────────────────────────────────────┐
│ ⚡ REACTIONS AVAILABLE                    │
│                                          │
│ Goblin A attacks Mira                    │
│ 🎲 17+4 = 21 vs AC 15 — Hit             │
│                                          │
│ @Mira:                                   │
│ [🛡️ Shield (+5 AC, 1st-level slot)]     │
│                                          │
│ @Vex:                                    │
│ [🎵 Silvery Barbs (force reroll, 1st)]  │
│                                          │
│ [⏭️ All pass — skip]                    │
│ ⏱️ 15s                                   │
└──────────────────────────────────────────┘
```

Each player can only click their own buttons. The embed updates live as reactions are used — showing the updated outcome and remaining options.

When a reaction chains (Shield → still hit → Silvery Barbs available), the embed updates in-place rather than posting a new message. This keeps the channel clean.

### NPC Reactions

NPC reactions are displayed as bot messages within the reaction window:

```
Bot: ⚡ The Lich casts Counterspell on Kael's Fireball!
     Counterspell: auto-succeeds against a 3rd-level spell.

     @Kael: [🔮 Counterspell (counter the Counterspell, 3rd-level slot)] [⏭️ Pass]
     ⏱️ 15s
```

### Saving Throws

When multiple players must save (e.g., Fireball), the bot processes them sequentially:

```
Bot: 🔥 Fireball! DEX save DC 15.
     Goblin A: 🎲 8+1 = 9 — Fail (auto-rolled)
     Goblin B: 🎲 16+1 = 17 — Save (auto-rolled)
     
     @Kael: DEX save DC 15 (d20+2) — Your turn!
     [🎲 Roll]
```

NPC saves are auto-rolled and shown for transparency. Player saves are interactive.

## Embed Design

### Narrative Response

Claude's narrative text is posted as a **regular message** (not an embed). Long narratives are split at sentence boundaries at the 2000-character Discord limit. This keeps the feel natural — like a person speaking in the channel.

### Mechanical Results Embed

Attached to the narrative message:

```
┌──────────────────────────────────────────┐
│ ⚔️ Combat Results                        │
│                                          │
│ Kael (Fighter) → Goblin A               │
│ Attack: 19 (14+5) vs AC 15 — Hit        │
│ Damage: 9 slashing (4+2+3)              │
│ Goblin A: 0 HP — Defeated               │
│                                          │
│ 📊 Party Status                          │
│ Kael: 38/38 HP · Mira: 24/28 HP         │
└──────────────────────────────────────────┘
```

Colour-coded: green for successful actions, red for damage taken, amber for status effects.

### Character Sheet Embed

```
┌──────────────────────────────────────────┐
│ 🛡️ Kael Stormblade                      │
│ Level 3 Human Fighter (Champion)         │
│──────────────────────────────────────────│
│ HP: ████████░░ 32/38                     │
│ AC: 18 · Speed: 30ft                     │
│                                          │
│ STR 16(+3)  DEX 14(+2)  CON 14(+2)      │
│ INT 10(+0)  WIS 12(+1)  CHA  8(-1)      │
│                                          │
│ Conditions: None                         │
│ Equipment: Longsword, Shield, Chain Mail │
└──────────────────────────────────────────┘
```

### LFG Embed

```
┌──────────────────────────────────────────┐
│ 🎲 Looking for Adventurers!              │
│                                          │
│ 🌍 Shattered Coast · ⚔️ Level 1         │
│ 📅 Saturday 20:00 CET                    │
│ 👥 2/5 players: Owner, Alice             │
│                                          │
│ [⚔️ Join] [🚀 Launch (owner only)]      │
└──────────────────────────────────────────┘
```

Updates live as players join.

## Game Mode

When a session is active, the bound text channel enters **Game Mode**. The bot signals this with:

1. A pinned session banner embed showing campaign name, active players, and "Game Mode Active"
2. Channel topic updated to "[Campaign Name] — Game in progress"

**In Game Mode:**

- Player messages are intercepted as in-character actions
- Messages starting with `//` or wrapped in `(parentheses)` are OOC and ignored
- The bot posts narrative responses and mechanical embeds
- Roll prompts and reaction windows appear as interactive embeds

**Outside Game Mode:**

- The channel is a normal Discord channel
- The bot does not intercept messages
- Players can chat freely about the campaign between sessions

The transition is explicit and visible — players always know whether they are "in game."

## Character Creation

Path 1 (guided conversation with Claude) in a thread off the `/character create` message. Claude asks one question at a time. The creating player responds in the thread. On completion, the bot posts the character sheet in the main channel and archives the thread.

Path 2 (direct form via Discord modals) is deferred to V2.

## Bot Architecture (Internal)

### Cog Structure

| Cog | Responsibility |
|---|---|
| `LFGCog` | `/lfg` command. LFG embed posting, join tracking, launch trigger. |
| `CampaignCog` | `/tavern` commands. Channel creation/management, session start/stop/end, invites. |
| `CharacterCog` | `/character` commands. Creation thread management, sheet embeds. |
| `GameplayCog` | `/roll`, `/action`, `/pass`, `/history`, `/recap`, `/map`. Message interception. Roll prompt rendering. Reaction window rendering. |
| `VoiceCog` | `/tavern voice` commands. Voice channel join/leave, STT/TTS pipeline. Loaded conditionally (ADR-0008). |
| `WebSocketCog` | WebSocket connection to Tavern API. Event dispatch to other cogs. |

### State Management

The bot holds minimal local state, all recoverable from the API on restart:

| State | Purpose |
|---|---|
| Channel → Campaign binding | Route messages to correct campaign |
| Discord user → Tavern user mapping | Attribute actions to correct character |
| Active session flag per channel | Know whether to intercept messages |
| Pending roll state per channel | Know whether `/roll` is a turn-roll or standalone |
| Active reaction windows | Track which players still need to respond |
| Voice channel association | Where to send/receive audio |

No local database. No persistent storage. The bot is stateless with respect to game state — everything lives in the Tavern API.

### Error Handling

| Error | Behaviour |
|---|---|
| Tavern API unreachable | Error message in channel. Retry with backoff. |
| WebSocket disconnected | Reconnect with backoff. Warning if > 5s. |
| Missing channel permissions | Warn and fall back to manual binding mode. |
| Player not in campaign | "You're not part of this campaign. Ask the owner to invite you." |
| Turn submitted out of order | "It's not your turn — waiting for [character]." |
| Roll triggered with no pending roll | "No roll pending. Use `/roll <expression>` for a standalone roll." |
| Reaction window expired | Auto-pass, proceed to resolution. |

### Discord Rate Limit Handling

- Defer slash command responses immediately, follow up async
- Batch rapid WebSocket events into single embed updates
- Update reaction embeds in-place rather than posting new messages
- Maximum 5 messages per 5 seconds per channel

## Deployment

Separate container in Docker Compose (ADR-0003). Optional — not started without `DISCORD_BOT_TOKEN`. Voice dependencies included but `VoiceCog` only loads if libraries are available.

```yaml
services:
  discord-bot:
    build: ./backend
    command: python -m tavern.discord_bot
    environment:
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - TAVERN_API_URL=http://tavern-server:8000
      - TAVERN_WS_URL=ws://tavern-server:8000
      - STT_PROVIDER=${STT_PROVIDER:-}
      - STT_API_KEY=${STT_API_KEY:-}
      - TTS_PROVIDER=${TTS_PROVIDER:-}
      - TTS_API_KEY=${TTS_API_KEY:-}
    depends_on:
      - tavern-server
    restart: unless-stopped
```

## V1 Scope

### Included

- `/lfg` group formation with join buttons
- Bot-managed channel creation (category + text + voice)
- All campaign management commands
- Text-based turn submission (message interception + `/action`)
- Interactive dice rolling with pre-roll options (ADR-0009)
- Reaction windows with buttons (self, cross-player, NPC)
- Narrative response posting (complete, not streamed)
- Mechanical results as embeds
- Character creation (Path 1, threaded)
- Character sheet / inventory / spell embeds
- Combat turn prompts with initiative tracking
- OOC message filtering
- Game Mode activation/deactivation
- Discord OAuth identity mapping
- Configurable rolling mode (interactive / automatic / hybrid)

### Deferred to V2

- Voice input (STT) and voice output (TTS)
- Character creation via modal forms (Path 2)
- Streaming narrative (progressive message editing)
- Campaign creation wizard with full world/tone selection UI
- Battle map rendering
- Channel fallback if permissions are missing (functional but not polished)

### Explicitly Not Planned

- Bot-to-bot federation
- In-Discord character sheet editing
- Thread-per-scene
- Reaction-based action selection (too limiting for free-form RP)
- Voice-triggered rolls (rolls are always via text button/command)