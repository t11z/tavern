import logging

import discord
from discord.ext import commands

from .config import BotConfig
from .models.state import BotState
from .services.api_client import TavernAPI
from .services.channel_manager import ChannelManager

logger = logging.getLogger(__name__)


class TavernBot(commands.Bot):
    """Discord bot client for Tavern.

    Intents: message_content, guilds, members.
    Cogs are loaded in setup_hook; slash commands are synced globally on startup.

    Shared services (api, channel_manager, state) are attached to the bot
    instance so cogs can access them without circular imports.
    """

    def __init__(self, config: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.api = TavernAPI(config.tavern_api_url)
        self.channel_manager = ChannelManager()
        self.state = BotState()

    async def setup_hook(self) -> None:
        from .cogs.campaign import CampaignCog
        from .cogs.character import CharacterCog
        from .cogs.gameplay import GameplayCog
        from .cogs.lfg import LFGCog
        from .cogs.websocket import WebSocketCog
        from .services.identity import IdentityService

        identity = IdentityService(self.api)
        await self.add_cog(CampaignCog(self, self.api, self.channel_manager, self.state, identity))
        await self.add_cog(LFGCog(self, self.api, self.channel_manager, self.state))
        await self.add_cog(WebSocketCog(self, self.api, self.config.tavern_ws_url))
        await self.add_cog(GameplayCog(self, self.api, self.state, identity))
        await self.add_cog(CharacterCog(self, self.api, self.state, identity))
        await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Tavern bot ready. Guilds: %d", len(self.guilds))

    async def close(self) -> None:
        await self.api.aclose()
        await super().close()
