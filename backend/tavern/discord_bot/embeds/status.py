"""Campaign status embed builder.

Standalone helper that turns a campaign API response dict into a rich
``discord.Embed``.  Kept separate from ``cogs/campaign.py`` so the embed
logic can be tested without instantiating the cog.
"""

from __future__ import annotations

import discord

TAVERN_AMBER = discord.Colour(0xD4A24E)

# Maximum scene description length before truncation.
_MAX_SCENE_LEN = 300


def build_campaign_status_embed(campaign_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build a rich campaign status embed from an API campaign response.

    Handles both the top-level campaign fields (name, status, dm_persona) and
    the nested ``state`` object (turn_count, scene_context, in_combat).

    Args:
        campaign_data: Raw dict as returned by ``TavernAPI.get_campaign``.

    Returns:
        A ``discord.Embed`` ready to send.
    """
    name = campaign_data.get("name") or "Campaign"
    status = campaign_data.get("status") or "unknown"
    dm_persona = campaign_data.get("dm_persona") or "—"
    world = campaign_data.get("world") or "—"

    state: dict = campaign_data.get("state") or {}  # type: ignore[assignment]
    turn_count = state.get("turn_count", 0)
    in_combat = bool(state.get("in_combat", False))
    scene = state.get("scene_context") or "—"

    if len(scene) > _MAX_SCENE_LEN:
        scene = scene[: _MAX_SCENE_LEN - 3] + "..."

    mode_icon = "⚔️" if in_combat else "🗺️"
    mode_label = "Combat" if in_combat else "Exploration"

    embed = discord.Embed(
        title=f"📊 {name}",
        colour=TAVERN_AMBER,
    )
    embed.add_field(name="Status", value=status.capitalize(), inline=True)
    embed.add_field(name="Mode", value=f"{mode_icon} {mode_label}", inline=True)
    embed.add_field(name="Turns", value=str(turn_count), inline=True)
    embed.add_field(name="World", value=world, inline=True)
    embed.add_field(name="Narrator Tone", value=dm_persona, inline=True)
    embed.add_field(name="Current Scene", value=scene, inline=False)

    return embed
