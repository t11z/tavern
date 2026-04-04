"""Character cog — /character subcommands and guided creation threads.

Commands:
    /character create     Start guided (Path 1) character creation in a thread
    /character sheet      Post your character sheet (or another player's)
    /character inventory  Detailed equipment embed
    /character spells     Spells and spell-slot embed

Creation flow:
    1. /character create → bot opens a thread named "{user}'s Character"
    2. Bot posts Claude's first question (from the API) in the thread
    3. Player replies in the thread; bot forwards each message to the API
    4. API replies with Claude's next question or a completion signal
    5. On completion: character sheet embed posted in the MAIN channel,
       "✅ Character created!" posted in thread, thread archived

Active sessions are tracked in ``_sessions: dict[thread_id → CreationSession]``
so the on_message listener can route thread messages to the right API session.
Only the creating player can send messages that are forwarded to the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds.character_sheet import (
    build_character_sheet_embed,
    build_inventory_embed,
    build_spells_embed,
)
from ..models.state import BotState
from ..services.api_client import TavernAPI, TavernAPIError
from ..services.identity import IdentityService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class CreationSession:
    """Tracks a single guided-creation conversation in a Discord thread."""

    user_id: int
    """Discord user ID of the player creating the character."""
    campaign_id: str
    """Tavern campaign UUID string."""
    api_session_id: str
    """Session ID returned by ``POST .../characters/creation``."""
    thread_id: int
    """Discord thread ID where the conversation is happening."""
    channel_id: int
    """Main text channel ID — where the completed sheet is posted."""


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class CharacterCog(commands.Cog):
    """All /character subcommands and creation thread management."""

    def __init__(
        self,
        bot: commands.Bot,
        api: TavernAPI,
        state: BotState,
        identity: IdentityService,
    ) -> None:
        self.bot = bot
        self.api = api
        self.state = state
        self.identity = identity
        # thread_id → active creation session
        self._sessions: dict[int, CreationSession] = {}

    # ------------------------------------------------------------------
    # /character group
    # ------------------------------------------------------------------

    character = app_commands.Group(name="character", description="Character commands")

    # ------------------------------------------------------------------
    # /character create
    # ------------------------------------------------------------------

    @character.command(name="create", description="Start guided character creation.")
    async def create(self, interaction: discord.Interaction) -> None:
        """Open a private thread and start a guided character creation conversation."""
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        binding = self.state.get_binding(channel_id)
        if binding is None:
            await interaction.response.send_message(
                "No campaign in this channel. Use `/lfg` to start one.",
                ephemeral=True,
            )
            return

        campaign_id = str(binding.campaign_id)
        user = interaction.user

        await interaction.response.defer(thinking=True)

        # Ensure the user has a Tavern account so identity resolves correctly.
        try:
            tavern_user = await self.identity.get_tavern_user(user.id, user.display_name)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not resolve your account: {exc.message}", ephemeral=True
            )
            return

        # Reject if the user already has a character in this campaign.
        existing = await self.identity.get_character(user.id, campaign_id)
        if existing is not None:
            await interaction.followup.send(
                f"You already have a character (**{existing.name}**) in this campaign.",
                ephemeral=True,
            )
            return

        # Start the guided creation session via the API.
        try:
            creation_resp = await self.api.start_character_creation(
                campaign_id, str(tavern_user.id), user.display_name
            )
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not start character creation: {exc.message}", ephemeral=True
            )
            return

        session_id: str = creation_resp.get("session_id", "")
        first_message: str = (
            creation_resp.get("message") or "Let's begin your character creation journey!"
        )
        status: str = creation_resp.get("status", "in_progress")

        # Post the interaction response and create a thread from it.
        await interaction.followup.send(
            f"⚔️ {user.mention} — your character creation thread is below!"
        )
        anchor_msg = await interaction.original_response()

        try:
            thread = await anchor_msg.create_thread(
                name=f"{user.display_name}'s Character",
                auto_archive_duration=1440,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error("Could not create creation thread: %s", exc)
            await interaction.followup.send(
                "❌ Could not create a thread. Check the bot's thread permissions.",
                ephemeral=True,
            )
            return

        # If creation somehow completed immediately (rare), skip straight to finish.
        if status == "complete":
            character_data = creation_resp.get("character") or {}
            await self._finish_creation(thread, channel_id, user, character_data, first_message)
            return

        # Store the session and post Claude's first question in the thread.
        session = CreationSession(
            user_id=user.id,
            campaign_id=campaign_id,
            api_session_id=session_id,
            thread_id=thread.id,
            channel_id=channel_id,
        )
        self._sessions[thread.id] = session

        await thread.send(first_message)

    # ------------------------------------------------------------------
    # /character sheet
    # ------------------------------------------------------------------

    @character.command(name="sheet", description="View a character sheet.")
    @app_commands.describe(user="Player to view (default: yourself)")
    async def sheet(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        binding = self.state.get_binding(channel_id)
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        campaign_id = str(binding.campaign_id)
        target = user or interaction.user

        await interaction.response.defer(thinking=True)

        character = await self.identity.get_character(target.id, campaign_id)
        if character is None:
            name = target.display_name
            await interaction.followup.send(
                f"**{name}** doesn't have a character in this campaign yet.",
                ephemeral=True,
            )
            return

        try:
            char_data = await self.api.get_character(campaign_id, str(character.id))
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        embed = build_character_sheet_embed(char_data)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /character inventory
    # ------------------------------------------------------------------

    @character.command(name="inventory", description="View your character's inventory.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        binding = self.state.get_binding(channel_id)
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        campaign_id = str(binding.campaign_id)
        await interaction.response.defer(thinking=True)

        character = await self.identity.get_character(interaction.user.id, campaign_id)
        if character is None:
            await interaction.followup.send(
                "You don't have a character in this campaign.", ephemeral=True
            )
            return

        try:
            char_data = await self.api.get_character(campaign_id, str(character.id))
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        embed = build_inventory_embed(char_data)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /character spells
    # ------------------------------------------------------------------

    @character.command(name="spells", description="View your character's spells.")
    async def spells(self, interaction: discord.Interaction) -> None:
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        binding = self.state.get_binding(channel_id)
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        campaign_id = str(binding.campaign_id)
        await interaction.response.defer(thinking=True)

        character = await self.identity.get_character(interaction.user.id, campaign_id)
        if character is None:
            await interaction.followup.send(
                "You don't have a character in this campaign.", ephemeral=True
            )
            return

        try:
            char_data = await self.api.get_character(campaign_id, str(character.id))
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        embed = build_spells_embed(char_data)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # on_message — creation thread routing
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Forward player replies in creation threads to the API."""
        if message.author.bot:
            return

        thread_id = message.channel.id
        session = self._sessions.get(thread_id)
        if session is None:
            return

        # Only the creating player's messages are forwarded.
        if message.author.id != session.user_id:
            return

        # Send to API.
        try:
            resp = await self.api.submit_creation_step(
                session.campaign_id, session.api_session_id, message.content
            )
        except TavernAPIError as exc:
            logger.error("Creation step failed for session %s: %s", session.api_session_id, exc)
            await message.channel.send(f"❌ Error: {exc.message}")
            return

        reply_text: str = resp.get("message") or ""
        status: str = resp.get("status", "in_progress")

        if reply_text:
            await message.channel.send(reply_text)

        if status == "complete":
            character_data = resp.get("character") or {}
            main_channel = await self._get_text_channel(session.channel_id)
            await self._finish_creation(
                message.channel,  # type: ignore[arg-type]
                session.channel_id,
                message.author,
                character_data,
                reply_text,
                main_channel=main_channel,
            )
            del self._sessions[thread_id]
            # Invalidate identity cache so the new character is discovered.
            self.identity._character_cache.pop((session.user_id, session.campaign_id), None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _finish_creation(
        self,
        thread: discord.Thread,
        channel_id: int,
        user: discord.User | discord.Member,
        character_data: dict,  # type: ignore[type-arg]
        completion_message: str,
        main_channel: discord.TextChannel | None = None,
    ) -> None:
        """Post the completed character sheet in the main channel and close the thread."""
        # Build and post character sheet in the main channel.
        if main_channel is None:
            main_channel = await self._get_text_channel(channel_id)

        if main_channel is not None:
            sheet_embed = build_character_sheet_embed(character_data)
            char_name = character_data.get("name") or user.display_name
            await main_channel.send(
                f"🎉 {user.mention}'s character **{char_name}** is ready for adventure!",
                embed=sheet_embed,
            )

        # Confirm and archive the creation thread.
        try:
            await thread.send("✅ Character created! This thread is now archived.")
            await thread.edit(archived=True, locked=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Could not archive creation thread %s: %s", thread.id, exc)

    async def _get_text_channel(self, channel_id: int) -> discord.TextChannel | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None
