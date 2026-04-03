"""Manages Discord channel lifecycle for Tavern campaigns.

Responsible for creating, archiving, and deleting the category+channel set
that belongs to each campaign.  All Discord API calls are wrapped with a
``discord.Forbidden`` guard; if the bot lacks permissions it logs a warning
and returns ``None`` so callers can surface a graceful error to the user.

Permission model (per the Channel Architecture spec):

    @everyone        view=False
    Campaign members view=True, send_messages=True, connect=True
    Bot              view=True, send_messages=True, manage_messages=True,
                     embed_links=True, connect=True, speak=True,
                     move_members=True
"""

from __future__ import annotations

import logging
import re

import discord

logger = logging.getLogger(__name__)

# Permissions granted to campaign members on the category.
_MEMBER_OVERWRITE = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=True,
    connect=True,
)

# Permissions granted to the bot on the category.
_BOT_OVERWRITE = discord.PermissionOverwrite(
    view_channel=True,
    send_messages=True,
    manage_messages=True,
    embed_links=True,
    connect=True,
    speak=True,
    move_members=True,
)

# Permissions denied to @everyone on the category.
_EVERYONE_OVERWRITE = discord.PermissionOverwrite(view_channel=False)

# Guild-level permissions the bot requires to manage channels.
_REQUIRED_PERMISSIONS = ("manage_channels", "move_members", "manage_roles")


def _slugify(name: str) -> str:
    """Convert a campaign name to a valid Discord channel slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:100] or "campaign"


class ChannelManager:
    """Creates and manages Discord channels for Tavern campaigns."""

    # ------------------------------------------------------------------
    # Channel creation
    # ------------------------------------------------------------------

    async def create_campaign_channels(
        self,
        guild: discord.Guild,
        campaign_name: str,
        member_ids: list[int],
        bot_user: discord.ClientUser,
    ) -> tuple[discord.CategoryChannel, discord.TextChannel, discord.VoiceChannel] | None:
        """Create the category, text channel, and voice channel for a campaign.

        Args:
            guild:         The Discord guild to create channels in.
            campaign_name: Human-readable campaign name.
            member_ids:    Discord user IDs of campaign members.
            bot_user:      The bot's own user object (used to set its overwrite).

        Returns:
            ``(category, text_channel, voice_channel)`` on success.
            ``None`` if the bot lacks the required permissions (Forbidden).
        """
        overwrites = _build_overwrites(guild, member_ids, bot_user)
        try:
            category = await guild.create_category(
                f"Tavern: {campaign_name}",
                overwrites=overwrites,
            )
            text_channel = await guild.create_text_channel(
                _slugify(campaign_name),
                category=category,
            )
            voice_channel = await guild.create_voice_channel(
                f"{campaign_name} Voice",
                category=category,
            )
        except discord.Forbidden:
            logger.warning(
                "Missing permissions to create channels in guild %s (%d). "
                "Ask a server admin to grant Manage Channels, or use /tavern bind.",
                guild.name,
                guild.id,
            )
            return None

        return category, text_channel, voice_channel

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------

    async def archive_channels(self, category: discord.CategoryChannel) -> None:
        """Make all channels in the category read-only and rename it.

        Channel content is preserved; members can still read but not write.
        """
        everyone = category.guild.default_role
        for channel in category.channels:
            await channel.set_permissions(everyone, send_messages=False)
        archived_name = f"📁 {category.name} (archived)"
        await category.edit(name=archived_name)

    async def delete_channels(self, category: discord.CategoryChannel) -> None:
        """Delete all channels in the category, then delete the category itself."""
        for channel in list(category.channels):
            await channel.delete()
        await category.delete()

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    async def check_permissions(self, guild: discord.Guild) -> list[str]:
        """Return names of required guild permissions the bot is currently missing.

        An empty list means the bot has everything it needs.
        """
        perms = guild.me.guild_permissions
        return [p for p in _REQUIRED_PERMISSIONS if not getattr(perms, p, False)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_overwrites(
    guild: discord.Guild,
    member_ids: list[int],
    bot_user: discord.ClientUser,
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    """Build the permission overwrite dict for the campaign category."""
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: _EVERYONE_OVERWRITE,
    }
    bot_member = guild.get_member(bot_user.id)
    if bot_member is not None:
        overwrites[bot_member] = _BOT_OVERWRITE

    for uid in member_ids:
        member = guild.get_member(uid)
        if member is not None:
            overwrites[member] = _MEMBER_OVERWRITE

    return overwrites
