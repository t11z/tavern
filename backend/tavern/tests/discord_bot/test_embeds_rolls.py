"""Tests for embeds/rolls.py — build_roll_prompt_embed, RollPromptView,
and build_roll_result_embed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord

from tavern.discord_bot.embeds.rolls import (
    _CRIT_HIT_COLOUR,
    _HIT_COLOUR,
    _MISS_COLOUR,
    TAVERN_AMBER,
    RollPromptView,
    _format_target,
    _option_emoji,
    build_roll_prompt_embed,
    build_roll_result_embed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_api() -> MagicMock:
    api = MagicMock()
    api.execute_roll = AsyncMock(return_value={})
    return api


def _make_basic_roll_data(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "description": "Kael attacks Goblin A",
        "type": "attack",
        "dice": "1d20",
        "base_modifier": 5,
        "target": {"type": "ac", "value": 15, "target_name": "Goblin A"},
        "timeout_seconds": 120,
    }
    base.update(overrides)
    return base


def _make_result_data(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "dice": "1d20",
        "natural_result": 14,
        "modifier": 5,
        "total": 19,
        "target": {"type": "ac", "value": 15},
        "outcome": "hit",
        "advantage": False,
        "rolls": [14],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _format_target
# ---------------------------------------------------------------------------


def test_format_target_ac() -> None:
    assert _format_target({"type": "ac", "value": 15}) == "AC 15"


def test_format_target_ac_with_name() -> None:
    assert (
        _format_target({"type": "ac", "value": 15, "target_name": "Goblin A"})
        == "AC 15 (Goblin A)"
    )


def test_format_target_dc() -> None:
    assert _format_target({"type": "dc", "value": 14}) == "DC 14"


def test_format_target_empty() -> None:
    result = _format_target({})
    assert result == "?"


def test_format_target_unknown_type() -> None:
    result = _format_target({"type": "custom", "value": 10})
    assert "10" in result


# ---------------------------------------------------------------------------
# _option_emoji
# ---------------------------------------------------------------------------


def test_option_emoji_reckless_attack() -> None:
    assert _option_emoji("reckless_attack") == "⚡"


def test_option_emoji_sharpshooter() -> None:
    assert _option_emoji("sharpshooter") == "🎯"


def test_option_emoji_bardic_inspiration() -> None:
    assert _option_emoji("bardic_inspiration") == "🎵"


def test_option_emoji_unknown_defaults_to_gem() -> None:
    assert _option_emoji("something_new") == "🔮"


# ---------------------------------------------------------------------------
# build_roll_prompt_embed
# ---------------------------------------------------------------------------


def test_prompt_embed_title_contains_description() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "Kael attacks Goblin A" in embed.title


def test_prompt_embed_title_starts_with_sword() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert embed.title.startswith("⚔️")


def test_prompt_embed_description_contains_roll_type() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "attack" in embed.description.lower()


def test_prompt_embed_description_contains_dice() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "1d20" in embed.description


def test_prompt_embed_description_contains_modifier() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "5" in embed.description


def test_prompt_embed_description_contains_target() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "AC 15" in embed.description


def test_prompt_embed_colour_is_amber() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert embed.colour == TAVERN_AMBER


def test_prompt_embed_footer_shows_timeout() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data())
    assert "120" in embed.footer.text
    assert "⏱️" in embed.footer.text


def test_prompt_embed_custom_timeout_in_footer() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data(timeout_seconds=60))
    assert "60" in embed.footer.text


def test_prompt_embed_negative_modifier_formatted_correctly() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data(base_modifier=-2))
    assert "- 2" in embed.description


def test_prompt_embed_zero_modifier() -> None:
    embed = build_roll_prompt_embed(_make_basic_roll_data(base_modifier=0))
    assert "0" in embed.description


def test_prompt_embed_missing_target_graceful() -> None:
    data = _make_basic_roll_data()
    data.pop("target")
    embed = build_roll_prompt_embed(data)
    assert embed.description is not None


# ---------------------------------------------------------------------------
# RollPromptView — structure
# ---------------------------------------------------------------------------


def test_view_has_plain_roll_button() -> None:
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=[],
    )
    labels = [item.label for item in view.children if isinstance(item, discord.ui.Button)]
    assert "🎲 Roll" in labels


def test_view_single_option_adds_button() -> None:
    option = {"id": "reckless_attack", "name": "Reckless Attack", "available": True}
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=[option],
    )
    labels = [item.label for item in view.children if isinstance(item, discord.ui.Button)]
    assert len(labels) == 2  # plain + option
    assert any("Reckless Attack" in label for label in labels)


def test_view_option_button_has_contextual_emoji() -> None:
    option = {"id": "sharpshooter", "name": "Sharpshooter", "available": True}
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=[option],
    )
    option_buttons = [
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.label != "🎲 Roll"
    ]
    assert len(option_buttons) == 1
    assert "🎯" in option_buttons[0].label


def test_view_unavailable_option_skipped() -> None:
    options = [
        {"id": "reckless_attack", "name": "Reckless", "available": False},
        {"id": "sharpshooter", "name": "Sharp", "available": True},
    ]
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=options,
    )
    labels = [item.label for item in view.children if isinstance(item, discord.ui.Button)]
    # Only plain + sharpshooter (reckless skipped).
    assert len(labels) == 2
    assert not any("Reckless" in label for label in labels)


def test_view_multiple_options() -> None:
    options = [
        {"id": "reckless_attack", "name": "Reckless Attack", "available": True},
        {"id": "great_weapon_master", "name": "GWM", "available": True},
    ]
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=options,
    )
    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    assert len(buttons) == 3  # plain + 2 options


def test_view_plain_button_style_is_primary() -> None:
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=[],
    )
    plain = next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.label == "🎲 Roll"
    )
    assert plain.style == discord.ButtonStyle.primary


def test_view_option_button_style_is_secondary() -> None:
    option = {"id": "reckless_attack", "name": "Reckless Attack", "available": True}
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=123,
        pre_roll_options=[option],
    )
    option_btn = next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.label != "🎲 Roll"
    )
    assert option_btn.style == discord.ButtonStyle.secondary


# ---------------------------------------------------------------------------
# RollPromptView — click behaviour
# ---------------------------------------------------------------------------


async def test_view_rejects_wrong_player() -> None:
    view = RollPromptView(
        api=_make_api(),
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=999,  # only user 999 may click
        pre_roll_options=[],
    )
    plain_btn = next(item for item in view.children if isinstance(item, discord.ui.Button))
    interaction = MagicMock()
    interaction.user.id = 123  # wrong user
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()

    await plain_btn.callback(interaction)

    interaction.response.send_message.assert_called_once()
    # Should NOT call edit_message (i.e. did not proceed to disable buttons).
    interaction.response.edit_message.assert_not_called()


async def test_view_accepts_correct_player_and_calls_api() -> None:
    api = _make_api()
    view = RollPromptView(
        api=api,
        campaign_id="camp-1",
        turn_id="turn-1",
        roll_id="roll-1",
        active_player_id=999,
        pre_roll_options=[],
    )
    plain_btn = next(item for item in view.children if isinstance(item, discord.ui.Button))
    interaction = MagicMock()
    interaction.user.id = 999  # correct user
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    await plain_btn.callback(interaction)

    api.execute_roll.assert_called_once_with("camp-1", "turn-1", "roll-1", [])


async def test_view_disables_buttons_on_click() -> None:
    api = _make_api()
    view = RollPromptView(
        api=api,
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=999,
        pre_roll_options=[{"id": "reckless_attack", "name": "Reckless", "available": True}],
    )
    plain_btn = next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.label == "🎲 Roll"
    )
    interaction = MagicMock()
    interaction.user.id = 999
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    await plain_btn.callback(interaction)

    for item in view.children:
        if isinstance(item, discord.ui.Button):
            assert item.disabled is True


async def test_view_option_button_passes_option_to_api() -> None:
    api = _make_api()
    option = {"id": "reckless_attack", "name": "Reckless Attack", "available": True}
    view = RollPromptView(
        api=api,
        campaign_id="camp-1",
        turn_id="turn-1",
        roll_id="roll-1",
        active_player_id=999,
        pre_roll_options=[option],
    )
    option_btn = next(
        item
        for item in view.children
        if isinstance(item, discord.ui.Button) and item.label != "🎲 Roll"
    )
    interaction = MagicMock()
    interaction.user.id = 999
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    await option_btn.callback(interaction)

    api.execute_roll.assert_called_once_with("camp-1", "turn-1", "roll-1", ["reckless_attack"])


async def test_view_api_error_sends_followup() -> None:
    from tavern.discord_bot.services.api_client import TavernAPIError

    api = _make_api()
    api.execute_roll = AsyncMock(side_effect=TavernAPIError(500, "Server error"))
    view = RollPromptView(
        api=api,
        campaign_id="c1",
        turn_id="t1",
        roll_id="r1",
        active_player_id=999,
        pre_roll_options=[],
    )
    plain_btn = next(item for item in view.children if isinstance(item, discord.ui.Button))
    interaction = MagicMock()
    interaction.user.id = 999
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    await plain_btn.callback(interaction)

    interaction.followup.send.assert_called_once()
    call_kwargs = interaction.followup.send.call_args
    assert "Server error" in call_kwargs.args[0]


# ---------------------------------------------------------------------------
# build_roll_result_embed — basic structure
# ---------------------------------------------------------------------------


def test_result_embed_title_normal_hit() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="hit"))
    assert "🎲" in embed.title
    assert "CRITICAL" not in embed.title


def test_result_embed_description_contains_natural_result() -> None:
    embed = build_roll_result_embed(_make_result_data(natural_result=14))
    assert "14" in embed.description


def test_result_embed_description_contains_total() -> None:
    embed = build_roll_result_embed(_make_result_data(total=19))
    assert "19" in embed.description


def test_result_embed_description_contains_target() -> None:
    embed = build_roll_result_embed(_make_result_data(target={"type": "ac", "value": 15}))
    assert "AC 15" in embed.description


def test_result_embed_description_contains_outcome() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="hit"))
    assert "HIT" in embed.description


# ---------------------------------------------------------------------------
# build_roll_result_embed — colours
# ---------------------------------------------------------------------------


def test_result_hit_colour_is_green() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="hit"))
    assert embed.colour == _HIT_COLOUR


def test_result_success_colour_is_green() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="success"))
    assert embed.colour == _HIT_COLOUR


def test_result_save_colour_is_green() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="save"))
    assert embed.colour == _HIT_COLOUR


def test_result_miss_colour_is_red() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="miss"))
    assert embed.colour == _MISS_COLOUR


def test_result_fail_colour_is_red() -> None:
    embed = build_roll_result_embed(_make_result_data(outcome="fail"))
    assert embed.colour == _MISS_COLOUR


# ---------------------------------------------------------------------------
# build_roll_result_embed — natural 20 / 1
# ---------------------------------------------------------------------------


def test_result_nat_20_title_is_critical_hit() -> None:
    embed = build_roll_result_embed(_make_result_data(natural_result=20, outcome="hit"))
    assert "CRITICAL HIT" in embed.title


def test_result_nat_20_colour_is_gold() -> None:
    embed = build_roll_result_embed(_make_result_data(natural_result=20, outcome="hit"))
    assert embed.colour == _CRIT_HIT_COLOUR


def test_result_nat_1_title_is_critical_miss() -> None:
    embed = build_roll_result_embed(_make_result_data(natural_result=1, outcome="miss"))
    assert "Critical Miss" in embed.title


def test_result_nat_1_colour_is_red() -> None:
    embed = build_roll_result_embed(_make_result_data(natural_result=1, outcome="miss"))
    assert embed.colour == _MISS_COLOUR


# ---------------------------------------------------------------------------
# build_roll_result_embed — advantage
# ---------------------------------------------------------------------------


def test_result_advantage_shows_both_dice() -> None:
    embed = build_roll_result_embed(
        _make_result_data(advantage=True, natural_result=14, rolls=[14, 8])
    )
    assert "14" in embed.description
    assert "8" in embed.description


def test_result_advantage_lower_die_is_struck_through() -> None:
    embed = build_roll_result_embed(
        _make_result_data(advantage=True, natural_result=14, rolls=[14, 8])
    )
    # Lower value should be wrapped in Discord strikethrough markers.
    assert "~~8~~" in embed.description


def test_result_no_advantage_plain_format() -> None:
    embed = build_roll_result_embed(
        _make_result_data(advantage=False, natural_result=14, rolls=[14])
    )
    # No strikethrough.
    assert "~~" not in embed.description


# ---------------------------------------------------------------------------
# build_roll_result_embed — negative modifier
# ---------------------------------------------------------------------------


def test_result_negative_modifier_formatted_correctly() -> None:
    embed = build_roll_result_embed(_make_result_data(modifier=-2))
    assert "- 2" in embed.description


def test_result_zero_modifier() -> None:
    embed = build_roll_result_embed(_make_result_data(modifier=0))
    assert "0" in embed.description


# ---------------------------------------------------------------------------
# build_roll_result_embed — next roll hint
# ---------------------------------------------------------------------------


def test_result_no_next_roll_no_field() -> None:
    embed = build_roll_result_embed(_make_result_data())
    field_names = [f.name for f in embed.fields]
    assert "⏭️ Up Next" not in field_names


def test_result_next_roll_adds_field() -> None:
    data = _make_result_data()
    data["next_roll"] = {"type": "damage", "dice": "2d6", "modifier": 3}
    embed = build_roll_result_embed(data)
    field_names = [f.name for f in embed.fields]
    assert "⏭️ Up Next" in field_names


def test_result_next_roll_field_contains_dice() -> None:
    data = _make_result_data()
    data["next_roll"] = {"type": "damage", "dice": "2d6", "modifier": 3}
    embed = build_roll_result_embed(data)
    up_next = next(f for f in embed.fields if f.name == "⏭️ Up Next")
    assert "2d6" in up_next.value
    assert "damage" in up_next.value.lower()
