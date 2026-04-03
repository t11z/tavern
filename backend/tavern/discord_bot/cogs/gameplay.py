"""Gameplay cog — turn submission, narrative posting, and in-session commands.

Handles:
  • Message interception in Game Mode channels (on_message)
  • /action <text>   — explicit turn submission
  • /roll [expr]     — trigger pending turn roll, or standalone dice roll
  • /history [n]     — condensed turn history embed
  • /recap           — narrative recap from Claude (Haiku)
  • /map             — current scene description embed

  WebSocket event listeners (dispatched by WebSocketCog):
  • on_tavern_turn_roll_required   — post roll prompt embed + buttons
  • on_tavern_turn_roll_executed   — post roll result embed
  • on_tavern_turn_narrative_end   — post narrative + optional combat embed
  • on_tavern_character_updated    — log only; HP reflected in next turn status
  • on_tavern_player_joined        — post join notice
  • on_tavern_player_left          — post leave notice
  • on_tavern_system_error         — post error warning
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds.combat import build_combat_embed, build_party_status
from ..embeds.rolls import RollPromptView, build_roll_prompt_embed, build_roll_result_embed
from ..models.state import BotState, PendingRoll
from ..services.api_client import TavernAPI, TavernAPIError
from ..services.identity import IdentityService

logger = logging.getLogger(__name__)

# Regex that matches out-of-character messages:
#   ^//         starts with //
#   ^\(.*\)$    entire message wrapped in parentheses
_OOC_RE = re.compile(r"^//|^\(.*\)$", re.DOTALL)

# Maximum characters per Discord message.
_MAX_MSG_LEN = 2000
# Split narratives working backwards from this position.
_SPLIT_AT = _MAX_MSG_LEN - 10

# Max turns returned by /history.
_HISTORY_MAX = 25


def _is_ooc(content: str) -> bool:
    """Return True if the message content is an out-of-character message."""
    return bool(_OOC_RE.match(content.strip()))


def _split_narrative(text: str) -> list[str]:
    """Split narrative text at sentence boundaries to fit Discord's 2000-char limit."""
    from ..embeds.narrative import split_narrative

    return split_narrative(text, max_length=_MAX_MSG_LEN)


