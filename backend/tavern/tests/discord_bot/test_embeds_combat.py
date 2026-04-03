"""Tests for embeds/combat.py — build_combat_embed and build_party_status."""

from __future__ import annotations

from tavern.discord_bot.embeds.combat import (
    _GREEN,
    _RED,
    TAVERN_AMBER,
    build_combat_embed,
    build_party_status,
)

# ---------------------------------------------------------------------------
# build_combat_embed — title and empty results
# ---------------------------------------------------------------------------


def test_embed_title() -> None:
    embed = build_combat_embed([])
    assert embed.title == "⚔️ Combat Results"


def test_empty_results_has_description() -> None:
    embed = build_combat_embed([])
    assert embed.description is not None
    assert "No mechanical results" in embed.description


def test_empty_results_no_fields() -> None:
    embed = build_combat_embed([])
    assert len(embed.fields) == 0


# ---------------------------------------------------------------------------
# build_combat_embed — damage
# ---------------------------------------------------------------------------


def test_damage_result_field_name() -> None:
    embed = build_combat_embed(
        [{"type": "damage", "target": "Goblin A", "amount": 9, "damage_type": "slashing"}]
    )
    assert embed.fields[0].name == "⚔️ Damage"


def test_damage_result_with_source() -> None:
    result = {
        "type": "damage",
        "target": "Goblin A",
        "amount": 9,
        "damage_type": "slashing",
        "source": "Kael",
    }
    embed = build_combat_embed([result])
    value = embed.fields[0].value
    assert "Kael" in value
    assert "Goblin A" in value
    assert "9" in value
    assert "slashing" in value


def test_damage_result_without_source() -> None:
    result = {"type": "damage", "target": "Goblin A", "amount": 4, "damage_type": "fire"}
    embed = build_combat_embed([result])
    value = embed.fields[0].value
    assert "Goblin A" in value
    assert "4" in value


def test_damage_result_colour_is_green() -> None:
    embed = build_combat_embed([{"type": "damage", "target": "X", "amount": 1}])
    assert embed.colour == _GREEN


# ---------------------------------------------------------------------------
# build_combat_embed — miss
# ---------------------------------------------------------------------------


def test_miss_result_field_name() -> None:
    embed = build_combat_embed([{"type": "miss", "attacker": "Kael", "target": "Goblin A"}])
    assert embed.fields[0].name == "❌ Miss"


def test_miss_result_field_value() -> None:
    result = {"type": "miss", "attacker": "Kael", "target": "Goblin A"}
    embed = build_combat_embed([result])
    assert "Kael" in embed.fields[0].value
    assert "Goblin A" in embed.fields[0].value


# ---------------------------------------------------------------------------
# build_combat_embed — heal
# ---------------------------------------------------------------------------


def test_heal_result_field_name() -> None:
    embed = build_combat_embed([{"type": "heal", "target": "Mira", "amount": 8}])
    assert embed.fields[0].name == "💚 Healed"


def test_heal_result_field_value() -> None:
    embed = build_combat_embed([{"type": "heal", "target": "Mira", "amount": 8}])
    assert "Mira" in embed.fields[0].value
    assert "8" in embed.fields[0].value


# ---------------------------------------------------------------------------
# build_combat_embed — condition_added / condition_removed
# ---------------------------------------------------------------------------


def test_condition_added_field_name() -> None:
    embed = build_combat_embed(
        [{"type": "condition_added", "target": "Kael", "condition": "poisoned"}]
    )
    assert embed.fields[0].name == "⚡ Condition"
    assert "poisoned" in embed.fields[0].value


def test_condition_removed_non_alive() -> None:
    embed = build_combat_embed(
        [{"type": "condition_removed", "target": "Kael", "condition": "poisoned"}]
    )
    assert embed.fields[0].name == "✅ Condition Removed"
    assert "poisoned" in embed.fields[0].value


def test_condition_removed_alive_shows_defeated() -> None:
    embed = build_combat_embed(
        [{"type": "condition_removed", "target": "Goblin A", "condition": "alive"}]
    )
    assert embed.fields[0].name == "💀 Defeated"
    assert "Goblin A" in embed.fields[0].value
    assert "defeated" in embed.fields[0].value.lower()


# ---------------------------------------------------------------------------
# build_combat_embed — unknown type
# ---------------------------------------------------------------------------


def test_unknown_result_type_rendered_generically() -> None:
    embed = build_combat_embed([{"type": "custom_event", "extra": "data"}])
    assert "custom_event" in embed.fields[0].name


# ---------------------------------------------------------------------------
# build_combat_embed — multiple results / fields
# ---------------------------------------------------------------------------


def test_multiple_results_produce_multiple_fields() -> None:
    results = [
        {"type": "damage", "target": "Goblin A", "amount": 9},
        {"type": "condition_removed", "target": "Goblin A", "condition": "alive"},
    ]
    embed = build_combat_embed(results)
    assert len(embed.fields) == 2


def test_fields_are_not_inline() -> None:
    embed = build_combat_embed([{"type": "damage", "target": "X", "amount": 1}])
    assert embed.fields[0].inline is False


# ---------------------------------------------------------------------------
# build_combat_embed — colour selection
# ---------------------------------------------------------------------------


def test_damage_taken_type_gives_red() -> None:
    embed = build_combat_embed([{"type": "damage_taken", "target": "Kael", "amount": 5}])
    assert embed.colour == _RED


def test_miss_colour_is_amber() -> None:
    embed = build_combat_embed([{"type": "miss", "attacker": "X", "target": "Y"}])
    assert embed.colour == TAVERN_AMBER


def test_colour_red_takes_priority_over_green() -> None:
    results = [
        {"type": "damage", "target": "Goblin"},
        {"type": "damage_taken", "target": "Kael", "amount": 3},
    ]
    embed = build_combat_embed(results)
    assert embed.colour == _RED


# ---------------------------------------------------------------------------
# build_party_status
# ---------------------------------------------------------------------------


def test_party_status_single_character() -> None:
    chars = [{"name": "Kael", "hp": 32, "max_hp": 38}]
    result = build_party_status(chars)
    assert result == "📊 Kael 32/38"


def test_party_status_multiple_characters() -> None:
    chars = [
        {"name": "Kael", "hp": 32, "max_hp": 38},
        {"name": "Mira", "hp": 24, "max_hp": 28},
    ]
    result = build_party_status(chars)
    assert result == "📊 Kael 32/38 · Mira 24/28"


def test_party_status_empty_list() -> None:
    assert build_party_status([]) == ""


def test_party_status_missing_name_uses_placeholder() -> None:
    chars = [{"hp": 10, "max_hp": 20}]
    result = build_party_status(chars)
    assert "10/20" in result


def test_party_status_three_characters() -> None:
    chars = [
        {"name": "A", "hp": 1, "max_hp": 10},
        {"name": "B", "hp": 2, "max_hp": 10},
        {"name": "C", "hp": 3, "max_hp": 10},
    ]
    result = build_party_status(chars)
    assert result.startswith("📊")
    assert "A 1/10" in result
    assert "B 2/10" in result
    assert "C 3/10" in result
    # Parts separated by ·
    assert " · " in result
