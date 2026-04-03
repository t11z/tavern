# Quickstart

Get Tavern running in under five minutes.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/)

## Run

```bash
git clone https://github.com/t11z/tavern
cd tavern
cp .env.example .env
```

Open `.env` and add your API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Then start everything:

```bash
docker compose up
```

Open [http://localhost:3000](http://localhost:3000) and start your adventure.

## Optional: Discord Bot

If you want to play via Discord, add your bot token to `.env`:

```
DISCORD_BOT_TOKEN=your-bot-token-here
```

The bot starts automatically alongside the game server. See the [Discord Developer Portal](https://discord.com/developers/applications) to create a bot application and obtain a token.

## What Happens on First Start

1. PostgreSQL initializes and creates the database.
2. Alembic runs migrations to set up the schema.
3. The game server starts on port 3000.
4. The web client is served at the root URL.
5. If a Discord bot token is configured, the bot connects to Discord.

No SRD data is loaded on first start — the rules database is empty until you run the import pipeline. You can still create campaigns and characters, but spell data, monster stats, and class features will be populated as the import pipeline is developed.

## Next Steps

- [How to Play](how-to-play.md) — the three play scenarios explained
- [Character Creation](game-design/character-creation.md) — how characters are built
- [The Shattered Coast](game-design/worlds/shattered-coast.md) — the included starter world
- [Contributing](contributing.md) — how to get involved