class GameplayCog(commands.Cog):
    """In-game message processing and gameplay commands."""

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

    # ------------------------------------------------------------------
    # Message interception
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Intercept in-character messages in Game Mode channels."""
        # Ignore messages from bots (including ourselves).
        if message.author.bot:
            return

        # Ignore DMs and non-text channels.
        if not isinstance(message.channel, discord.TextChannel):
            return

        channel_id = message.channel.id

        # Only intercept channels that are in Game Mode.
        if not self.state.is_game_mode(channel_id):
            return

        content = message.content

        # Slash commands are handled by discord.py; skip them here.
        if content.startswith("/"):
            return

        # Out-of-character messages are silently ignored.
        if _is_ooc(content):
            return

        binding = self.state.get_binding(channel_id)
        if binding is None:
            return

        await self._submit_action(
            message.channel, message.author, str(binding.campaign_id), content
        )

    # ------------------------------------------------------------------
    # /action
    # ------------------------------------------------------------------

    @app_commands.command(name="action", description="Submit an in-character action.")
    @app_commands.describe(text="What does your character do?")
    async def action(self, interaction: discord.Interaction, text: str) -> None:
        """Explicit turn submission — equivalent to typing in the channel."""
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        binding = self.state.get_binding(channel_id)
        if binding is None:
            await interaction.response.send_message(
                "No campaign in this channel. Use `/lfg` to start one.",
                ephemeral=True,
            )
            return

        if not self.state.is_game_mode(channel_id):
            await interaction.response.send_message(
                "The session is not active. Use `/tavern start` to begin.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Must be used in a text channel.", ephemeral=True)
            return

        user = interaction.user
        campaign_id = str(binding.campaign_id)

        character = await self._resolve_character(interaction, user, campaign_id)
        if character is None:
            return

        try:
            async with channel.typing():
                await self.api.submit_turn(campaign_id, str(character.id), text)
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Action submitted: *{text}*", ephemeral=True)

    # ------------------------------------------------------------------
    # /history
    # ------------------------------------------------------------------

    @app_commands.command(name="history", description="Show recent turn history.")
    @app_commands.describe(n="Number of turns to show (default 5, max 25)")
    async def history(self, interaction: discord.Interaction, n: int = 5) -> None:
        binding = self.state.get_binding(interaction.channel_id)  # type: ignore[arg-type]
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        n = max(1, min(n, _HISTORY_MAX))
        await interaction.response.defer(thinking=True)

        try:
            data = await self.api.get_turn_history(str(binding.campaign_id), limit=n)
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        turns: list[dict] = data if isinstance(data, list) else data.get("turns", [])

        if not turns:
            await interaction.followup.send("No turns recorded yet.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📜 Last {len(turns)} Turns",
            colour=discord.Colour(0xD4A24E),
        )
        lines: list[str] = []
        for turn in turns:
            char_name = turn.get("character_name") or turn.get("character_id", "?")
            action = turn.get("action", "—")
            summary = turn.get("summary") or ""
            if summary:
                lines.append(f"⚔️ **{char_name}**: {action} → {summary}")
            else:
                lines.append(f"⚔️ **{char_name}**: {action}")

        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /recap
    # ------------------------------------------------------------------

    @app_commands.command(name="recap", description="Get a narrative recap from Claude.")
    async def recap(self, interaction: discord.Interaction) -> None:
        binding = self.state.get_binding(interaction.channel_id)  # type: ignore[arg-type]
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            data = await self.api.get_recap(str(binding.campaign_id))
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        summary: str = data.get("summary") or data.get("recap") or "No recap available."
        for chunk in _split_narrative(summary):
            await interaction.followup.send(chunk)

    # ------------------------------------------------------------------
    # /map
    # ------------------------------------------------------------------

    @app_commands.command(name="map", description="Show the current scene description.")
    async def map(self, interaction: discord.Interaction) -> None:
        binding = self.state.get_binding(interaction.channel_id)  # type: ignore[arg-type]
        if binding is None:
            await interaction.response.send_message("No campaign in this channel.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            data = await self.api.get_scene(str(binding.campaign_id))
        except TavernAPIError:
            # Fall back to campaign data if scene endpoint isn't available yet.
            try:
                data = await self.api.get_campaign(str(binding.campaign_id))
                state = data.get("state") or {}
                data = {
                    "location": data.get("name", "Unknown"),
                    "description": state.get("scene_context") or "No scene information available.",
                    "points_of_interest": [],
                }
            except TavernAPIError as exc2:
                await interaction.followup.send(f"❌ {exc2.message}", ephemeral=True)
                return

        embed = _build_scene_embed(data)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /roll
    # ------------------------------------------------------------------

    @app_commands.command(
        name="roll",
        description="Trigger a pending turn roll, or roll a dice expression.",
    )
    @app_commands.describe(expression="Dice expression for a standalone roll, e.g. '2d6+3'")
    async def roll(self, interaction: discord.Interaction, expression: str | None = None) -> None:
        channel_id: int = interaction.channel_id  # type: ignore[assignment]
        pending = self.state.get_pending_roll(channel_id)

        if pending is not None:
            # A turn roll is waiting — trigger it via API.
            binding = self.state.get_binding(channel_id)
            if binding is None:
                await interaction.response.send_message(
                    "No campaign in this channel.", ephemeral=True
                )
                return

            await interaction.response.defer(thinking=True)
            try:
                await self.api.execute_roll(
                    str(binding.campaign_id),
                    str(pending.turn_id),
                    str(pending.roll_id),
                    [],
                )
            except TavernAPIError as exc:
                await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
                return

            self.state.clear_pending_roll(channel_id)
            await interaction.followup.send("🎲 Roll triggered!", ephemeral=True)

        elif expression is not None:
            # Standalone roll.
            binding = self.state.get_binding(channel_id)
            if binding is None:
                await interaction.response.send_message(
                    "No campaign in this channel.", ephemeral=True
                )
                return

            await interaction.response.defer(thinking=True)
            try:
                result = await self.api.standalone_roll(str(binding.campaign_id), expression)
            except TavernAPIError as exc:
                await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
                return

            total = result.get("total") or result.get("result", "?")
            await interaction.followup.send(
                f"🎲 {interaction.user.display_name} rolls {expression}: **{total}**"
            )

        else:
            await interaction.response.send_message(
                "No roll pending. Use `/roll <expression>` for a standalone roll, "
                "e.g. `/roll 2d6+3`.",
                ephemeral=True,
            )

    # ------------------------------------------------------------------
    # WebSocket event listeners — dice rolling
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_tavern_turn_roll_required")
    async def on_tavern_turn_roll_required(self, payload: dict) -> None:  # type: ignore[type-arg]
        """Post an interactive roll prompt and record the pending roll in state."""
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return

        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return

        binding = self.state.get_binding(channel_id)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        turn_id: str = payload.get("turn_id", "")
        roll_id: str = payload.get("roll_id", "")
        character_id: str = payload.get("character_id", "")
        pre_roll_options: list[dict] = payload.get("pre_roll_options") or []  # type: ignore[assignment]
        timeout_seconds: int = payload.get("timeout_seconds", 120)

        # Resolve the active player's Discord user ID for button gating and mention.
        active_discord_id = self._find_discord_user_for_character(character_id, campaign_id)

        # Record the pending roll in state (for /roll command fallback).
        try:
            from uuid import UUID

            self.state.set_pending_roll(
                PendingRoll(
                    channel_id=channel_id,
                    turn_id=UUID(turn_id),
                    roll_id=UUID(roll_id),
                    character_id=UUID(character_id),
                    expires_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
                )
            )
        except (ValueError, AttributeError):
            logger.warning("Could not parse roll UUIDs from payload: %s", payload)

        # Build embed and view.
        embed = build_roll_prompt_embed(payload)
        view = RollPromptView(
            api=self.api,
            campaign_id=campaign_id,
            turn_id=turn_id,
            roll_id=roll_id,
            active_player_id=active_discord_id or 0,
            pre_roll_options=pre_roll_options,
            timeout=float(timeout_seconds),
        )

        # Mention the active player if we could resolve them.
        mention = f"<@{active_discord_id}> " if active_discord_id else ""
        await channel.send(f"{mention}Your turn to roll!", embed=embed, view=view)

    @commands.Cog.listener("on_tavern_turn_roll_executed")
    async def on_tavern_turn_roll_executed(self, payload: dict) -> None:  # type: ignore[type-arg]
        """Post the roll result embed and clear the pending roll from state."""
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return

        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return

        self.state.clear_pending_roll(channel_id)

        embed = build_roll_result_embed(payload)
        await channel.send(embed=embed)

    # ------------------------------------------------------------------
    # WebSocket event listeners — narrative and presence
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_tavern_turn_narrative_end")
    async def on_tavern_turn_narrative_end(self, payload: dict) -> None:  # type: ignore[type-arg]
        """Post Claude's narrative and an optional combat results embed."""
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return

        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return

        narrative: str = payload.get("narrative") or ""
        if not narrative:
            logger.debug(
                "narrative_end payload has no narrative text (turn_id=%s)", payload.get("turn_id")
            )
            return

        # Post narrative as plain message(s), split at sentence boundaries.
        chunks = _split_narrative(narrative)
        for chunk in chunks:
            await channel.send(chunk)

        # Attach combat results embed if mechanical results are present.
        mechanical_results: list[dict] = payload.get("mechanical_results") or []  # type: ignore[assignment]
        if mechanical_results:
            combat_embed = build_combat_embed(mechanical_results)

            # Append party status if show_party_status is on and character
            # updates are in the payload.
            character_updates: list[dict] = payload.get("character_updates") or []  # type: ignore[assignment]
            party_line = build_party_status(character_updates) if character_updates else ""
            if party_line:
                combat_embed.add_field(name="📊 Party Status", value=party_line, inline=False)

            await channel.send(embed=combat_embed)

    @commands.Cog.listener("on_tavern_character_updated")
    async def on_tavern_character_updated(self, payload: dict) -> None:  # type: ignore[type-arg]
        """Log character updates. HP changes will be reflected in next party status."""
        logger.debug(
            "Character updated: %s (campaign %s)",
            payload.get("character_id"),
            payload.get("campaign_id"),
        )

    @commands.Cog.listener("on_tavern_player_joined")
    async def on_tavern_player_joined(self, payload: dict) -> None:  # type: ignore[type-arg]
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return
        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return
        name: str = (
            payload.get("display_name") or payload.get("character_name") or "A new adventurer"
        )
        await channel.send(f"👋 {name} has joined the session.")

    @commands.Cog.listener("on_tavern_player_left")
    async def on_tavern_player_left(self, payload: dict) -> None:  # type: ignore[type-arg]
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return
        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return
        name: str = payload.get("display_name") or payload.get("character_name") or "A player"
        await channel.send(f"👋 {name} has left the session.")

    @commands.Cog.listener("on_tavern_system_error")
    async def on_tavern_system_error(self, payload: dict) -> None:  # type: ignore[type-arg]
        channel_id: int | None = payload.get("_channel_id")
        if channel_id is None:
            return
        channel = await self._get_text_channel(channel_id)
        if channel is None:
            return
        error_msg: str = (
            payload.get("message") or payload.get("error") or "An unknown error occurred."
        )
        await channel.send(f"⚠️ {error_msg}")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _submit_action(
        self,
        channel: discord.TextChannel,
        user: discord.User | discord.Member,
        campaign_id: str,
        action: str,
    ) -> None:
        """Resolve user → character, show typing, and submit the turn."""
        try:
            tavern_user = await self.identity.get_tavern_user(user.id, user.display_name)
        except TavernAPIError as exc:
            await channel.send(
                f"{user.mention} ❌ Could not resolve your Tavern user: {exc.message}"
            )
            return

        character = await self.identity.get_character(user.id, campaign_id)
        if character is None:
            await channel.send(
                f"{user.mention} You don't have a character in this campaign. "
                "Use `/character create`."
            )
            return

        try:
            async with channel.typing():
                await self.api.submit_turn(campaign_id, str(character.id), action)
        except TavernAPIError as exc:
            logger.error(
                "Turn submission failed for %s in campaign %s: %s",
                tavern_user.id,
                campaign_id,
                exc,
            )
            await channel.send(f"{user.mention} ❌ {exc.message}")

    async def _resolve_character(
        self,
        interaction: discord.Interaction,
        user: discord.User | discord.Member,
        campaign_id: str,
    ):  # type: ignore[return]
        """Resolve a Discord user to their character; send error and return None if missing."""
        try:
            await self.identity.get_tavern_user(user.id, user.display_name)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not resolve your Tavern user: {exc.message}", ephemeral=True
            )
            return None

        character = await self.identity.get_character(user.id, campaign_id)
        if character is None:
            await interaction.followup.send(
                "You don't have a character in this campaign. Use `/character create`.",
                ephemeral=True,
            )
            return None

        return character

    async def _get_text_channel(self, channel_id: int) -> discord.TextChannel | None:
        """Return the TextChannel for the given ID, fetching if necessary."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    def _find_discord_user_for_character(self, character_id: str, campaign_id: str) -> int | None:
        """Return the Discord user ID whose character matches character_id in campaign_id.

        Iterates the identity service's character cache — O(n) over cached characters,
        acceptable for the expected number of concurrent campaign members.
        Returns None if the character is not in cache (e.g. user has never interacted).
        """
        for (discord_user_id, camp_id), character in self.identity._character_cache.items():
            if camp_id == campaign_id and character is not None:
                if str(character.id) == character_id:
                    return discord_user_id
        return None


# ---------------------------------------------------------------------------
# Embed helper (local — not exported)
# ---------------------------------------------------------------------------


def _build_scene_embed(data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the /map scene embed from a scene API response."""
    location = data.get("location") or data.get("name") or "Unknown Location"
    description = data.get("description") or data.get("scene_context") or "—"
    poi: list[str] = data.get("points_of_interest") or []

    embed = discord.Embed(
        title=f"🗺️ {location}",
        description=description,
        colour=discord.Colour(0xD4A24E),
    )
    if poi:
        embed.add_field(
            name="📍 Points of Interest",
            value="\n".join(f"• {p}" for p in poi),
            inline=False,
        )
    return embed
