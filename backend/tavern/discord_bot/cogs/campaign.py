"""Campaign management cog — all /tavern subcommands.

Implements the Campaign Management slash command surface from the discord-bot
game design spec.  Also absorbs /tavern ping from the temporary PingCog.

Commands:
    /tavern start     Resume a paused session (owner)
    /tavern stop      Pause the active session (owner)
    /tavern end       Permanently end the campaign (owner)
    /tavern invite    Invite a player mid-campaign (owner)
    /tavern kick      Remove a player (owner)
    /tavern status    Show campaign status (any member)
    /tavern config    View or update settings (owner to set, any member to view)
    /tavern bind      Bind this channel to a campaign manually (owner)
    /tavern help      List all commands
    /tavern ping      Health check (anyone)

Auth note: is_owner() returns True for all users while auth is not yet
implemented (known deviation — ADR-0006 §3).  Once the auth layer ships,
swap in a real membership check.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..models.state import BotState, ChannelBinding
from ..services.api_client import TavernAPI, TavernAPIError
from ..services.channel_manager import ChannelManager
from ..services.identity import IdentityService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config catalogue  (mirrors campaign-configuration.md settings catalog)
# ---------------------------------------------------------------------------

_CONFIG_KEYS: dict[str, dict] = {
    "rolling_mode": {
        "options": ["interactive", "automatic", "hybrid"],
        "description": "How dice rolls are handled.",
    },
    "turn_timeout": {
        "range": (30, 600),
        "description": "Seconds a player has to act before auto-resolve.",
    },
    "reaction_window": {
        "range": (5, 30),
        "description": "Seconds other players have to react after a roll.",
    },
    "difficulty": {
        "options": ["forgiving", "balanced", "deadly"],
        "description": "NPC tactical intelligence and encounter scaling.",
    },
    "allow_late_join": {
        "options": ["true", "false"],
        "description": "Allow new players to join mid-session.",
    },
    "absent_character_mode": {
        "options": ["passive", "auto"],
        "description": "Behaviour for disconnected characters.",
    },
    "ooc_prefix": {
        "description": "Prefix for out-of-character messages (default: //).",
    },
    "show_party_status": {
        "options": ["true", "false"],
        "description": "Append party HP to mechanical result embeds.",
    },
}

TAVERN_AMBER = discord.Colour(0xD4A24E)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_config_value(key: str, value: str) -> str | None:
    """Return an error message if (key, value) is invalid, else None."""
    if key not in _CONFIG_KEYS:
        valid = ", ".join(sorted(_CONFIG_KEYS))
        return f"Unknown setting `{key}`. Valid keys: {valid}"

    spec = _CONFIG_KEYS[key]

    if "options" in spec:
        if value not in spec["options"]:
            opts = ", ".join(spec["options"])
            return f"Invalid value `{value}` for `{key}`. Options: {opts}"

    if "range" in spec:
        try:
            n = int(value)
        except ValueError:
            return f"`{key}` must be an integer."
        lo, hi = spec["range"]
        if not lo <= n <= hi:
            return f"`{key}` must be between {lo} and {hi}. Got {n}."

    return None


def _coerce_config_value(key: str, value: str) -> int | bool | str:
    """Cast the string value to the appropriate Python type."""
    spec = _CONFIG_KEYS.get(key, {})
    if "range" in spec:
        return int(value)
    if key in ("allow_late_join", "show_party_status"):
        return value == "true"
    return value


def _build_config_embed(config: dict) -> discord.Embed:
    embed = discord.Embed(title="⚙️ Campaign Settings", colour=TAVERN_AMBER)
    for key, spec in _CONFIG_KEYS.items():
        raw = config.get(key)
        if raw is None:
            continue
        embed.add_field(name=key, value=f"`{raw}`  — {spec['description']}", inline=False)
    return embed


def _build_status_embed(campaign: dict) -> discord.Embed:
    state = campaign.get("state") or {}
    embed = discord.Embed(
        title=f"📊 {campaign.get('name', 'Campaign')}",
        colour=TAVERN_AMBER,
    )
    embed.add_field(name="Status", value=campaign.get("status", "unknown"), inline=True)
    embed.add_field(name="Tone", value=campaign.get("dm_persona") or "—", inline=True)
    embed.add_field(name="Turns", value=str(state.get("turn_count", 0)), inline=True)
    scene = state.get("scene_context") or "—"
    if len(scene) > 200:
        scene = scene[:197] + "..."
    embed.add_field(name="Current Scene", value=scene, inline=False)
    return embed


def _build_session_banner(campaign_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ {campaign_name} — Game Mode Active",
        description=(
            "Messages in this channel are **in-character actions**.\n"
            "Prefix OOC messages with `//` or wrap in `(parentheses)`."
        ),
        colour=TAVERN_AMBER,
    )
    embed.set_footer(text="Game Mode Active")
    return embed


def _build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Tavern Bot — Commands",
        colour=TAVERN_AMBER,
    )
    embed.add_field(
        name="Group Formation",
        value=(
            "`/lfg <description>` — Post a Looking For Group listing\n"
            "`/tavern start` — Resume a paused session\n"
            "`/tavern stop` — Pause the active session\n"
            "`/tavern end` — Permanently end the campaign"
        ),
        inline=False,
    )
    embed.add_field(
        name="Players",
        value=(
            "`/tavern invite @user` — Invite a player\n"
            "`/tavern kick @user` — Remove a player\n"
            "`/tavern status` — Show campaign status"
        ),
        inline=False,
    )
    embed.add_field(
        name="Settings & Utility",
        value=(
            "`/tavern config` — Show all settings\n"
            "`/tavern config <key> <value>` — Change a setting\n"
            "`/tavern bind #channel <campaign_id>` — Manual channel binding\n"
            "`/tavern ping` — Health check\n"
            "`/tavern help` — This message"
        ),
        inline=False,
    )
    embed.add_field(
        name="Gameplay",
        value=(
            "`/character create` — Create your character\n"
            "`/character sheet` — View your character sheet\n"
            "`/roll [expression]` — Roll dice\n"
            "`/action <text>` — Submit an action\n"
            "`/history [n]` — Last N turns\n"
            "`/recap` — Narrative recap"
        ),
        inline=False,
    )
    embed.set_footer(text="Tavern — SRD 5e RPG engine")
    return embed


# ---------------------------------------------------------------------------
# Confirmation views
# ---------------------------------------------------------------------------


class _ConfirmEndView(discord.ui.View):
    """Yes / No confirmation before permanently ending a campaign."""

    def __init__(self, cog: CampaignCog, campaign_id: str, campaign_name: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.campaign_id = campaign_id
        self.campaign_name = campaign_name

    @discord.ui.button(label="Yes — end campaign", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(thinking=True)
        try:
            await self.cog.api.patch_campaign_config(self.campaign_id, {"status": "ended"})
        except TavernAPIError as exc:
            logger.error("Failed to end campaign %s: %s", self.campaign_id, exc)
            await interaction.followup.send(
                f"❌ Failed to end campaign: {exc.message}", ephemeral=True
            )
            self.stop()
            return

        cleanup_view = _CleanupView(self.cog, interaction.channel_id)  # type: ignore[arg-type]
        summary = discord.Embed(
            title=f"📜 {self.campaign_name} — Campaign Ended",
            description="The campaign has concluded. What should happen to the channels?",
            colour=TAVERN_AMBER,
        )
        await interaction.followup.send(embed=summary, view=cleanup_view)
        self.stop()

    @discord.ui.button(label="No — keep going", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Campaign end cancelled.", ephemeral=True)
        self.stop()


class _CleanupView(discord.ui.View):
    """Archive / Delete / Keep buttons shown after campaign end."""

    def __init__(self, cog: CampaignCog, channel_id: int) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.channel_id = channel_id

    @discord.ui.button(label="📁 Archive (read-only)", style=discord.ButtonStyle.primary)
    async def archive(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = interaction.channel
        if channel and hasattr(channel, "category") and channel.category:  # type: ignore[union-attr]
            await self.cog.channel_manager.archive_channels(channel.category)  # type: ignore[union-attr]
        self.cog.state.unbind_channel(self.channel_id)
        self.cog.state.clear_game_mode(self.channel_id)
        await interaction.response.send_message(
            "📁 Channels archived. They will be deleted in 30 days.", ephemeral=False
        )
        self.stop()

    @discord.ui.button(label="🗑️ Delete now", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = interaction.channel
        if channel and hasattr(channel, "category") and channel.category:  # type: ignore[union-attr]
            await self.cog.channel_manager.delete_channels(channel.category)  # type: ignore[union-attr]
        self.cog.state.unbind_channel(self.channel_id)
        self.cog.state.clear_game_mode(self.channel_id)
        await interaction.response.send_message("🗑️ Channels deleted.", ephemeral=False)
        self.stop()

    @discord.ui.button(label="📌 Keep as-is", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog.state.unbind_channel(self.channel_id)
        self.cog.state.clear_game_mode(self.channel_id)
        await interaction.response.send_message(
            "📌 Channels kept. The bot has removed its campaign binding.", ephemeral=False
        )
        self.stop()


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class CampaignCog(commands.Cog):
    """All /tavern subcommands."""

    def __init__(
        self,
        bot: commands.Bot,
        api: TavernAPI,
        channel_manager: ChannelManager,
        state: BotState,
        identity: IdentityService,
    ) -> None:
        self.bot = bot
        self.api = api
        self.channel_manager = channel_manager
        self.state = state
        self.identity = identity

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _require_binding(self, interaction: discord.Interaction) -> ChannelBinding | None:
        """Return the channel's campaign binding or send an ephemeral error."""
        binding = self.state.get_binding(interaction.channel_id)  # type: ignore[arg-type]
        if binding is None:
            await interaction.response.send_message(
                "No campaign in this channel. Use `/lfg` to start one.",
                ephemeral=True,
            )
        return binding

    async def is_owner(self, interaction: discord.Interaction, campaign_id: str) -> bool:
        """Return True if the invoking user is the campaign owner.

        Auth is not yet implemented (ADR-0006 known deviation — Phase 6).
        Returns True for all users until the membership endpoint is available.
        """
        # TODO(auth): call GET /api/campaigns/{id}/members and check role == "owner"
        return True

    async def _require_owner(self, interaction: discord.Interaction, campaign_id: str) -> bool:
        """Check ownership and send an ephemeral error if not owner. Returns True if owner."""
        if not await self.is_owner(interaction, campaign_id):
            await interaction.response.send_message(
                "Only the campaign owner can do that.", ephemeral=True
            )
            return False
        return True

    # ------------------------------------------------------------------
    # /tavern group
    # ------------------------------------------------------------------

    tavern = app_commands.Group(name="tavern", description="Tavern campaign commands")

    # ------------------------------------------------------------------
    # /tavern start
    # ------------------------------------------------------------------

    @tavern.command(name="start", description="Resume a paused campaign session.")
    async def start(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)

        if self.state.is_game_mode(interaction.channel_id):  # type: ignore[arg-type]
            await interaction.response.send_message("Session is already active.", ephemeral=True)
            return

        try:
            campaign = await self.api.get_campaign(campaign_id)
        except TavernAPIError as exc:
            await interaction.response.send_message(
                f"❌ Could not fetch campaign: {exc.message}", ephemeral=True
            )
            return

        campaign_name = campaign.get("name", "Campaign")
        channel = interaction.channel

        # Activate game mode.
        self.state.set_game_mode(interaction.channel_id)  # type: ignore[arg-type]

        # Update channel topic.
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.edit(topic=f"{campaign_name} — Game in progress")
            except discord.Forbidden:
                pass  # bot lacks Manage Channel; non-fatal

        # Post and pin session banner.
        await interaction.response.send_message(
            "⚔️ Session resumed! Your adventure continues...",
        )
        banner_msg = await channel.send(embed=_build_session_banner(campaign_name))  # type: ignore[union-attr]
        try:
            await banner_msg.pin()
            self.state.set_pinned_banner(interaction.channel_id, banner_msg.id)  # type: ignore[arg-type]
        except discord.Forbidden:
            pass  # bot lacks Manage Messages; non-fatal

        # Signal WebSocketCog to connect (handler registered by that cog when built).
        self.bot.dispatch("tavern_session_start", campaign_id, interaction.channel_id)

    # ------------------------------------------------------------------
    # /tavern stop
    # ------------------------------------------------------------------

    @tavern.command(name="stop", description="Pause the active session.")
    async def stop(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        if not await self._require_owner(interaction, campaign_id):
            return

        if not self.state.is_game_mode(interaction.channel_id):  # type: ignore[arg-type]
            await interaction.response.send_message(
                "No active session in this channel.", ephemeral=True
            )
            return

        channel = interaction.channel

        # Deactivate game mode.
        self.state.clear_game_mode(interaction.channel_id)  # type: ignore[arg-type]

        # Unpin session banner.
        banner_id = self.state.get_pinned_banner(interaction.channel_id)  # type: ignore[arg-type]
        if banner_id and isinstance(channel, discord.TextChannel):
            try:
                msg = await channel.fetch_message(banner_id)
                await msg.unpin()
            except (discord.NotFound, discord.Forbidden):
                pass
            self.state.clear_pinned_banner(interaction.channel_id)  # type: ignore[arg-type]

        # Restore channel topic.
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.edit(topic=None)
            except discord.Forbidden:
                pass

        # Signal WebSocketCog to disconnect.
        self.bot.dispatch("tavern_session_stop", campaign_id, interaction.channel_id)

        # Fetch turn count for summary.
        turns_played = 0
        try:
            history = await self.api.get_turn_history(campaign_id, limit=1)
            turns_played = history.get("total", 0)
        except TavernAPIError:
            pass

        summary = discord.Embed(
            title="⏸️ Session Paused",
            colour=TAVERN_AMBER,
        )
        summary.add_field(name="Turns this session", value=str(turns_played), inline=True)
        summary.set_footer(text='Use "/tavern start" to resume')

        await interaction.response.send_message(
            "Session paused. Use `/tavern start` to resume.", embed=summary
        )

    # ------------------------------------------------------------------
    # /tavern end
    # ------------------------------------------------------------------

    @tavern.command(name="end", description="Permanently end the campaign.")
    async def end(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        if not await self._require_owner(interaction, campaign_id):
            return

        try:
            campaign = await self.api.get_campaign(campaign_id)
        except TavernAPIError as exc:
            await interaction.response.send_message(
                f"❌ Could not fetch campaign: {exc.message}", ephemeral=True
            )
            return

        campaign_name = campaign.get("name", "Campaign")
        view = _ConfirmEndView(self, campaign_id, campaign_name)
        await interaction.response.send_message(
            f"⚠️ End **{campaign_name}** permanently? This cannot be undone.",
            view=view,
        )

    # ------------------------------------------------------------------
    # /tavern invite
    # ------------------------------------------------------------------

    @tavern.command(name="invite", description="Invite a player to the campaign.")
    @app_commands.describe(user="The Discord user to invite")
    async def invite(self, interaction: discord.Interaction, user: discord.Member) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        if not await self._require_owner(interaction, campaign_id):
            return

        await interaction.response.defer(thinking=True)

        # Find or create the Tavern user for this Discord member.
        try:
            tavern_user = await self.identity.get_tavern_user(user.id, user.display_name)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not resolve Tavern user: {exc.message}", ephemeral=True
            )
            return

        # Add to campaign via API.
        try:
            await self.api.invite_player(campaign_id, str(tavern_user.id))
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not add {user.display_name}: {exc.message}", ephemeral=True
            )
            return

        # Grant Discord channel permissions.
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel) and channel.category:
            overwrite = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True
            )
            try:
                await channel.category.set_permissions(user, overwrite=overwrite)
            except discord.Forbidden:
                pass  # non-fatal — permissions already may be set at member level

        await interaction.followup.send(f"✅ {user.mention} has joined the campaign!")

    # ------------------------------------------------------------------
    # /tavern kick
    # ------------------------------------------------------------------

    @tavern.command(name="kick", description="Remove a player from the campaign.")
    @app_commands.describe(user="The Discord user to remove")
    async def kick(self, interaction: discord.Interaction, user: discord.Member) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        if not await self._require_owner(interaction, campaign_id):
            return

        await interaction.response.defer(thinking=True)

        # Look up the Tavern user (must be cached; no auto-create on kick).
        tavern_user = self.identity._user_cache.get(user.id)

        if tavern_user is not None:
            try:
                await self.api.remove_player(campaign_id, str(tavern_user.id))
            except TavernAPIError as exc:
                await interaction.followup.send(
                    f"❌ Could not remove {user.display_name}: {exc.message}",
                    ephemeral=True,
                )
                return

        # Revoke Discord channel permissions.
        channel = interaction.channel
        if isinstance(channel, discord.TextChannel) and channel.category:
            try:
                await channel.category.set_permissions(user, overwrite=None)
            except discord.Forbidden:
                pass

        await interaction.followup.send(f"{user.display_name} has left the campaign.")

    # ------------------------------------------------------------------
    # /tavern status
    # ------------------------------------------------------------------

    @tavern.command(name="status", description="Show campaign status.")
    async def status(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        await interaction.response.defer(thinking=True)

        try:
            campaign = await self.api.get_campaign(str(binding.campaign_id))
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not fetch campaign: {exc.message}", ephemeral=True
            )
            return

        await interaction.followup.send(embed=_build_status_embed(campaign))

    # ------------------------------------------------------------------
    # /tavern config
    # ------------------------------------------------------------------

    @tavern.command(name="config", description="View or update campaign settings.")
    @app_commands.describe(
        key="Setting name (omit to see all settings)",
        value="New value (required when setting a key)",
    )
    async def config(
        self,
        interaction: discord.Interaction,
        key: str | None = None,
        value: str | None = None,
    ) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)
        await interaction.response.defer(thinking=True)

        # No arguments — show current config.
        if key is None:
            try:
                cfg = await self.api.get_campaign_config(campaign_id)
            except TavernAPIError as exc:
                await interaction.followup.send(
                    f"❌ Could not fetch config: {exc.message}", ephemeral=True
                )
                return
            await interaction.followup.send(embed=_build_config_embed(cfg))
            return

        # Key provided — owner check then set.
        if not await self.is_owner(interaction, campaign_id):
            await interaction.followup.send(
                "Only the campaign owner can change settings.", ephemeral=True
            )
            return

        if value is None:
            await interaction.followup.send(
                f"Provide a value for `{key}`. Use `/tavern config` to see valid options.",
                ephemeral=True,
            )
            return

        error = _validate_config_value(key, value)
        if error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        coerced = _coerce_config_value(key, value)
        try:
            await self.api.patch_campaign_config(campaign_id, {key: coerced})
        except TavernAPIError as exc:
            await interaction.followup.send(f"❌ {exc.message}", ephemeral=True)
            return

        desc = _CONFIG_KEYS[key]["description"]
        await interaction.followup.send(f"✅ `{key}` set to `{value}`. {desc}")

    # ------------------------------------------------------------------
    # /tavern bind
    # ------------------------------------------------------------------

    @tavern.command(
        name="bind",
        description="Bind this channel to a campaign (fallback when bot lacks Manage Channels).",
    )
    @app_commands.describe(
        channel="The text channel to bind",
        campaign_id="Campaign UUID from the Tavern API",
    )
    async def bind(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        campaign_id: str,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        # Verify the campaign exists.
        try:
            campaign = await self.api.get_campaign(campaign_id)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Campaign not found: {exc.message}", ephemeral=True
            )
            return

        if interaction.guild is None:
            await interaction.followup.send("Must be used inside a server.", ephemeral=True)
            return

        self.state.bind_channel(
            ChannelBinding(
                channel_id=channel.id,
                campaign_id=__import__("uuid").UUID(campaign_id),
                guild_id=interaction.guild.id,
            )
        )

        campaign_name = campaign.get("name", campaign_id)
        await interaction.followup.send(
            f"✅ {channel.mention} is now bound to **{campaign_name}**.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /tavern help
    # ------------------------------------------------------------------

    @tavern.command(name="help", description="List all Tavern bot commands.")
    async def help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_build_help_embed())

    # ------------------------------------------------------------------
    # /tavern ping  (moved from PingCog)
    # ------------------------------------------------------------------

    @tavern.command(name="ping", description="Health check: bot and API connectivity.")
    async def ping(self, interaction: discord.Interaction) -> None:
        try:
            await self.api.health_check()
            api_status = "reachable"
        except Exception:
            api_status = "unreachable"
        await interaction.response.send_message(f"🏓 Pong! API: {api_status}")
