"""Tests for the LFG embed builder — pure data, no I/O."""

from __future__ import annotations

import discord
import pytest

from tavern.discord_bot.embeds.lfg import TAVERN_AMBER, build_lfg_embed


class TestBuildLfgEmbed:
    def test_returns_discord_embed(self) -> None:
        embed = build_lfg_embed("Shattered Coast", "Alice", ["Alice"])
        assert isinstance(embed, discord.Embed)

    def test_title_is_looking_for_adventurers(self) -> None:
        embed = build_lfg_embed("any", "Alice", ["Alice"])
        assert embed.title == "🎲 Looking for Adventurers!"

    def test_description_is_lfg_text(self) -> None:
        embed = build_lfg_embed("Saturday 8pm, Level 1", "Alice", ["Alice"])
        assert embed.description == "Saturday 8pm, Level 1"

    def test_colour_is_tavern_amber(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice"])
        assert embed.colour == TAVERN_AMBER

    def test_tavern_amber_is_correct_hex(self) -> None:
        assert TAVERN_AMBER.value == 0xD4A24E

    def test_player_count_field_shows_count(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice", "Bob", "Carol"])
        count_field = next(f for f in embed.fields if "Players" in f.name)
        assert "3" in count_field.value

    def test_party_field_lists_all_players(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice", "Bob"])
        party_field = next(f for f in embed.fields if f.name == "Party")
        assert "Alice" in party_field.value
        assert "Bob" in party_field.value

    def test_party_field_joins_names_with_comma(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice", "Bob"])
        party_field = next(f for f in embed.fields if f.name == "Party")
        assert party_field.value == "Alice, Bob"

    def test_footer_mentions_join(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice"])
        assert embed.footer.text is not None
        assert "Join" in embed.footer.text

    def test_empty_player_list_falls_back_to_creator_name(self) -> None:
        embed = build_lfg_embed("x", "Alice", [])
        party_field = next(f for f in embed.fields if f.name == "Party")
        assert "Alice" in party_field.value

    def test_single_player_shows_count_1(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice"])
        count_field = next(f for f in embed.fields if "Players" in f.name)
        assert "1" in count_field.value

    def test_long_description_preserved(self) -> None:
        desc = "A" * 500
        embed = build_lfg_embed(desc, "Alice", ["Alice"])
        assert embed.description == desc

    def test_has_exactly_two_fields(self) -> None:
        embed = build_lfg_embed("x", "Alice", ["Alice"])
        assert len(embed.fields) == 2
