"""Tests for embeds/status.py — build_campaign_status_embed."""

from __future__ import annotations

from tavern.discord_bot.embeds.status import build_campaign_status_embed

# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_title_includes_campaign_name() -> None:
    embed = build_campaign_status_embed({"name": "Shattered Coast"})
    assert "Shattered Coast" in embed.title


def test_title_fallback_when_no_name() -> None:
    embed = build_campaign_status_embed({})
    assert "Campaign" in embed.title


def test_status_field_present() -> None:
    embed = build_campaign_status_embed({"status": "active"})
    field_names = [f.name for f in embed.fields]
    assert "Status" in field_names


def test_status_field_value_capitalised() -> None:
    embed = build_campaign_status_embed({"status": "active"})
    status_field = next(f for f in embed.fields if f.name == "Status")
    assert status_field.value == "Active"


def test_default_status_when_missing() -> None:
    embed = build_campaign_status_embed({})
    status_field = next(f for f in embed.fields if f.name == "Status")
    assert status_field.value == "Unknown"


# ---------------------------------------------------------------------------
# Mode field (combat / exploration)
# ---------------------------------------------------------------------------


def test_mode_exploration_when_not_in_combat() -> None:
    embed = build_campaign_status_embed({"state": {"in_combat": False}})
    mode_field = next(f for f in embed.fields if f.name == "Mode")
    assert "Exploration" in mode_field.value


def test_mode_combat_when_in_combat() -> None:
    embed = build_campaign_status_embed({"state": {"in_combat": True}})
    mode_field = next(f for f in embed.fields if f.name == "Mode")
    assert "Combat" in mode_field.value


def test_mode_defaults_to_exploration_when_state_absent() -> None:
    embed = build_campaign_status_embed({})
    mode_field = next(f for f in embed.fields if f.name == "Mode")
    assert "Exploration" in mode_field.value


# ---------------------------------------------------------------------------
# Turn count
# ---------------------------------------------------------------------------


def test_turns_field_shows_count() -> None:
    embed = build_campaign_status_embed({"state": {"turn_count": 42}})
    turns_field = next(f for f in embed.fields if f.name == "Turns")
    assert turns_field.value == "42"


def test_turns_defaults_to_zero() -> None:
    embed = build_campaign_status_embed({})
    turns_field = next(f for f in embed.fields if f.name == "Turns")
    assert turns_field.value == "0"


# ---------------------------------------------------------------------------
# World and narrator tone
# ---------------------------------------------------------------------------


def test_world_field_shown() -> None:
    embed = build_campaign_status_embed({"world": "Forgotten Realms"})
    world_field = next(f for f in embed.fields if f.name == "World")
    assert "Forgotten Realms" in world_field.value


def test_world_defaults_to_dash() -> None:
    embed = build_campaign_status_embed({})
    world_field = next(f for f in embed.fields if f.name == "World")
    assert world_field.value == "—"


def test_narrator_tone_field_shown() -> None:
    embed = build_campaign_status_embed({"dm_persona": "gritty"})
    tone_field = next(f for f in embed.fields if f.name == "Narrator Tone")
    assert "gritty" in tone_field.value


def test_narrator_tone_defaults_to_dash() -> None:
    embed = build_campaign_status_embed({})
    tone_field = next(f for f in embed.fields if f.name == "Narrator Tone")
    assert tone_field.value == "—"


# ---------------------------------------------------------------------------
# Scene / description field
# ---------------------------------------------------------------------------


def test_scene_field_present() -> None:
    embed = build_campaign_status_embed({"state": {"scene_context": "A dark forest."}})
    field_names = [f.name for f in embed.fields]
    assert "Current Scene" in field_names


def test_scene_field_value() -> None:
    embed = build_campaign_status_embed({"state": {"scene_context": "A dark forest."}})
    scene_field = next(f for f in embed.fields if f.name == "Current Scene")
    assert "A dark forest." in scene_field.value


def test_scene_truncated_when_long() -> None:
    long_scene = "X" * 500
    embed = build_campaign_status_embed({"state": {"scene_context": long_scene}})
    scene_field = next(f for f in embed.fields if f.name == "Current Scene")
    assert len(scene_field.value) <= 303  # _MAX_SCENE_LEN + "..." = 303


def test_scene_defaults_to_dash_when_absent() -> None:
    embed = build_campaign_status_embed({})
    scene_field = next(f for f in embed.fields if f.name == "Current Scene")
    assert scene_field.value == "—"


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def test_embed_colour_is_tavern_amber() -> None:
    from tavern.discord_bot.embeds.status import TAVERN_AMBER

    embed = build_campaign_status_embed({})
    assert embed.colour == TAVERN_AMBER


# ---------------------------------------------------------------------------
# Full data roundtrip
# ---------------------------------------------------------------------------


def test_full_campaign_data() -> None:
    data = {
        "name": "Shattered Coast",
        "status": "active",
        "dm_persona": "gritty noir",
        "world": "Eberron",
        "state": {
            "turn_count": 17,
            "in_combat": True,
            "scene_context": "The party stands at the edge of the ruined citadel.",
        },
    }
    embed = build_campaign_status_embed(data)
    assert "Shattered Coast" in embed.title
    field_map = {f.name: f.value for f in embed.fields}
    assert field_map["Status"] == "Active"
    assert "Combat" in field_map["Mode"]
    assert field_map["Turns"] == "17"
    assert field_map["World"] == "Eberron"
    assert "gritty noir" in field_map["Narrator Tone"]
    assert "ruined citadel" in field_map["Current Scene"]
