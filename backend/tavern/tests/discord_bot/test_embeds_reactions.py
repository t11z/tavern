"""Tests for reaction-related embed builders and views in embeds/rolls.py.

Covers:
  _reaction_emoji
  build_reaction_window_embed
  build_self_reaction_embed
  build_reaction_used_embed
  build_reaction_window_closed_embed
  ReactionWindowView  (structure + button filtering)
  SelfReactionView    (structure + button filtering)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from tavern.discord_bot.embeds.rolls import (
    _HIT_COLOUR,
    _MISS_COLOUR,
    TAVERN_AMBER,
    ReactionWindowView,
    SelfReactionView,
    _reaction_emoji,
    build_reaction_used_embed,
    build_reaction_window_closed_embed,
    build_reaction_window_embed,
    build_self_reaction_embed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api() -> MagicMock:
    api = MagicMock()
    api.submit_reaction = AsyncMock(return_value={})
    api.submit_pass = AsyncMock(return_value={})
    return api


def _make_interaction(user_id: int = 111) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _make_roll_result(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "natural": 17,
        "total": 21,
        "target": {"type": "ac", "value": 15},
        "provisional_outcome": "hit",
        "attacker": "Goblin A",
        "defender": "Mira",
    }
    base.update(overrides)
    return base


def _make_reaction_data(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "roll_result": _make_roll_result(),
        "available_reactions": [
            {
                "reactor_character_id": "char-mira",
                "reactor_name": "Mira",
                "reactions": [{"id": "shield_spell", "name": "Shield"}],
            },
            {
                "reactor_character_id": "char-vex",
                "reactor_name": "Vex",
                "reactions": [{"id": "silvery_barbs", "name": "Silvery Barbs"}],
            },
        ],
        "window_seconds": 15,
    }
    base.update(overrides)
    return base


def _make_self_reaction_data(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "natural_result": 8,
        "modifier": 5,
        "total": 13,
        "target": {"type": "ac", "value": 15},
        "provisional_outcome": "miss",
        "self_reactions": [
            {
                "id": "lucky_feat",
                "name": "Lucky",
                "uses_remaining": 2,
            }
        ],
        "self_reaction_window_seconds": 10,
        "character_id": "char-kael",
    }
    base.update(overrides)
    return base


def _make_reaction_used_data(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "reactor_name": "Mira",
        "reactor_character_id": "char-mira",
        "reaction_id": "shield_spell",
        "reaction_name": "Shield",
        "is_npc": False,
        "new_outcome": "miss",
        "remaining_reactions": [
            {
                "reactor_character_id": "char-vex",
                "reactor_name": "Vex",
                "reactions": [{"id": "silvery_barbs", "name": "Silvery Barbs"}],
            }
        ],
        "window_seconds": 15,
    }
    base.update(overrides)
    return base


def _make_reaction_window_view(**overrides) -> ReactionWindowView:
    defaults: dict = {  # type: ignore[type-arg]
        "api": _make_api(),
        "campaign_id": "camp-1",
        "turn_id": "turn-1",
        "roll_id": "roll-1",
        "available_reactions": [
            {
                "reactor_character_id": "char-mira",
                "reactor_name": "Mira",
                "reactions": [{"id": "shield_spell", "name": "Shield"}],
            },
            {
                "reactor_character_id": "char-vex",
                "reactor_name": "Vex",
                "reactions": [{"id": "silvery_barbs", "name": "Silvery Barbs"}],
            },
        ],
        "identity_map": {"char-mira": 111, "char-vex": 222},
        "timeout": 15.0,
    }
    defaults.update(overrides)
    return ReactionWindowView(**defaults)


# ---------------------------------------------------------------------------
# _reaction_emoji
# ---------------------------------------------------------------------------


def test_reaction_emoji_shield() -> None:
    assert _reaction_emoji("shield_spell") == "🛡️"


def test_reaction_emoji_silvery_barbs() -> None:
    assert _reaction_emoji("silvery_barbs") == "🌟"


def test_reaction_emoji_lucky_feat() -> None:
    assert _reaction_emoji("lucky_feat") == "🍀"


def test_reaction_emoji_counterspell() -> None:
    assert _reaction_emoji("counterspell") == "🔮"


def test_reaction_emoji_unknown_defaults_to_lightning() -> None:
    assert _reaction_emoji("unknown_reaction") == "⚡"


# ---------------------------------------------------------------------------
# build_reaction_window_embed
# ---------------------------------------------------------------------------


def test_reaction_window_embed_title() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert embed.title == "⚡ REACTIONS AVAILABLE"


def test_reaction_window_embed_colour_is_amber() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert embed.colour == TAVERN_AMBER


def test_reaction_window_embed_footer_shows_seconds() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert "15" in embed.footer.text
    assert "⏱️" in embed.footer.text


def test_reaction_window_embed_shows_attacker_and_defender() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert "Goblin A" in embed.description
    assert "Mira" in embed.description


def test_reaction_window_embed_shows_roll_total() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert "21" in embed.description


def test_reaction_window_embed_shows_outcome() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert "HIT" in embed.description


def test_reaction_window_embed_lists_reactors() -> None:
    embed = build_reaction_window_embed(_make_reaction_data())
    assert "Vex" in embed.description
    assert "Silvery Barbs" in embed.description
    assert "Shield" in embed.description


def test_reaction_window_embed_no_reactions_still_renders() -> None:
    embed = build_reaction_window_embed(_make_reaction_data(available_reactions=[]))
    assert embed.title == "⚡ REACTIONS AVAILABLE"
    assert embed.description is not None


# ---------------------------------------------------------------------------
# build_self_reaction_embed
# ---------------------------------------------------------------------------


def test_self_reaction_embed_title_contains_self_reaction() -> None:
    embed = build_self_reaction_embed(_make_self_reaction_data())
    assert "Self-Reaction" in embed.title


def test_self_reaction_embed_colour_is_amber() -> None:
    embed = build_self_reaction_embed(_make_self_reaction_data())
    assert embed.colour == TAVERN_AMBER


def test_self_reaction_embed_footer_shows_window_seconds() -> None:
    embed = build_self_reaction_embed(_make_self_reaction_data())
    assert "10" in embed.footer.text


def test_self_reaction_embed_shows_roll_total() -> None:
    embed = build_self_reaction_embed(_make_self_reaction_data())
    assert "13" in embed.description


def test_self_reaction_embed_shows_outcome() -> None:
    embed = build_self_reaction_embed(_make_self_reaction_data())
    assert "MISS" in embed.description


# ---------------------------------------------------------------------------
# build_reaction_used_embed
# ---------------------------------------------------------------------------


def test_reaction_used_embed_title() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert embed.title == "⚡ REACTIONS AVAILABLE"


def test_reaction_used_embed_colour_is_amber() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert embed.colour == TAVERN_AMBER


def test_reaction_used_embed_shows_reactor_name() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert "Mira" in embed.description


def test_reaction_used_embed_shows_reaction_name() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert "Shield" in embed.description


def test_reaction_used_embed_shows_new_outcome() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert "MISS" in embed.description


def test_reaction_used_embed_npc_format_includes_lightning() -> None:
    data = _make_reaction_used_data(
        is_npc=True,
        reactor_name="The Lich",
        reaction_name="Legendary Resistance",
        reaction_id="legendary_resistance",
        uses_remaining=2,
    )
    embed = build_reaction_used_embed(data)
    assert "⚡" in embed.description
    assert "The Lich" in embed.description
    assert "2 remaining" in embed.description


def test_reaction_used_embed_player_format_uses_reaction_emoji() -> None:
    data = _make_reaction_used_data(is_npc=False, reaction_id="shield_spell")
    embed = build_reaction_used_embed(data)
    assert "🛡️" in embed.description


def test_reaction_used_embed_lists_remaining_reactors() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data())
    assert "Vex" in embed.description
    assert "Silvery Barbs" in embed.description


def test_reaction_used_embed_footer_shows_window_seconds() -> None:
    embed = build_reaction_used_embed(_make_reaction_used_data(window_seconds=12))
    assert "12" in embed.footer.text


# ---------------------------------------------------------------------------
# build_reaction_window_closed_embed
# ---------------------------------------------------------------------------


def test_reaction_window_closed_embed_title() -> None:
    embed = build_reaction_window_closed_embed({"final_outcome": "miss"})
    assert embed.title == "✅ Reactions Resolved"


def test_reaction_window_closed_embed_hit_is_green() -> None:
    embed = build_reaction_window_closed_embed({"final_outcome": "hit"})
    assert embed.colour == _HIT_COLOUR


def test_reaction_window_closed_embed_miss_is_red() -> None:
    embed = build_reaction_window_closed_embed({"final_outcome": "miss"})
    assert embed.colour == _MISS_COLOUR


def test_reaction_window_closed_embed_shows_final_outcome() -> None:
    embed = build_reaction_window_closed_embed({"final_outcome": "miss"})
    assert "MISS" in embed.description


def test_reaction_window_closed_embed_shows_roll_numbers_when_present() -> None:
    embed = build_reaction_window_closed_embed(
        {
            "final_outcome": "hit",
            "roll_result": {
                "natural": 17,
                "total": 21,
                "target": {"type": "ac", "value": 15},
            },
        }
    )
    assert "17" in embed.description
    assert "21" in embed.description


# ---------------------------------------------------------------------------
# ReactionWindowView — structure
# ---------------------------------------------------------------------------


def test_reaction_window_view_has_reaction_buttons() -> None:
    view = _make_reaction_window_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("Shield" in label for label in labels)
    assert any("Silvery Barbs" in label for label in labels)


def test_reaction_window_view_has_pass_buttons_per_reactor() -> None:
    view = _make_reaction_window_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("Pass" in label and "Mira" in label for label in labels)
    assert any("Pass" in label and "Vex" in label for label in labels)


def test_reaction_window_view_has_all_pass_button() -> None:
    view = _make_reaction_window_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("All pass" in label for label in labels)


def test_reaction_window_view_responded_reactors_excluded() -> None:
    view = _make_reaction_window_view(responded={"char-mira"})
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    # Mira's reaction + pass buttons should not appear; Vex's should
    assert not any("Mira" in label for label in labels)
    assert any("Vex" in label for label in labels)


def test_reaction_window_view_reactor_char_ids_excludes_responded() -> None:
    view = _make_reaction_window_view(responded={"char-mira"})
    assert "char-mira" not in view._reactor_char_ids
    assert "char-vex" in view._reactor_char_ids


# ---------------------------------------------------------------------------
# ReactionWindowView — click behaviour
# ---------------------------------------------------------------------------


async def test_reaction_view_wrong_player_rejected_on_reaction() -> None:
    view = _make_reaction_window_view()
    shield_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Shield" in b.label
    )
    interaction = _make_interaction(user_id=999)  # not Mira (111) or Vex (222)
    await shield_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    interaction.response.edit_message.assert_not_called()
    view._api.submit_reaction.assert_not_called()


async def test_reaction_view_correct_player_submits_reaction() -> None:
    view = _make_reaction_window_view()
    shield_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Shield" in b.label
    )
    interaction = _make_interaction(user_id=111)  # Mira
    await shield_btn.callback(interaction)

    view._api.submit_reaction.assert_called_once_with(
        "camp-1", "turn-1", "roll-1", "char-mira", "shield_spell"
    )


async def test_reaction_view_wrong_player_rejected_on_pass() -> None:
    view = _make_reaction_window_view()
    pass_btn = next(
        b
        for b in view.children
        if isinstance(b, discord.ui.Button) and "Pass" in b.label and "Mira" in b.label
    )
    interaction = _make_interaction(user_id=999)
    await pass_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    view._api.submit_pass.assert_not_called()


async def test_reaction_view_correct_player_submits_pass() -> None:
    view = _make_reaction_window_view()
    pass_btn = next(
        b
        for b in view.children
        if isinstance(b, discord.ui.Button) and "Pass" in b.label and "Mira" in b.label
    )
    interaction = _make_interaction(user_id=111)
    await pass_btn.callback(interaction)

    view._api.submit_pass.assert_called_once_with("camp-1", "turn-1", "roll-1", "char-mira")


async def test_reaction_view_all_pass_submits_for_all_reactors() -> None:
    view = _make_reaction_window_view()
    all_pass_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "All pass" in b.label
    )
    interaction = _make_interaction(user_id=999)  # any player can click
    await all_pass_btn.callback(interaction)

    assert view._api.submit_pass.call_count == 2
    called_char_ids = {call.args[3] for call in view._api.submit_pass.call_args_list}
    assert "char-mira" in called_char_ids
    assert "char-vex" in called_char_ids


async def test_reaction_view_unresolved_identity_is_unguarded() -> None:
    """If a character's Discord user can't be resolved, anyone can click their button."""
    view = _make_reaction_window_view(identity_map={})  # no resolved users
    shield_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Shield" in b.label
    )
    interaction = _make_interaction(user_id=999)
    await shield_btn.callback(interaction)

    # Should not be rejected — unresolved identity is unguarded.
    interaction.response.send_message.assert_not_called()
    view._api.submit_reaction.assert_called_once()


# ---------------------------------------------------------------------------
# SelfReactionView — structure
# ---------------------------------------------------------------------------


def _make_self_reaction_view(**overrides) -> SelfReactionView:
    defaults: dict = {  # type: ignore[type-arg]
        "api": _make_api(),
        "campaign_id": "camp-1",
        "turn_id": "turn-1",
        "roll_id": "roll-1",
        "character_id": "char-kael",
        "rolling_player_id": 111,
        "self_reactions": [
            {"id": "lucky_feat", "name": "Lucky", "uses_remaining": 2},
        ],
        "timeout": 10.0,
    }
    defaults.update(overrides)
    return SelfReactionView(**defaults)


def test_self_reaction_view_has_reaction_button() -> None:
    view = _make_self_reaction_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("Lucky" in label for label in labels)


def test_self_reaction_view_shows_uses_remaining() -> None:
    view = _make_self_reaction_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("2" in label for label in labels)


def test_self_reaction_view_has_accept_button() -> None:
    view = _make_self_reaction_view()
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    assert any("Accept" in label for label in labels)


def test_self_reaction_view_multiple_reactions() -> None:
    view = _make_self_reaction_view(
        self_reactions=[
            {"id": "lucky_feat", "name": "Lucky", "uses_remaining": 1},
            {"id": "lucky_feat", "name": "Lucky Again", "uses_remaining": 1},
        ]
    )
    labels = [b.label for b in view.children if isinstance(b, discord.ui.Button)]
    # 2 self-reaction buttons + 1 accept button
    assert len(labels) == 3


# ---------------------------------------------------------------------------
# SelfReactionView — click behaviour
# ---------------------------------------------------------------------------


async def test_self_reaction_view_wrong_player_rejected_on_reaction() -> None:
    view = _make_self_reaction_view()
    lucky_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Lucky" in b.label
    )
    interaction = _make_interaction(user_id=999)
    await lucky_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    view._api.submit_reaction.assert_not_called()


async def test_self_reaction_view_correct_player_submits_reaction() -> None:
    view = _make_self_reaction_view()
    lucky_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Lucky" in b.label
    )
    interaction = _make_interaction(user_id=111)
    await lucky_btn.callback(interaction)

    view._api.submit_reaction.assert_called_once_with(
        "camp-1", "turn-1", "roll-1", "char-kael", "lucky_feat"
    )


async def test_self_reaction_view_wrong_player_rejected_on_accept() -> None:
    view = _make_self_reaction_view()
    accept_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Accept" in b.label
    )
    interaction = _make_interaction(user_id=999)
    await accept_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    view._api.submit_pass.assert_not_called()


async def test_self_reaction_view_accept_submits_pass() -> None:
    view = _make_self_reaction_view()
    accept_btn = next(
        b for b in view.children if isinstance(b, discord.ui.Button) and "Accept" in b.label
    )
    interaction = _make_interaction(user_id=111)
    await accept_btn.callback(interaction)

    view._api.submit_pass.assert_called_once_with("camp-1", "turn-1", "roll-1", "char-kael")
