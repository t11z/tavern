"""Tests for ChannelManager — mock discord.py Guild/Category objects."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from tavern.discord_bot.services.channel_manager import (
    ChannelManager,
    _slugify,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_guild(
    *,
    bot_id: int = 1,
    member_ids: list[int] | None = None,
    missing_perms: list[str] | None = None,
) -> MagicMock:
    """Build a mock discord.Guild with the minimal surface ChannelManager needs."""
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Test Server"
    guild.id = 999

    # @everyone role
    guild.default_role = MagicMock(spec=discord.Role)

    # Bot member (guild.me)
    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = bot_id
    guild.me = bot_member

    # Guild permissions (for check_permissions)
    perms = MagicMock(spec=discord.Permissions)
    for perm in ("manage_channels", "move_members", "manage_roles"):
        setattr(perms, perm, perm not in (missing_perms or []))
    bot_member.guild_permissions = perms
    guild.me.guild_permissions = perms

    # Cache member objects so the same instance is returned for the same ID.
    # This is necessary because overwrite dicts use object identity as keys.
    _member_cache: dict[int, MagicMock] = {}

    def _get_member(uid: int) -> MagicMock | None:
        if uid in _member_cache:
            return _member_cache[uid]
        if uid == bot_id:
            _member_cache[uid] = bot_member
            return bot_member
        if member_ids and uid in member_ids:
            m = MagicMock(spec=discord.Member)
            m.id = uid
            _member_cache[uid] = m
            return m
        return None

    guild.get_member = MagicMock(side_effect=_get_member)

    # Async channel creation helpers
    guild.create_category = AsyncMock(return_value=_make_category(guild))
    guild.create_text_channel = AsyncMock(return_value=_make_text_channel())
    guild.create_voice_channel = AsyncMock(return_value=_make_voice_channel())

    return guild


def _make_category(guild: MagicMock) -> MagicMock:
    cat = MagicMock(spec=discord.CategoryChannel)
    cat.name = "Tavern: Shattered Coast"
    cat.guild = guild
    cat.channels = []
    cat.edit = AsyncMock()
    return cat


def _make_text_channel() -> MagicMock:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = 100
    ch.jump_url = "https://discord.com/channels/999/100"
    ch.set_permissions = AsyncMock()
    ch.delete = AsyncMock()
    return ch


def _make_voice_channel() -> MagicMock:
    ch = MagicMock(spec=discord.VoiceChannel)
    ch.id = 101
    ch.set_permissions = AsyncMock()
    ch.delete = AsyncMock()
    return ch


def make_bot_user(bot_id: int = 1) -> MagicMock:
    u = MagicMock(spec=discord.ClientUser)
    u.id = bot_id
    return u


@pytest.fixture
def manager() -> ChannelManager:
    return ChannelManager()


# ---------------------------------------------------------------------------
# _slugify helper
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercases(self) -> None:
        assert _slugify("Shattered Coast") == "shattered-coast"

    def test_replaces_spaces_with_hyphens(self) -> None:
        assert _slugify("my campaign") == "my-campaign"

    def test_strips_special_characters(self) -> None:
        assert _slugify("Hero's Quest!") == "heros-quest"

    def test_collapses_multiple_hyphens(self) -> None:
        assert _slugify("a  --  b") == "a-b"

    def test_truncates_to_100_chars(self) -> None:
        assert len(_slugify("a" * 200)) == 100

    def test_returns_fallback_for_empty_result(self) -> None:
        assert _slugify("!!!") == "campaign"


# ---------------------------------------------------------------------------
# create_campaign_channels
# ---------------------------------------------------------------------------


class TestCreateCampaignChannels:
    async def test_creates_category_with_correct_name(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)
        guild.create_category.assert_called_once()
        name_arg = guild.create_category.call_args.args[0]
        assert name_arg == "Tavern: Shattered Coast"

    async def test_creates_text_channel_with_slug(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)
        guild.create_text_channel.assert_called_once()
        name_arg = guild.create_text_channel.call_args.args[0]
        assert name_arg == "shattered-coast"

    async def test_creates_voice_channel(self, manager: ChannelManager) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)
        guild.create_voice_channel.assert_called_once()
        name_arg = guild.create_voice_channel.call_args.args[0]
        assert name_arg == "Shattered Coast Voice"

    async def test_returns_tuple_of_three_channels(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        result = await manager.create_campaign_channels(
            guild, "Shattered Coast", [], bot_user
        )
        assert result is not None
        assert len(result) == 3

    async def test_everyone_gets_view_false(self, manager: ChannelManager) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)

        _, kwargs = guild.create_category.call_args
        overwrites = kwargs["overwrites"]
        everyone_ow = overwrites[guild.default_role]
        assert everyone_ow.view_channel is False

    async def test_bot_gets_manage_messages_and_move_members(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(bot_id=42)
        bot_user = make_bot_user(bot_id=42)
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)

        _, kwargs = guild.create_category.call_args
        overwrites = kwargs["overwrites"]
        bot_member = guild.get_member(42)
        bot_ow = overwrites[bot_member]
        assert bot_ow.manage_messages is True
        assert bot_ow.move_members is True
        assert bot_ow.embed_links is True

    async def test_members_get_view_and_send(self, manager: ChannelManager) -> None:
        guild = make_guild(bot_id=1, member_ids=[200, 201])
        bot_user = make_bot_user(bot_id=1)
        await manager.create_campaign_channels(
            guild, "Shattered Coast", [200, 201], bot_user
        )

        _, kwargs = guild.create_category.call_args
        overwrites = kwargs["overwrites"]
        member_200 = guild.get_member(200)
        member_ow = overwrites[member_200]
        assert member_ow.view_channel is True
        assert member_ow.send_messages is True
        assert member_ow.connect is True

    async def test_unknown_member_ids_are_skipped(
        self, manager: ChannelManager
    ) -> None:
        """guild.get_member returning None should not crash or add an overwrite."""
        guild = make_guild(bot_id=1, member_ids=[])  # no members registered
        bot_user = make_bot_user(bot_id=1)
        # Pass a user ID that guild.get_member can't resolve.
        result = await manager.create_campaign_channels(
            guild, "Campaign", [9999], bot_user
        )
        assert result is not None  # should succeed, just skip the unknown member

    async def test_returns_none_on_forbidden(self, manager: ChannelManager) -> None:
        guild = make_guild()
        guild.create_category = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
        bot_user = make_bot_user()
        result = await manager.create_campaign_channels(
            guild, "Shattered Coast", [], bot_user
        )
        assert result is None

    async def test_text_channel_created_under_category(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)

        _, kwargs = guild.create_text_channel.call_args
        assert kwargs["category"] is guild.create_category.return_value

    async def test_voice_channel_created_under_category(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        bot_user = make_bot_user()
        await manager.create_campaign_channels(guild, "Shattered Coast", [], bot_user)

        _, kwargs = guild.create_voice_channel.call_args
        assert kwargs["category"] is guild.create_category.return_value


# ---------------------------------------------------------------------------
# archive_channels
# ---------------------------------------------------------------------------


class TestArchiveChannels:
    def _make_category_with_channels(
        self, guild: MagicMock, n: int = 2
    ) -> MagicMock:
        cat = _make_category(guild)
        cat.name = "Tavern: Shattered Coast"
        channels = [_make_text_channel() for _ in range(n)]
        cat.channels = channels
        return cat

    async def test_sets_everyone_send_messages_false_on_all_channels(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        category = self._make_category_with_channels(guild, n=2)
        await manager.archive_channels(category)
        for ch in category.channels:
            ch.set_permissions.assert_called_once_with(
                guild.default_role, send_messages=False
            )

    async def test_renames_category_with_archive_prefix(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        category = self._make_category_with_channels(guild)
        await manager.archive_channels(category)
        category.edit.assert_called_once()
        name_kwarg = category.edit.call_args.kwargs.get(
            "name"
        ) or category.edit.call_args.args[0] if category.edit.call_args.args else None
        # Grab name from kwargs
        call_kwargs = category.edit.call_args.kwargs
        assert call_kwargs.get("name") == "📁 Tavern: Shattered Coast (archived)"

    async def test_works_with_empty_category(self, manager: ChannelManager) -> None:
        guild = make_guild()
        category = self._make_category_with_channels(guild, n=0)
        await manager.archive_channels(category)  # should not raise
        category.edit.assert_called_once()


# ---------------------------------------------------------------------------
# delete_channels
# ---------------------------------------------------------------------------


class TestDeleteChannels:
    async def test_deletes_all_child_channels(self, manager: ChannelManager) -> None:
        guild = make_guild()
        category = _make_category(guild)
        ch1, ch2 = _make_text_channel(), _make_voice_channel()
        category.channels = [ch1, ch2]
        category.delete = AsyncMock()
        await manager.delete_channels(category)
        ch1.delete.assert_called_once()
        ch2.delete.assert_called_once()

    async def test_deletes_category_after_channels(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild()
        category = _make_category(guild)
        category.channels = []
        category.delete = AsyncMock()
        await manager.delete_channels(category)
        category.delete.assert_called_once()


# ---------------------------------------------------------------------------
# check_permissions
# ---------------------------------------------------------------------------


class TestCheckPermissions:
    async def test_returns_empty_when_all_perms_present(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(missing_perms=[])
        result = await manager.check_permissions(guild)
        assert result == []

    async def test_returns_missing_manage_channels(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(missing_perms=["manage_channels"])
        result = await manager.check_permissions(guild)
        assert "manage_channels" in result

    async def test_returns_missing_move_members(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(missing_perms=["move_members"])
        result = await manager.check_permissions(guild)
        assert "move_members" in result

    async def test_returns_missing_manage_roles(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(missing_perms=["manage_roles"])
        result = await manager.check_permissions(guild)
        assert "manage_roles" in result

    async def test_returns_all_missing_when_none_present(
        self, manager: ChannelManager
    ) -> None:
        guild = make_guild(
            missing_perms=["manage_channels", "move_members", "manage_roles"]
        )
        result = await manager.check_permissions(guild)
        assert set(result) == {"manage_channels", "move_members", "manage_roles"}
