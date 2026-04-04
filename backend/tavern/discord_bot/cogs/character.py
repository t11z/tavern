"""Character cog — /character subcommands and guided creation threads.

Commands:
    /character create     Start guided character creation in a thread
    /character sheet      Post your character sheet (or another player's)
    /character inventory  Detailed equipment embed
    /character spells     Spells and spell-slot embed

Creation flow (local wizard — no LLM):
    1. /character create → bot opens a thread named "{user}'s Character"
    2. Bot walks through five steps in the thread:
         Step 0: character name
         Step 1: class (numbered list)
         Step 2: species (numbered list)
         Step 3: background (numbered list)
         Step 4: standard array assignment (six scores for STR DEX CON INT WIS CHA)
         Step 5: background ability bonuses (+2/+1 or +1/+1/+1)
    3. On completion: POST /api/campaigns/{id}/characters, sheet embed in main channel,
       thread archived.

Active sessions are tracked in ``_sessions: dict[thread_id → CreationSession]``.
Only the creating player's messages advance the wizard.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

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
# SRD constants (mirrors frontend/src/constants.ts)
# ---------------------------------------------------------------------------

_SRD_CLASSES = [
    "Barbarian",
    "Bard",
    "Cleric",
    "Druid",
    "Fighter",
    "Monk",
    "Paladin",
    "Ranger",
    "Rogue",
    "Sorcerer",
    "Warlock",
    "Wizard",
]

_SRD_SPECIES = [
    "Dragonborn",
    "Dwarf",
    "Elf",
    "Gnome",
    "Half-Elf",
    "Half-Orc",
    "Halfling",
    "Human",
    "Tiefling",
]

_SRD_BACKGROUNDS = [
    "Acolyte",
    "Charlatan",
    "Criminal",
    "Entertainer",
    "Folk Hero",
    "Guild Artisan",
    "Hermit",
    "Noble",
    "Outlander",
    "Sage",
    "Sailor",
    "Soldier",
]

_STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]
_ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

# Regex to parse bonus notation like "STR+2 CON+1" or "STR+1 DEX+1 CON+1"
_BONUS_RE = re.compile(r"([A-Za-z]{3})\+(\d)")


def _numbered_list(items: list[str]) -> str:
    return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))


def _parse_choice(text: str, options: list[str]) -> str | None:
    """Return the option matching a number (1-based) or a case-insensitive name."""
    text = text.strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(options):
            return options[idx]
        return None
    for opt in options:
        if opt.lower() == text.lower():
            return opt
    return None


def _parse_standard_array(text: str) -> dict[str, int] | None:
    """Parse '15 14 13 12 10 8' (in STR DEX CON INT WIS CHA order)."""
    parts = text.split()
    if len(parts) != 6:
        return None
    try:
        values = [int(p) for p in parts]
    except ValueError:
        return None
    if sorted(values, reverse=True) != _STANDARD_ARRAY:
        return None
    return dict(zip(_ABILITIES, values))


def _parse_bonuses(text: str) -> dict[str, int] | None:
    """Parse '+2/+1' or '+1/+1/+1' bonus notation.

    Accepted formats:
      STR+2 CON+1          → {STR: 2, CON: 1}
      STR+1 DEX+1 CON+1   → {STR: 1, DEX: 1, CON: 1}
    """
    matches = _BONUS_RE.findall(text.upper())
    if len(matches) not in (2, 3):
        return None
    bonuses: dict[str, int] = {}
    for ability, value in matches:
        if ability not in _ABILITIES:
            return None
        bonuses[ability] = int(value)
    values = sorted(bonuses.values(), reverse=True)
    if values not in ([2, 1], [1, 1, 1]):
        return None
    return bonuses


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class CreationSession:
    """Tracks a single guided-creation conversation in a Discord thread."""

    user_id: int
    campaign_id: str
    thread_id: int
    channel_id: int
    step: int = 0
    name: str = ""
    class_name: str = ""
    species: str = ""
    background: str = ""
    ability_scores: dict[str, int] = field(default_factory=dict)
    background_bonuses: dict[str, int] = field(default_factory=dict)


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
        """Open a thread and start a local creation wizard."""
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

        # Ensure the user has a Tavern account.
        try:
            await self.identity.get_tavern_user(user.id, user.display_name)
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

        # Post and create a thread from the response.
        await interaction.followup.send(
            f"⚔️ {user.mention} — character creation thread started below!"
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

        session = CreationSession(
            user_id=user.id,
            campaign_id=campaign_id,
            thread_id=thread.id,
            channel_id=channel_id,
        )
        self._sessions[thread.id] = session
        await self._send_step(thread, session)

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
        """Advance the creation wizard when the player replies in their thread."""
        if message.author.bot:
            return

        thread_id = message.channel.id
        session = self._sessions.get(thread_id)
        if session is None:
            return

        # Only the creating player's messages advance the wizard.
        if message.author.id != session.user_id:
            return

        await self._handle_step(message.channel, session, message.content.strip())  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Wizard steps
    # ------------------------------------------------------------------

    async def _send_step(self, thread: discord.Thread, session: CreationSession) -> None:
        """Post the prompt for the current wizard step."""
        step = session.step
        if step == 0:
            await thread.send("**Step 1 of 5 — Name**\nWhat is your character's name?")
        elif step == 1:
            await thread.send(
                f"**Step 2 of 5 — Class**\nChoose a class (type the number or name):\n"
                f"{_numbered_list(_SRD_CLASSES)}"
            )
        elif step == 2:
            await thread.send(
                f"**Step 3 of 5 — Species**\nChoose a species:\n{_numbered_list(_SRD_SPECIES)}"
            )
        elif step == 3:
            await thread.send(
                f"**Step 4 of 5 — Background**\nChoose a background:\n"
                f"{_numbered_list(_SRD_BACKGROUNDS)}"
            )
        elif step == 4:
            array_str = " ".join(str(n) for n in _STANDARD_ARRAY)
            await thread.send(
                f"**Step 5 of 5 — Ability Scores**\n"
                f"Assign the standard array `[{array_str}]` to your abilities.\n"
                f"Type 6 numbers in this order: **STR DEX CON INT WIS CHA**\n"
                f"Each value must be used exactly once.\n"
                f"Example: `15 14 13 12 10 8`"
            )
        elif step == 5:
            await thread.send(
                "**Step 6 of 6 — Background Bonuses**\n"
                "Assign your background's ability score bonuses.\n"
                "Valid distributions:\n"
                "• `+2/+1` split — e.g. `STR+2 CON+1`\n"
                "• `+1/+1/+1` spread — e.g. `STR+1 DEX+1 CON+1`\n"
                "Type your choice:"
            )

    async def _handle_step(
        self, thread: discord.Thread, session: CreationSession, text: str
    ) -> None:
        """Process the player's reply for the current step and advance or re-prompt."""
        step = session.step

        if step == 0:
            if not text:
                await thread.send("Please enter a name for your character.")
                return
            session.name = text
            session.step = 1
            await self._send_step(thread, session)

        elif step == 1:
            choice = _parse_choice(text, _SRD_CLASSES)
            if choice is None:
                await thread.send(
                    f"❌ Not a valid class. Type a number (1–{len(_SRD_CLASSES)}) or a class name."
                )
                return
            session.class_name = choice
            session.step = 2
            await self._send_step(thread, session)

        elif step == 2:
            choice = _parse_choice(text, _SRD_SPECIES)
            if choice is None:
                await thread.send(
                    f"❌ Not a valid species. "
                    f"Type a number (1–{len(_SRD_SPECIES)}) or a species name."
                )
                return
            session.species = choice
            session.step = 3
            await self._send_step(thread, session)

        elif step == 3:
            choice = _parse_choice(text, _SRD_BACKGROUNDS)
            if choice is None:
                await thread.send(
                    f"❌ Not a valid background. Type a number (1–{len(_SRD_BACKGROUNDS)}) "
                    f"or a background name."
                )
                return
            session.background = choice
            session.step = 4
            await self._send_step(thread, session)

        elif step == 4:
            scores = _parse_standard_array(text)
            if scores is None:
                array_str = " ".join(str(n) for n in _STANDARD_ARRAY)
                await thread.send(
                    f"❌ Invalid assignment. Provide exactly 6 numbers using each of "
                    f"[{array_str}] once, in STR DEX CON INT WIS CHA order."
                )
                return
            session.ability_scores = scores
            session.step = 5
            await self._send_step(thread, session)

        elif step == 5:
            bonuses = _parse_bonuses(text)
            if bonuses is None:
                await thread.send(
                    "❌ Invalid bonus format.\n"
                    "Use `ABL+2 ABL+1` (e.g. `STR+2 CON+1`) or "
                    "`ABL+1 ABL+1 ABL+1` (e.g. `STR+1 DEX+1 CON+1`)."
                )
                return
            session.background_bonuses = bonuses
            await self._submit(thread, session)

    async def _submit(self, thread: discord.Thread, session: CreationSession) -> None:
        """Submit the completed character to the API and finish the wizard."""
        await thread.send("⏳ Creating your character...")

        data = {
            "name": session.name,
            "class_name": session.class_name,
            "species": session.species,
            "background": session.background,
            "ability_scores": session.ability_scores,
            "ability_score_method": "standard_array",
            "background_bonuses": session.background_bonuses,
            "equipment_choices": "package_a",
            "languages": [],
        }

        try:
            char_data = await self.api.create_character(session.campaign_id, data)
        except TavernAPIError as exc:
            await thread.send(f"❌ Character creation failed: {exc.message}\nPlease start over.")
            del self._sessions[session.thread_id]
            return

        # Post character sheet in main channel.
        main_channel = await self._get_text_channel(session.channel_id)
        if main_channel is not None:
            sheet_embed = build_character_sheet_embed(char_data)
            char_name = char_data.get("name") or session.name
            user = thread.guild.get_member(session.user_id) if thread.guild else None
            mention = user.mention if user else f"<@{session.user_id}>"
            await main_channel.send(
                f"🎉 {mention}'s character **{char_name}** is ready for adventure!",
                embed=sheet_embed,
            )

        # Archive the thread.
        try:
            await thread.send("✅ Character created! This thread is now archived.")
            await thread.edit(archived=True, locked=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Could not archive creation thread %s: %s", thread.id, exc)

        # Invalidate identity cache so the new character is discovered.
        self.identity._character_cache.pop((session.user_id, session.campaign_id), None)
        del self._sessions[session.thread_id]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_text_channel(self, channel_id: int) -> discord.TextChannel | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None
