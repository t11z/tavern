"""Character sheet embed builders.

Provides three embed builders that accept a raw character API response dict:

  build_character_sheet_embed(character_data) — full character sheet with HP
      bar, ability scores, AC/speed, conditions, and equipment summary
  build_inventory_embed(character_data)       — detailed equipment list
  build_spells_embed(character_data)          — cantrips, prepared spells, and
      spell slots; non-spellcasters get a short "no spells" message

All functions are pure (no I/O).  They tolerate missing fields by substituting
sensible defaults so they will not raise on a partial API response.
"""

from __future__ import annotations

import discord

# ---------------------------------------------------------------------------
# Class → colour map  (spec-defined hex values)
# ---------------------------------------------------------------------------

_CLASS_COLOUR: dict[str, discord.Colour] = {
    "barbarian": discord.Colour(0xE74C3C),
    "bard": discord.Colour(0x9B59B6),
    "cleric": discord.Colour(0xF1C40F),
    "druid": discord.Colour(0x2ECC71),
    "fighter": discord.Colour(0xE67E22),
    "monk": discord.Colour(0x1ABC9C),
    "paladin": discord.Colour(0xF39C12),
    "ranger": discord.Colour(0x27AE60),
    "rogue": discord.Colour(0x7F8C8D),
    "sorcerer": discord.Colour(0xE91E63),
    "warlock": discord.Colour(0x8E44AD),
    "wizard": discord.Colour(0x3498DB),
}

_DEFAULT_COLOUR = discord.Colour(0xD4A24E)  # Tavern amber

# Classes that have a spell system.
_SPELLCASTER_CLASSES = frozenset(
    {"bard", "cleric", "druid", "paladin", "ranger", "sorcerer", "warlock", "wizard"}
)

# HP bar characters.
_BAR_FILLED = "█"
_BAR_EMPTY = "░"
_BAR_WIDTH = 10

# Maximum equipment items shown in the character sheet summary.
_SHEET_EQUIP_MAX = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _class_colour(class_name: str) -> discord.Colour:
    return _CLASS_COLOUR.get(class_name.lower().strip(), _DEFAULT_COLOUR)


def _hp_bar(current: int, max_hp: int) -> str:
    """Return a 10-character visual HP bar, e.g. ``████░░░░░░``."""
    if max_hp <= 0:
        return _BAR_EMPTY * _BAR_WIDTH
    ratio = max(0.0, min(1.0, current / max_hp))
    filled = round(ratio * _BAR_WIDTH)
    return _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)


def _modifier(score: int) -> str:
    """Return a signed modifier string, e.g. ``+3`` or ``-1``."""
    mod = (score - 10) // 2
    return f"+{mod}" if mod >= 0 else str(mod)


def _ability_scores_value(scores: dict) -> str:  # type: ignore[type-arg]
    """Build a compact ability-scores line: ``STR 16 (+3)  DEX 14 (+2)  …``"""
    parts: list[str] = []
    for stat in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
        # Accept both "str" and "STR" as keys in the API response.
        score: int = scores.get(stat.lower(), scores.get(stat, 10))
        parts.append(f"**{stat}** {score} ({_modifier(score)})")
    return "  ".join(parts)


def _item_name(item: dict | str) -> str:  # type: ignore[type-arg]
    return item.get("name", "Unknown") if isinstance(item, dict) else str(item)


def _item_details(item: dict | str) -> str:  # type: ignore[type-arg]
    if not isinstance(item, dict):
        return "—"
    parts: list[str] = []
    if item.get("type"):
        parts.append(str(item["type"]))
    if item.get("damage"):
        parts.append(f"Damage: {item['damage']}")
    if item.get("weight") is not None:
        parts.append(f"Weight: {item['weight']} lb")
    props = item.get("properties")
    if props and isinstance(props, list):
        parts.append(", ".join(str(p) for p in props))
    return "  ·  ".join(parts) if parts else "—"


def _spell_name(spell: dict | str) -> str:  # type: ignore[type-arg]
    return spell.get("name", "Unknown") if isinstance(spell, dict) else str(spell)


# ---------------------------------------------------------------------------
# Character sheet embed
# ---------------------------------------------------------------------------


