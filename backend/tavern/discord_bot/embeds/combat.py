"""Combat result embed builders.

Pure functions — no I/O, no discord.py state.  Take structured mechanical
result data (as returned by the Tavern API / WebSocket events) and return
``discord.Embed`` objects or formatted strings ready to send.

Colour convention (per discord-bot.md Embed Design):
    Green  — successful player actions (hit, kill, heal)
    Red    — damage taken by players
    Amber  — status effects / neutral outcomes
"""

from __future__ import annotations

import discord

# Shared across all bot embeds.
TAVERN_AMBER = discord.Colour(0xD4A24E)
_GREEN = discord.Colour(0x57F287)
_RED = discord.Colour(0xED4245)

# Result types that indicate something bad happened to a player.
_DAMAGE_TAKEN_TYPES = {"damage_taken", "player_damage"}


def build_combat_embed(results: list[dict]) -> discord.Embed:  # type: ignore[type-arg]
    """Build the ⚔️ Combat Results embed from a list of mechanical results.

    Each element of *results* is a dict with at least a ``"type"`` key.
    Recognised types:

    ``damage``
        A creature took damage.  Keys: ``target``, ``amount``,
        ``damage_type``, optional ``source``.

    ``miss``
        An attack missed.  Keys: ``attacker``, ``target``.

    ``heal``
        A creature was healed.  Keys: ``target``, ``amount``.

    ``condition_added``
        A condition was applied.  Keys: ``target``, ``condition``.

    ``condition_removed``
        A condition was removed.  Keys: ``target``, ``condition``.
        If ``condition`` is ``"alive"`` this is rendered as "Defeated".

    Unknown types are rendered as a generic line so new result types do not
    silently disappear from the embed.

    Args:
        results: List of mechanical result dicts (may be empty).

    Returns:
        A ``discord.Embed`` with one field per result.
    """
    # Pick embed colour based on result types present.
    colour = _choose_colour(results)
    embed = discord.Embed(title="⚔️ Combat Results", colour=colour)

    if not results:
        embed.description = "No mechanical results."
        return embed

    for result in results:
        result_type = result.get("type", "unknown")
        field_name, field_value = _format_result(result_type, result)
        embed.add_field(name=field_name, value=field_value, inline=False)

    return embed


def build_party_status(characters: list[dict]) -> str:  # type: ignore[type-arg]
    """Build the inline party status line shown after combat results.

    Example output::

        📊 Kael 32/38 · Mira 24/28

    Args:
        characters: List of character dicts, each with at least ``"name"``,
                    ``"hp"``, and ``"max_hp"`` keys.

    Returns:
        A formatted string.  Returns an empty string if *characters* is empty.
    """
    if not characters:
        return ""

    parts: list[str] = []
    for char in characters:
        name = char.get("name", "?")
        hp = char.get("hp", 0)
        max_hp = char.get("max_hp", 0)
        parts.append(f"{name} {hp}/{max_hp}")

    return "📊 " + " · ".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _choose_colour(results: list[dict]) -> discord.Colour:  # type: ignore[type-arg]
    """Return an embed colour based on the nature of the results."""
    types = {r.get("type", "") for r in results}
    if types & _DAMAGE_TAKEN_TYPES:
        return _RED
    if {"damage", "condition_removed"} & types:
        return _GREEN
    return TAVERN_AMBER


def _format_result(
    result_type: str,
    result: dict,  # type: ignore[type-arg]
) -> tuple[str, str]:
    """Return (field_name, field_value) for a single mechanical result."""
    if result_type == "damage":
        target = result.get("target", "Unknown")
        amount = result.get("amount", 0)
        dmg_type = result.get("damage_type", "")
        source = result.get("source", "")
        if source:
            value = f"{source} → {target}: {amount} {dmg_type} damage"
        else:
            value = f"{target}: {amount} {dmg_type} damage"
        return "⚔️ Damage", value

    if result_type == "miss":
        attacker = result.get("attacker", "Unknown")
        target = result.get("target", "Unknown")
        return "❌ Miss", f"{attacker} misses {target}"

    if result_type == "heal":
        target = result.get("target", "Unknown")
        amount = result.get("amount", 0)
        return "💚 Healed", f"{target} heals {amount} HP"

    if result_type == "condition_added":
        target = result.get("target", "Unknown")
        condition = result.get("condition", "unknown")
        return "⚡ Condition", f"{target}: {condition}"

    if result_type == "condition_removed":
        target = result.get("target", "Unknown")
        condition = result.get("condition", "unknown")
        if condition == "alive":
            return "💀 Defeated", f"{target} is defeated!"
        return "✅ Condition Removed", f"{target}: {condition} removed"

    # Unknown type — render generically so new server result types are visible.
    value = ", ".join(f"{k}={v}" for k, v in result.items() if k != "type")
    return f"📋 {result_type}", value or "—"
