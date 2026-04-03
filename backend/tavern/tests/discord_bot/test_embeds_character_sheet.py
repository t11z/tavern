"""Tests for embeds/character_sheet.py.

Covers:
  _hp_bar
  _modifier
  build_character_sheet_embed
  build_inventory_embed
  build_spells_embed
"""

from __future__ import annotations

from tavern.discord_bot.embeds.character_sheet import (
    _CLASS_COLOUR,
    _DEFAULT_COLOUR,
    _SPELLCASTER_CLASSES,
    _hp_bar,
    _modifier,
    build_character_sheet_embed,
    build_inventory_embed,
    build_spells_embed,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _full_char(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "name": "Kael Stormblade",
        "level": 3,
        "class_name": "Fighter",
        "species": "Human",
        "subclass": "Champion",
        "hp": 28,
        "max_hp": 38,
        "ac": 18,
        "speed": 30,
        "ability_scores": {
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 12,
            "cha": 8,
        },
        "conditions": [],
        "equipment": [
            {"name": "Longsword", "type": "martial melee", "damage": "1d8 slashing"},
            {"name": "Shield", "type": "armor"},
            {"name": "Chain Mail", "type": "heavy armor"},
            {"name": "Explorer's Pack", "type": "gear"},
            {"name": "Handaxe", "type": "simple melee"},
        ],
    }
    base.update(overrides)
    return base


def _spellcaster_char(**overrides) -> dict:  # type: ignore[type-arg]
    base = {
        "name": "Mira Moonwhisper",
        "level": 3,
        "class_name": "Wizard",
        "species": "High Elf",
        "hp": 18,
        "max_hp": 18,
        "ac": 12,
        "speed": 30,
        "ability_scores": {"int": 18, "dex": 14, "con": 12, "str": 8, "wis": 13, "cha": 10},
        "conditions": [],
        "equipment": [],
        "cantrips": [
            {"name": "Fire Bolt"},
            {"name": "Prestidigitation"},
            {"name": "Mage Hand"},
        ],
        "spells_known": [
            {"name": "Magic Missile"},
            {"name": "Shield"},
            {"name": "Detect Magic"},
        ],
        "spell_slots": {
            "1": {"total": 4, "used": 1},
            "2": {"total": 2, "used": 0},
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _hp_bar
# ---------------------------------------------------------------------------


def test_hp_bar_full_health() -> None:
    bar = _hp_bar(10, 10)
    assert bar == "██████████"


def test_hp_bar_empty_health() -> None:
    bar = _hp_bar(0, 10)
    assert bar == "░░░░░░░░░░"


def test_hp_bar_half_health() -> None:
    bar = _hp_bar(5, 10)
    assert bar.count("█") == 5
    assert bar.count("░") == 5


def test_hp_bar_length_always_ten() -> None:
    for current, max_hp in [(0, 10), (3, 10), (10, 10), (1, 100)]:
        assert len(_hp_bar(current, max_hp)) == 10


def test_hp_bar_zero_max_hp_returns_empty_bar() -> None:
    bar = _hp_bar(5, 0)
    assert bar == "░░░░░░░░░░"


def test_hp_bar_clamped_above_max() -> None:
    bar = _hp_bar(15, 10)
    assert bar == "██████████"


# ---------------------------------------------------------------------------
# _modifier
# ---------------------------------------------------------------------------


def test_modifier_positive() -> None:
    assert _modifier(16) == "+3"


def test_modifier_negative() -> None:
    assert _modifier(8) == "-1"


def test_modifier_zero() -> None:
    assert _modifier(10) == "+0"


def test_modifier_high() -> None:
    assert _modifier(20) == "+5"


# ---------------------------------------------------------------------------
# build_character_sheet_embed — title and description
# ---------------------------------------------------------------------------


def test_sheet_title_contains_name() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert "Kael Stormblade" in embed.title


def test_sheet_title_starts_with_shield() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert embed.title.startswith("🛡️")


def test_sheet_description_contains_level() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert "3" in embed.description


def test_sheet_description_contains_species() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert "Human" in embed.description


def test_sheet_description_contains_class() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert "Fighter" in embed.description


def test_sheet_description_contains_subclass_in_parens() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert "(Champion)" in embed.description


def test_sheet_description_no_subclass_when_absent() -> None:
    embed = build_character_sheet_embed(_full_char(subclass=""))
    assert "(" not in embed.description


# ---------------------------------------------------------------------------
# build_character_sheet_embed — colour
# ---------------------------------------------------------------------------


def test_sheet_fighter_colour() -> None:
    embed = build_character_sheet_embed(_full_char(class_name="Fighter"))
    assert embed.colour == _CLASS_COLOUR["fighter"]


def test_sheet_wizard_colour() -> None:
    embed = build_character_sheet_embed(_full_char(class_name="Wizard"))
    assert embed.colour == _CLASS_COLOUR["wizard"]


def test_sheet_bard_colour() -> None:
    embed = build_character_sheet_embed(_full_char(class_name="Bard"))
    assert embed.colour == _CLASS_COLOUR["bard"]


def test_sheet_unknown_class_falls_back_to_amber() -> None:
    embed = build_character_sheet_embed(_full_char(class_name="Artificer"))
    assert embed.colour == _DEFAULT_COLOUR


def test_sheet_class_name_case_insensitive() -> None:
    upper = build_character_sheet_embed(_full_char(class_name="WIZARD"))
    lower = build_character_sheet_embed(_full_char(class_name="wizard"))
    assert upper.colour == lower.colour


# ---------------------------------------------------------------------------
# build_character_sheet_embed — HP field
# ---------------------------------------------------------------------------


def test_sheet_hp_field_present() -> None:
    embed = build_character_sheet_embed(_full_char())
    field_names = [f.name for f in embed.fields]
    assert any("HP" in name for name in field_names)


def test_sheet_hp_field_contains_current_and_max() -> None:
    embed = build_character_sheet_embed(_full_char(hp=28, max_hp=38))
    hp_field = next(f for f in embed.fields if "HP" in f.name)
    assert "28" in hp_field.value
    assert "38" in hp_field.value


def test_sheet_hp_field_contains_bar_characters() -> None:
    embed = build_character_sheet_embed(_full_char())
    hp_field = next(f for f in embed.fields if "HP" in f.name)
    assert "█" in hp_field.value or "░" in hp_field.value


# ---------------------------------------------------------------------------
# build_character_sheet_embed — AC, Speed
# ---------------------------------------------------------------------------


def test_sheet_ac_field_present() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert any("AC" in f.name for f in embed.fields)


def test_sheet_ac_field_value() -> None:
    embed = build_character_sheet_embed(_full_char(ac=18))
    ac_field = next(f for f in embed.fields if "AC" in f.name)
    assert "18" in ac_field.value


def test_sheet_speed_field_present() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert any("Speed" in f.name for f in embed.fields)


def test_sheet_speed_field_value() -> None:
    embed = build_character_sheet_embed(_full_char(speed=30))
    speed_field = next(f for f in embed.fields if "Speed" in f.name)
    assert "30" in speed_field.value


# ---------------------------------------------------------------------------
# build_character_sheet_embed — ability scores
# ---------------------------------------------------------------------------


def test_sheet_ability_scores_field_present_when_provided() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert any("Ability" in f.name for f in embed.fields)


def test_sheet_ability_scores_field_contains_str() -> None:
    embed = build_character_sheet_embed(_full_char())
    scores_field = next(f for f in embed.fields if "Ability" in f.name)
    assert "STR" in scores_field.value
    assert "16" in scores_field.value


def test_sheet_ability_scores_field_contains_modifiers() -> None:
    embed = build_character_sheet_embed(_full_char())
    scores_field = next(f for f in embed.fields if "Ability" in f.name)
    assert "+3" in scores_field.value  # STR 16


def test_sheet_no_ability_scores_field_when_absent() -> None:
    embed = build_character_sheet_embed(_full_char(ability_scores={}))
    assert not any("Ability" in f.name for f in embed.fields)


# ---------------------------------------------------------------------------
# build_character_sheet_embed — conditions
# ---------------------------------------------------------------------------


def test_sheet_conditions_none_when_empty() -> None:
    embed = build_character_sheet_embed(_full_char(conditions=[]))
    cond_field = next(f for f in embed.fields if "Condition" in f.name)
    assert cond_field.value == "None"


def test_sheet_conditions_listed_when_present() -> None:
    embed = build_character_sheet_embed(_full_char(conditions=["Poisoned", "Blinded"]))
    cond_field = next(f for f in embed.fields if "Condition" in f.name)
    assert "Poisoned" in cond_field.value
    assert "Blinded" in cond_field.value


# ---------------------------------------------------------------------------
# build_character_sheet_embed — equipment summary
# ---------------------------------------------------------------------------


def test_sheet_equipment_field_present_when_items_exist() -> None:
    embed = build_character_sheet_embed(_full_char())
    assert any("Equipment" in f.name for f in embed.fields)


def test_sheet_equipment_shows_first_five_items() -> None:
    embed = build_character_sheet_embed(_full_char())
    eq_field = next(f for f in embed.fields if "Equipment" in f.name)
    assert "Longsword" in eq_field.value
    assert "Chain Mail" in eq_field.value


def test_sheet_equipment_truncates_beyond_five() -> None:
    char = _full_char(equipment=[{"name": f"Item {i}"} for i in range(8)])
    embed = build_character_sheet_embed(char)
    eq_field = next(f for f in embed.fields if "Equipment" in f.name)
    assert "3 more" in eq_field.value


def test_sheet_equipment_no_field_when_empty() -> None:
    embed = build_character_sheet_embed(_full_char(equipment=[]))
    assert not any("Equipment" in f.name for f in embed.fields)


# ---------------------------------------------------------------------------
# build_character_sheet_embed — tolerates missing fields
# ---------------------------------------------------------------------------


def test_sheet_minimal_data_does_not_raise() -> None:
    embed = build_character_sheet_embed({})
    assert embed.title is not None


# ---------------------------------------------------------------------------
# build_inventory_embed
# ---------------------------------------------------------------------------


def test_inventory_title_format() -> None:
    embed = build_inventory_embed(_full_char())
    assert "Kael Stormblade" in embed.title
    assert embed.title.startswith("🎒")


def test_inventory_empty_shows_description() -> None:
    embed = build_inventory_embed(_full_char(equipment=[]))
    assert embed.description is not None
    assert "No items" in embed.description


def test_inventory_items_as_field_names() -> None:
    embed = build_inventory_embed(_full_char())
    field_names = [f.name for f in embed.fields]
    assert "Longsword" in field_names
    assert "Shield" in field_names


def test_inventory_item_details_in_field_value() -> None:
    embed = build_inventory_embed(_full_char())
    sword_field = next(f for f in embed.fields if f.name == "Longsword")
    assert "1d8 slashing" in sword_field.value


def test_inventory_item_weight_in_details() -> None:
    char = _full_char(equipment=[{"name": "Backpack", "type": "gear", "weight": 5}])
    embed = build_inventory_embed(char)
    assert "5 lb" in embed.fields[0].value


def test_inventory_item_properties_in_details() -> None:
    char = _full_char(equipment=[{"name": "Longsword", "properties": ["versatile", "finesse"]}])
    embed = build_inventory_embed(char)
    assert "versatile" in embed.fields[0].value


def test_inventory_string_items_render() -> None:
    char = _full_char(equipment=["Rope (50 ft)", "Torch"])
    embed = build_inventory_embed(char)
    field_names = [f.name for f in embed.fields]
    assert "Rope (50 ft)" in field_names


def test_inventory_colour_matches_class() -> None:
    embed_fighter = build_inventory_embed(_full_char(class_name="Fighter"))
    embed_wizard = build_inventory_embed(_full_char(class_name="Wizard"))
    assert embed_fighter.colour == _CLASS_COLOUR["fighter"]
    assert embed_wizard.colour == _CLASS_COLOUR["wizard"]


# ---------------------------------------------------------------------------
# build_spells_embed — non-spellcasters
# ---------------------------------------------------------------------------


def test_spells_fighter_no_spells_message() -> None:
    embed = build_spells_embed(_full_char(class_name="Fighter"))
    assert "doesn't use spells" in embed.description


def test_spells_barbarian_no_spells_message() -> None:
    embed = build_spells_embed(_full_char(class_name="Barbarian"))
    assert "doesn't use spells" in embed.description


def test_spells_non_spellcaster_has_no_fields() -> None:
    embed = build_spells_embed(_full_char(class_name="Rogue"))
    assert len(embed.fields) == 0


# ---------------------------------------------------------------------------
# build_spells_embed — spellcasters
# ---------------------------------------------------------------------------


def test_spells_title_format() -> None:
    embed = build_spells_embed(_spellcaster_char())
    assert "Mira Moonwhisper" in embed.title
    assert embed.title.startswith("✨")


def test_spells_wizard_colour() -> None:
    embed = build_spells_embed(_spellcaster_char())
    assert embed.colour == _CLASS_COLOUR["wizard"]


def test_spells_cantrips_field_present() -> None:
    embed = build_spells_embed(_spellcaster_char())
    assert any("Cantrip" in f.name for f in embed.fields)


def test_spells_cantrips_listed() -> None:
    embed = build_spells_embed(_spellcaster_char())
    cantrip_field = next(f for f in embed.fields if "Cantrip" in f.name)
    assert "Fire Bolt" in cantrip_field.value
    assert "Mage Hand" in cantrip_field.value


def test_spells_known_field_present() -> None:
    embed = build_spells_embed(_spellcaster_char())
    assert any("Spell" in f.name and "Cantrip" not in f.name for f in embed.fields)


def test_spells_known_listed() -> None:
    embed = build_spells_embed(_spellcaster_char())
    spells_field = next(
        f
        for f in embed.fields
        if "Spell" in f.name and "Cantrip" not in f.name and "Slot" not in f.name
    )
    assert "Magic Missile" in spells_field.value
    assert "Shield" in spells_field.value


def test_spells_slots_field_present() -> None:
    embed = build_spells_embed(_spellcaster_char())
    assert any("Slot" in f.name for f in embed.fields)


def test_spells_slots_show_remaining_and_total() -> None:
    embed = build_spells_embed(_spellcaster_char())
    slots_field = next(f for f in embed.fields if "Slot" in f.name)
    assert "3/4" in slots_field.value  # 4 - 1 used = 3 remaining


def test_spells_slots_pips_notation() -> None:
    embed = build_spells_embed(_spellcaster_char())
    slots_field = next(f for f in embed.fields if "Slot" in f.name)
    assert "●" in slots_field.value
    assert "○" in slots_field.value


def test_spells_no_spells_description_when_all_absent() -> None:
    embed = build_spells_embed(_spellcaster_char(cantrips=[], spells_known=[], spell_slots={}))
    assert embed.description is not None
    assert "No spells" in embed.description


def test_spells_string_cantrips_render() -> None:
    embed = build_spells_embed(_spellcaster_char(cantrips=["Fire Bolt", "Light"]))
    cantrip_field = next(f for f in embed.fields if "Cantrip" in f.name)
    assert "Fire Bolt" in cantrip_field.value


def test_spellcaster_classes_set_contains_expected() -> None:
    assert "wizard" in _SPELLCASTER_CLASSES
    assert "bard" in _SPELLCASTER_CLASSES
    assert "fighter" not in _SPELLCASTER_CLASSES
    assert "barbarian" not in _SPELLCASTER_CLASSES
