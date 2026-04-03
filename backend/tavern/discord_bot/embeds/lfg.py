"""LFG embed builder.

Pure function — no I/O, no discord.py state.  Takes description and player
data, returns a ``discord.Embed`` ready to send or edit into a message.
"""

from __future__ import annotations

import discord

# Tavern amber — used consistently across all bot embeds.
TAVERN_AMBER = discord.Colour(0xD4A24E)


def build_lfg_embed(
    description: str,
    creator: str,
    players: list[str],
) -> discord.Embed:
    """Build the Looking For Group embed.

    Args:
        description: Free-text description from the /lfg command.
        creator:     Display name of the player who posted the LFG.
        players:     Display names of *all* joined players, creator first.

    Returns:
        A ``discord.Embed`` ready to be sent or used to edit an existing message.
    """
    count = len(players)
    player_list = ", ".join(players) if players else creator

    embed = discord.Embed(
        title="🎲 Looking for Adventurers!",
        description=description,
        colour=TAVERN_AMBER,
    )
    embed.add_field(name="👥 Players", value=f"{count} joined", inline=True)
    embed.add_field(name="Party", value=player_list, inline=True)
    embed.set_footer(text="Click ⚔️ Join to sign up  ·  🚀 Launch to start the campaign")

    return embed
