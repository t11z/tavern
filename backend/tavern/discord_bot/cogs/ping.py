import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..config import BotConfig


class PingCog(commands.Cog):
    """Temporary cog providing /tavern ping. Will be merged into CampaignCog in V1."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    group = app_commands.Group(name="tavern", description="Tavern bot commands")

    @group.command(name="ping", description="Health check: bot and API connectivity")
    async def ping(self, interaction: discord.Interaction) -> None:
        config: BotConfig = self.bot.config  # type: ignore[attr-defined]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{config.tavern_api_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    api_status = "reachable" if resp.status == 200 else "unreachable"
        except Exception:
            api_status = "unreachable"
        await interaction.response.send_message(f"🏓 Pong! API: {api_status}")