def build_character_sheet_embed(character_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build a full character sheet embed.

    Args:
        character_data: Raw dict from ``GET /api/campaigns/{id}/characters/{char_id}``.
                        Expected keys: ``name``, ``level``, ``class_name`` (or ``class``),
                        ``species`` (or ``race``), ``subclass``, ``hp``, ``max_hp``,
                        ``ac``, ``speed``, ``ability_scores``, ``conditions``,
                        ``equipment``.

    Returns:
        A class-coloured ``discord.Embed`` with HP bar and ability scores.
    """
    name: str = character_data.get("name") or "Unknown"
    level: int = character_data.get("level", 1)
    class_name: str = character_data.get("class_name") or character_data.get("class") or "—"
    species: str = character_data.get("species") or character_data.get("race") or "—"
    subclass: str = character_data.get("subclass") or ""

    hp: int = character_data.get("hp", 0)
    max_hp: int = character_data.get("max_hp", 1)
    ac: int = character_data.get("ac", 10)
    speed: int = character_data.get("speed", 30)

    ability_scores: dict = character_data.get("ability_scores") or {}  # type: ignore[assignment]
    conditions: list = character_data.get("conditions") or []
    equipment: list = character_data.get("equipment") or []

    colour = _class_colour(class_name)

    description = f"Level {level} {species} {class_name}"
    if subclass:
        description += f" ({subclass})"

    embed = discord.Embed(title=f"🛡️ {name}", description=description, colour=colour)

    # HP bar
    bar = _hp_bar(hp, max_hp)
    embed.add_field(name="❤️ HP", value=f"{bar} {hp}/{max_hp}", inline=False)

    # AC and Speed — two inline columns, blank spacer for even grid
    embed.add_field(name="🛡️ AC", value=str(ac), inline=True)
    embed.add_field(name="💨 Speed", value=f"{speed} ft", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Ability scores
    if ability_scores:
        embed.add_field(
            name="Ability Scores",
            value=_ability_scores_value(ability_scores),
            inline=False,
        )

    # Conditions
    conditions_str = ", ".join(str(c) for c in conditions) if conditions else "None"
    embed.add_field(name="⚠️ Conditions", value=conditions_str, inline=False)

    # Equipment summary (top 5 items)
    if equipment:
        shown = equipment[:_SHEET_EQUIP_MAX]
        lines = [f"• {_item_name(i)}" for i in shown]
        if len(equipment) > _SHEET_EQUIP_MAX:
            lines.append(f"*...and {len(equipment) - _SHEET_EQUIP_MAX} more*")
        embed.add_field(name="🎒 Equipment", value="\n".join(lines), inline=False)

    return embed


# ---------------------------------------------------------------------------
# Inventory embed
# ---------------------------------------------------------------------------


def build_inventory_embed(character_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build a detailed inventory embed showing all equipment with item stats.

    Args:
        character_data: Raw character API dict.  Uses ``name``, ``class_name``
                        (for colour), and ``equipment`` (list of item dicts or
                        strings).

    Returns:
        A class-coloured ``discord.Embed`` with one field per item.
    """
    name: str = character_data.get("name") or "Character"
    class_name: str = character_data.get("class_name") or character_data.get("class") or ""
    equipment: list = character_data.get("equipment") or []
    colour = _class_colour(class_name)

    embed = discord.Embed(title=f"🎒 {name}'s Inventory", colour=colour)

    if not equipment:
        embed.description = "No items in inventory."
        return embed

    for item in equipment:
        embed.add_field(name=_item_name(item), value=_item_details(item), inline=False)

    return embed


# ---------------------------------------------------------------------------
# Spells embed
# ---------------------------------------------------------------------------


def build_spells_embed(character_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build a spells embed showing cantrips, prepared spells, and spell slots.

    For non-spellcaster classes the embed contains only a short explanatory
    message.

    Args:
        character_data: Raw character API dict.  Uses ``name``, ``class_name``,
                        ``cantrips``, ``spells_known`` (or ``spells_prepared``),
                        and ``spell_slots`` (dict of level → ``{total, used}``).

    Returns:
        A class-coloured ``discord.Embed``.
    """
    name: str = character_data.get("name") or "Character"
    class_name: str = (
        (character_data.get("class_name") or character_data.get("class") or "").lower().strip()
    )
    colour = _class_colour(class_name)

    embed = discord.Embed(title=f"✨ {name}'s Spells", colour=colour)

    # Non-spellcasters get an early exit.
    if class_name and class_name not in _SPELLCASTER_CLASSES:
        embed.description = "Your character doesn't use spells."
        return embed

    cantrips: list = character_data.get("cantrips") or []
    spells: list = (
        character_data.get("spells_known") or character_data.get("spells_prepared") or []
    )
    spell_slots: dict = character_data.get("spell_slots") or {}  # type: ignore[assignment]

    if cantrips:
        embed.add_field(
            name="Cantrips",
            value=", ".join(_spell_name(c) for c in cantrips),
            inline=False,
        )

    if spells:
        embed.add_field(
            name="Spells Known / Prepared",
            value=", ".join(_spell_name(s) for s in spells),
            inline=False,
        )

    if spell_slots:
        lines: list[str] = []
        for lvl, slot_data in spell_slots.items():
            if isinstance(slot_data, dict):
                total: int = slot_data.get("total", 0)
                used: int = slot_data.get("used", 0)
                remaining = max(0, total - used)
                pips = "●" * remaining + "○" * used
                lines.append(f"Level {lvl}: {pips} ({remaining}/{total})")
            else:
                lines.append(f"Level {lvl}: {slot_data}")
        embed.add_field(name="Spell Slots", value="\n".join(lines), inline=False)

    if not cantrips and not spells and not spell_slots:
        embed.description = "No spells prepared."

    return embed
