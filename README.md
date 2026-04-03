# 🍺 Tavern

**An AI Game Master for tabletop RPG campaigns — open source, self-hosted, and cheaper than a coffee.**

> A solo session runs ~$0.28 in API usage. Four players for three hours: ~$0.70.
> No subscription. No platform fees. Just your Anthropic API key and `docker compose up`.

Tavern is a self-hosted, SRD 5.2.1-compatible RPG engine powered by Claude as your Game Master. It handles the rules. Claude handles the story. Play in your browser, on your phone at the table, or in a Discord voice channel with friends.

---

## ✨ Features

- 🎲 **Full SRD 5e rules engine** — combat, spells, conditions, and character progression implemented in code, not in prompts
- 🧠 **Claude as Game Master** — narrative, NPC behaviour, and world reaction powered by Claude
- 🎭 **Two ways to play** — browser-based web client or Discord bot with voice support
- 💾 **Persistent campaigns** — state survives across sessions via PostgreSQL
- 👥 **Solo and multiplayer** — play alone or with a group in real-time
- 📱 **Table mode** — shared display on a laptop, each player on their phone
- 💸 **Cost-efficient** — prompt caching and mixed model routing keep API costs minimal
- 🐳 **One-command setup** — a single `docker compose up` is all it takes
- 🌍 **Community worlds** — import custom world presets or use the included Shattered Coast setting

---

## 🚀 Quickstart

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/)

### Run

```bash
git clone https://github.com/t11z/tavern
cd tavern
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
# Optionally add DISCORD_BOT_TOKEN for Discord integration
docker compose up
```

Open [http://localhost:3000](http://localhost:3000) and start your adventure.

---

## 🎮 How to Play

**In your browser**: Open the web client, create a campaign, build a character, and play. Solo or invite friends via join code.

**At the table**: Open the shared display on a laptop or TV. Each player joins on their phone by scanning a QR code. Claude narrates through the speakers.

**On Discord**: Add the Tavern bot to your server, start a campaign in a text channel, and play — Claude narrates as the GM.

Setup:
1. Create a Discord application at [discord.com/developers/applications](https://discord.com/developers/applications) and add a bot user.
2. Enable the **Message Content** privileged intent under *Bot → Privileged Gateway Intents*.
3. Copy the bot token and add it to your `.env` file: `DISCORD_BOT_TOKEN=your-token-here`
4. Run `docker compose up` — the `discord-bot` service starts automatically alongside the API.
5. Invite the bot to your server using the OAuth2 URL (scopes: `bot`, `applications.commands`; permissions: `Send Messages`, `Manage Threads`, `Read Message History`).

See [`docs/game-design/discord-bot.md`](docs/game-design/discord-bot.md) for the full command reference and gameplay guide.

---

## 🏗️ Architecture

Tavern is a headless game server with a client-agnostic API. The web client and Discord bot are two reference clients — both first-class, both maintained by the core team.

The server separates two concerns:

| Layer | Responsibility |
|---|---|
| **Rules Engine** | Deterministic SRD logic — dice, combat, spells, conditions |
| **Narrator** | Claude handles narration, NPC behaviour, world reaction |

Claude never sees raw rulebook text at runtime. It receives a structured state snapshot — character status, scene context, a rolling session summary — and responds as a narrator. The numbers come from your code.

**Cost optimisations built in:**
- Prompt caching for static context (system prompt, character sheet)
- Haiku for low-complexity responses, Sonnet for narration
- Rolling summary instead of full conversation history

See `docs/adr/` for the full set of architecture decision records.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.12+ / FastAPI
- **Database**: PostgreSQL 16+
- **Web Client**: React (Vite)
- **Discord Bot**: Python (discord.py)
- **LLM**: Anthropic API (provider-abstracted)
- **Deployment**: Docker Compose

---

## 📥 SRD Import Pipeline

Tavern includes a one-time import pipeline to seed the rules database from the official SRD PDF, assisted by Claude:

```bash
python scripts/srd_import/run_pipeline.py --input srd/SRD_CC_v5_2_1.pdf
```

On SRD updates, a GitHub Actions workflow parses the new document, generates a diff, and opens a pull request for human review before any changes reach the engine.

---

## 📜 License & Attribution

Tavern is licensed under the [Apache License 2.0](LICENSE).

This work includes material from the System Reference Document 5.2.1 ("SRD 5.2.1") by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2.1 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode.

This product is *5E compatible*.

---

## 🤝 Contributing

Contributions welcome. Architecture decisions are documented in `docs/adr/`. Please read them before proposing changes — accepted ADRs are binding constraints.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.