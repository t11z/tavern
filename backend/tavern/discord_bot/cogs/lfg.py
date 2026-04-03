"""LFG (Looking For Group) cog.

Implements the /lfg command and the group-formation flow described in the
discord-bot game design spec, Journey 1 steps 1–2:

    /lfg <description>
      → Posts an embed with ⚔️ Join and 🚀 Launch buttons.
      → Join toggles the player in/out of the party.
      → Launch (creator only) creates campaign + channels and posts the
        session banner.

In-memory state:  LFGCog.sessions maps message_id → LFGSession.
State is lost on bot restart; players must re-post /lfg.  Persistent
views (across restarts) are deferred to V2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds.lfg import build_lfg_embed
from ..models.state import BotState, ChannelBinding
from ..services.api_client import TavernAPI, TavernAPIError
from ..services.channel_manager import ChannelManager

logger = logging.getLogger(__name__)

# LFG views expire after 24 hours of inactivity so Discord cleans up the
# buttons.  For a truly persistent view, re-register on bot startup (V2).
_VIEW_TIMEOUT_SECONDS = 86_400


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class LFGSession:
    """Tracks the state of a single LFG post."""

    message_id: int
    creator_id: int
    creator_name: str
    description: str
    # Parallel lists — index i is (joined_user_ids[i], joined_user_names[i]).
    # The creator is always first and cannot be removed.
    joined_user_ids: list[int] = field(default_factory=list)
    joined_user_names: list[str] = field(default_factory=list)

    def add_player(self, user_id: int, display_name: str) -> None:
        if user_id not in self.joined_user_ids:
            self.joined_user_ids.append(user_id)
            self.joined_user_names.append(display_name)

    def remove_player(self, user_id: int) -> None:
        """Remove a non-creator player (idempotent)."""
        if user_id == self.creator_id:
            return
        try:
            idx = self.joined_user_ids.index(user_id)
            self.joined_user_ids.pop(idx)
            self.joined_user_names.pop(idx)
        except ValueError:
            pass

    def toggle_player(self, user_id: int, display_name: str) -> None:
        if user_id in self.joined_user_ids:
            self.remove_player(user_id)
        else:
            self.add_player(user_id, display_name)

    @property
    def all_players(self) -> list[str]:
        """Display names of all joined players, creator first."""
        return self.joined_user_names


# ---------------------------------------------------------------------------
# Discord UI View
# ---------------------------------------------------------------------------


class LFGView(discord.ui.View):
    """Buttons attached to an LFG embed."""

    def __init__(self, cog: LFGCog, session: LFGSession) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="⚔️ Join", style=discord.ButtonStyle.primary)
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.session.toggle_player(interaction.user.id, interaction.user.display_name)
        embed = build_lfg_embed(
            self.session.description,
            self.session.creator_name,
            self.session.all_players,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🚀 Launch", style=discord.ButtonStyle.success)
    async def launch_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.session.creator_id:
            await interaction.response.send_message(
                "Only the campaign creator can launch.", ephemeral=True
            )
            return

        await self._launch(interaction)

    async def _launch(self, interaction: discord.Interaction) -> None:
        """Create the campaign and channels, then post the session banner."""
        await interaction.response.defer(thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Cannot launch outside a server.", ephemeral=True)
            return

        # 1. Create campaign via API.
        campaign_name = self.session.description[:100]
        try:
            campaign = await self.cog.api.create_campaign({"name": campaign_name})
        except TavernAPIError as exc:
            logger.error("Failed to create campaign: %s", exc)
            await interaction.followup.send(
                f"❌ Failed to create campaign: {exc.message}", ephemeral=True
            )
            return

        campaign_id = campaign["id"]

        # 2. Create Discord channels.
        result = await self.cog.channel_manager.create_campaign_channels(
            guild=guild,
            campaign_name=campaign_name,
            member_ids=self.session.joined_user_ids,
            bot_user=interaction.client.user,
        )
        if result is None:
            await interaction.followup.send(
                "❌ I don't have permission to create channels. "
                "Ask a server admin to grant **Manage Channels**, or use `/tavern bind`.",
                ephemeral=True,
            )
            return

        category, text_channel, _voice_channel = result

        # 3. Update bot state.
        from uuid import UUID

        self.cog.state.bind_channel(
            ChannelBinding(
                channel_id=text_channel.id,
                campaign_id=UUID(campaign_id),
                guild_id=guild.id,
            )
        )
        self.cog.state.set_game_mode(text_channel.id)

        # 4. Post session banner in the new text channel.
        player_list = ", ".join(self.session.all_players) or "No players yet"
        banner = discord.Embed(
            title=f"⚔️ {campaign_name}",
            description=(
                "The adventure begins! Use `/character create` to create your character.\n\n"
                "Messages in this channel are **in-character actions**.\n"
                "Prefix OOC messages with `//` or wrap them in `(parentheses)`."
            ),
            colour=discord.Colour(0xD4A24E),
        )
        banner.add_field(name="👥 Party", value=player_list, inline=False)
        banner.set_footer(text="Game Mode Active")
        await text_channel.send(embed=banner)

        # 5. Reply to the interaction with a move offer.
        move_view = _MoveView(text_channel)
        await interaction.followup.send(
            f"✅ Campaign launched! Head to {text_channel.mention}",
            view=move_view,
        )

        # Remove the session from the cog's registry.
        self.cog.sessions.pop(self.session.message_id, None)
        self.stop()


class _MoveView(discord.ui.View):
    """Offers to jump the user to the new campaign channel."""

    def __init__(self, text_channel: discord.TextChannel) -> None:
        super().__init__(timeout=60)
        self.add_item(
            discord.ui.Button(
                label="Move me there",
                style=discord.ButtonStyle.link,
                url=text_channel.jump_url,
            )
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class LFGCog(commands.Cog):
    """Looking For Group command and group-formation flow."""

    def __init__(
        self,
        bot: commands.Bot,
        api: TavernAPI,
        channel_manager: ChannelManager,
        state: BotState,
    ) -> None:
        self.bot = bot
        self.api = api
        self.channel_manager = channel_manager
        self.state = state
        # Maps message_id → LFGSession for all live LFG posts.
        self.sessions: dict[int, LFGSession] = {}

    @app_commands.command(
        name="lfg",
        description="Post a Looking For Group listing and gather players.",
    )
    @app_commands.describe(description="Campaign description: world, schedule, level, etc.")
    async def lfg(self, interaction: discord.Interaction, description: str) -> None:
        """Post an LFG embed with Join and Launch buttons."""
        session = LFGSession(
            message_id=0,  # filled in after send
            creator_id=interaction.user.id,
            creator_name=interaction.user.display_name,
            description=description,
        )
        # Creator joins automatically.
        session.add_player(interaction.user.id, interaction.user.display_name)

        embed = build_lfg_embed(description, interaction.user.display_name, session.all_players)
        view = LFGView(self, session)

        await interaction.response.send_message(embed=embed, view=view)

        # Capture the message ID now that it has been sent.
        msg = await interaction.original_response()
        session.message_id = msg.id
        self.sessions[msg.id] = session
