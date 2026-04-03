# How to Play

Tavern supports three play scenarios. All three are first-class experiences — the game server doesn't care how you connect.

## At Your Desk

The simplest way to play. Open the web client in your browser, create a campaign, build a character, and start playing.

**Solo play**: You and Claude. No setup beyond the [Quickstart](quickstart.md). Create a campaign, choose your tone and parameters, build a character through the guided conversation or the direct form, and begin your adventure.

**Invite friends**: Generate a join link from the campaign settings. Share it with your group. Each player opens the link, creates their character, and joins the session. Everyone sees the same narration in real-time. Combat follows initiative order — each player is prompted when it's their turn.

## At the Table

The full tabletop experience, digitized. A shared display at the head of the table shows the game. Each player uses their phone.

**Setup:**

1. Open the web client on a laptop or TV connected to the table. Switch to shared display mode — a read-only view optimized for readability at distance, showing narration, party status, and (eventually) the battle map.
2. Each player opens the web client on their phone. They join the campaign by scanning a QR code or entering a short join code displayed on the shared screen.
3. Each phone shows the player's personal character sheet, action input, and a compact chat view.

**Voice** (optional): Connect a speaker to the laptop. Claude's narration can be read aloud via text-to-speech — the browser's built-in TTS, or a higher-quality service if you prefer. Players speak their actions naturally; a microphone captures speech and converts it to text.

The shared display doesn't accept input — it's purely a visual anchor for the group. All actions come from individual phones.

## On Discord

For groups that already live on Discord. No browser needed.

**Setup:**

1. Add the Tavern bot to your Discord server. (The bot runs as part of your Tavern Docker Compose stack — see [Quickstart](quickstart.md).)
2. Create a text channel for the campaign. The bot posts narration, combat status, and turn prompts here.
3. Join a voice channel. The bot joins too — Claude speaks as your GM through voice, and you can speak your actions instead of typing them.

**Playing:**

- Type actions in the text channel, or speak them in the voice channel.
- The bot posts Claude's narrative responses as messages. In the voice channel, Claude speaks them aloud.
- Character sheets are accessible via slash commands or message embeds.
- In combat, the bot announces whose turn it is and waits for their action. If a player takes too long (default: 2 minutes), their character takes the Dodge action automatically.

**Player identity**: Discord users are mapped to Tavern users via Discord OAuth. Your Discord account is your Tavern account — no separate registration.

## Campaign Settings

Before starting a campaign, you choose a few parameters that shape the experience:

**Required:**

| Parameter | Options |
|---|---|
| Tone | Heroic Fantasy, Dark & Gritty, Lighthearted & Humorous, Mystery & Intrigue, Eldritch Horror — or write your own |
| Campaign Length | One-Shot (1 session), Short (3-5 sessions), Full Campaign (10+) |

**Optional (Claude fills in if you skip):**

| Parameter | Options |
|---|---|
| Setting Type | Coastal City, Underground, Wilderness, Political Court, Planar, Surprise Me |
| Play Focus | Combat-heavy, Roleplay-heavy, Exploration-heavy, Balanced |
| Difficulty | Forgiving, Balanced, Deadly |

You can also choose a world preset — like the included [Shattered Coast](game-design/worlds/shattered-coast.md) — or let Claude generate a unique world from your parameters.

## Creating a Character

Two paths, your choice:

**Guided conversation**: Claude asks what kind of hero you envision and walks you through species, class, background, ability scores, and equipment as an in-character conversation. Takes about 5-10 minutes. Great for new players or anyone who enjoys the roleplay of character creation.

**Direct form**: Dropdowns, sliders, and checkboxes. Pick your options, assign your scores, confirm. Takes about 2 minutes. For players who know exactly what they want.

Both paths produce the same validated character. See [Character Creation](game-design/character-creation.md) for the full details.

## During Play

**Exploration**: Free-form. Type (or say) what your character does. Claude narrates the result. In multiplayer, anyone can act — first come, first served, like conversation at a real table.

**Combat**: Turn-based. The rules engine rolls initiative and establishes the order. On your turn, you declare your action. The engine resolves the mechanics (attack rolls, damage, saves). Claude narrates what happens. Then the next player goes. NPC turns are handled automatically — Claude decides what they do, the engine resolves the outcome.

**Between sessions**: Just close the tab (or leave the Discord channel). Every turn is saved automatically. When you come back — hours, days, or weeks later — Claude picks up where you left off with a brief recap of recent events.

## Costs

Tavern runs on the Anthropic API. The server operator provides the API key and bears the cost. Players don't need their own API keys.

Typical costs per session:

| Scenario | Estimated Cost |
|---|---|
| Solo, 3 hours | ~$0.28 |
| 4 players, 3 hours | ~$0.70 |

These estimates assume prompt caching and mixed model routing (Sonnet for narration, Haiku for mechanical responses). Actual costs vary with session length and narrative complexity.