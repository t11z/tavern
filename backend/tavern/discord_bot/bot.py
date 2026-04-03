import logging

import discord
from discord.ext import commands

from .config import BotConfig

logger = logging.getLogger(__name__)


class TavernBot(commands.Bot):
    """Discord bot client for Tavern.

    Intents: message_content, guilds, members.
    Cogs are loaded in setup_hook; slash commands are synced globally on startup.
    """

    def __init__(self, config: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config

    async def setup_hook(self) -> None:
        from .cogs.ping import PingCog

        await self.add_cog(PingCog(self))
        await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Tavern bot ready. Guilds: %d", len(self.guilds))
