"""SRD Data Access Layer — the only place in core/ that knows about MongoDB.

All other modules in ``core/`` call functions from this module; they never
query MongoDB directly and are unaware of the three-tier layering.

Lookup order (first match wins):
  1. Campaign Override — scoped to a single campaign
  2. Instance Library  — custom content shared across all campaigns on this instance
  3. SRD Baseline      — 5e-bits/5e-database v4.6.3 (MongoDB container)

Caching:
  SRD Baseline lookups are cached indefinitely after the first fetch — the
  5e-database container never changes at runtime.  Instance Library and Campaign
  Override lookups are never cached because they can change during a session.

Schema notes (5e-bits/5e-database v4.6.3):
  Verify field names with:
    docker compose exec 5e-database mongosh 5e-database \\
      --eval "db.classes.findOne({index:'barbarian'})"
    docker compose exec 5e-database mongosh 5e-database \\
      --eval "db.levels.findOne({index:'barbarian-1'})"
  The ``index`` field is the primary lookup key (lowercase slug, e.g.
  "barbarian", "fireball", "goblin").
"""

from typing import Any, Final

from tavern.srd_db import get_srd_db

# ---------------------------------------------------------------------------
# Caster classification constants
#
# These drive code logic (which spell-slot table to apply), not raw SRD data.
# They are classification metadata — stable across all legal 5e rule sets.
# ---------------------------------------------------------------------------

FULL_CASTERS: Final[frozenset[str]] = frozenset({"Bard", "Cleric", "Druid", "Sorcerer", "Wizard"})
HALF_CASTERS: Final[frozenset[str]] = frozenset({"Paladin", "Ranger"})
NON_CASTERS: Final[frozenset[str]] = frozenset({"Barbarian", "Fighter", "Monk", "Rogue"})
ALL_CLASSES: Final[frozenset[str]] = (
    FULL_CASTERS | HALF_CASTERS | NON_CASTERS | frozenset({"Warlock"})
)

# ---------------------------------------------------------------------------
# SRD Baseline cache
# ---------------------------------------------------------------------------

_baseline_cache: dict[tuple[str, str], dict[str, Any]] = {}
_levels_cache: dict[tuple[str, int], dict[str, Any]] = {}


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *doc* with the MongoDB ``_id`` field removed."""
    return {k: v for k, v in doc.items() if k != "_id"}


async def _layered_lookup(
    collection_name: str,
    index: str,
    campaign_id: str | None = None,
) -> dict[str, Any] | None:
    """Perform a three-tier layered lookup for *index* in *collection_name*.

    Returns the first matching document (stripped of ``_id``), or ``None``
    if no document is found at any tier.
    """
    db = get_srd_db()

    # 1. Campaign Override
    if campaign_id:
        result = await db.campaign_overrides.find_one(
            {
                "campaign_id": campaign_id,
                "collection": collection_name,
                "index": index,
            }
        )
        if result is not None:
            override: dict[str, Any] = result["data"]
            return override

    # 2. Instance Library
    custom_result = await db[f"custom_{collection_name}"].find_one({"index": index})
    if custom_result is not None:
        return _strip_id(dict(custom_result))

    # 3. SRD Baseline (cached)
    cache_key = (collection_name, index)
    if cache_key in _baseline_cache:
        return _baseline_cache[cache_key]

    baseline = await db[collection_name].find_one({"index": index})
    if baseline is not None:
        doc = _strip_id(dict(baseline))
        _baseline_cache[cache_key] = doc
        return doc

    return None


async def _get_level_doc(class_index: str, level: int) -> dict[str, Any] | None:
    """Return the ``levels`` collection document for *class_index* at *level*.

    Field: ``index`` is e.g. ``"barbarian-1"``.  Results are cached.
    """
    cache_key = (class_index, level)
    if cache_key in _levels_cache:
        return _levels_cache[cache_key]

    db = get_srd_db()
    index = f"{class_index}-{level}"
    result = await db.levels.find_one({"index": index})
    if result is None:
        # Some collections use class.index + level as a compound filter
        result = await db.levels.find_one({"class.index": class_index, "level": level})
    if result is not None:
        doc = _strip_id(dict(result))
        _levels_cache[cache_key] = doc
        return doc
    return None


# ---------------------------------------------------------------------------
# Base entity functions — return raw 5e-database documents
# ---------------------------------------------------------------------------


async def get_monster(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the monster document for *index*, or ``None`` if not found.

    Applies layered lookup: campaign override → instance library → SRD baseline.
    *index* should be the lowercase slug (e.g. ``"goblin"``).
    """
    return await _layered_lookup("monsters", index.lower(), campaign_id)


async def get_spell(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the spell document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"fireball"``).
    """
    return await _layered_lookup("spells", index.lower(), campaign_id)


async def get_class(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the class document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"barbarian"``).
    """
    return await _layered_lookup("classes", index.lower(), campaign_id)


async def get_species(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the species/race document for *index*, or ``None`` if not found.

    Checks the ``races`` collection (the 5e-database collection name).
    *index* should be the lowercase slug (e.g. ``"elf"``).
    """
    return await _layered_lookup("races", index.lower(), campaign_id)


async def get_background(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the background document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"acolyte"``).
    """
    return await _layered_lookup("backgrounds", index.lower(), campaign_id)


async def get_equipment(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the equipment document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"longsword"``).
    """
    return await _layered_lookup("equipment", index.lower(), campaign_id)


async def get_feat(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the feat document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"alert"``).
    """
    return await _layered_lookup("feats", index.lower(), campaign_id)


async def get_condition(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the condition document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"blinded"``).
    """
    return await _layered_lookup("conditions", index.lower(), campaign_id)


async def get_magic_item(index: str, campaign_id: str | None = None) -> dict[str, Any] | None:
    """Return the magic item document for *index*, or ``None`` if not found.

    *index* should be the lowercase slug (e.g. ``"bag-of-holding"``).
    """
    return await _layered_lookup("magic-items", index.lower(), campaign_id)


# ---------------------------------------------------------------------------
# List / search functions
# ---------------------------------------------------------------------------


async def list_monsters(campaign_id: str | None = None, **filters: Any) -> list[dict[str, Any]]:
    """Return monsters matching *filters*, merged with custom content.

    Custom monsters from the Instance Library and Campaign Overrides are
    prepended to the SRD baseline results.
    """
    return await _list_merged("monsters", campaign_id, **filters)


async def list_spells(campaign_id: str | None = None, **filters: Any) -> list[dict[str, Any]]:
    """Return spells matching *filters*, merged with custom content."""
    return await _list_merged("spells", campaign_id, **filters)


async def list_classes(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all class documents."""
    return await _list_merged("classes", campaign_id)


async def list_species(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all species/race documents."""
    return await _list_merged("races", campaign_id)


async def list_backgrounds(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all background documents."""
    return await _list_merged("backgrounds", campaign_id)


async def list_feats(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all feat documents."""
    return await _list_merged("feats", campaign_id)


async def list_conditions(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all condition documents."""
    return await _list_merged("conditions", campaign_id)


async def list_equipment(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all equipment documents."""
    return await _list_merged("equipment", campaign_id)


async def list_magic_items(campaign_id: str | None = None) -> list[dict[str, Any]]:
    """Return all magic item documents."""
    return await _list_merged("magic-items", campaign_id)


async def _list_merged(
    collection_name: str,
    campaign_id: str | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Return merged documents from all three tiers for *collection_name*."""
    db = get_srd_db()
    query = dict(filters)
    results: list[dict[str, Any]] = []
    seen_indices: set[str] = set()

    # Campaign Override entries first
    if campaign_id:
        override_query = {"campaign_id": campaign_id, "collection": collection_name}
        async for doc in db.campaign_overrides.find(override_query):
            data: dict[str, Any] = doc["data"]
            idx = data.get("index", "")
            if idx not in seen_indices:
                results.append(data)
                seen_indices.add(idx)

    # Instance Library
    async for doc in db[f"custom_{collection_name}"].find(query):
        clean = _strip_id(dict(doc))
        idx = clean.get("index", "")
        if idx not in seen_indices:
            results.append(clean)
            seen_indices.add(idx)

    # SRD Baseline
    async for doc in db[collection_name].find(query):
        clean = _strip_id(dict(doc))
        idx = clean.get("index", "")
        if idx not in seen_indices:
            results.append(clean)
            seen_indices.add(idx)

    return results


# ---------------------------------------------------------------------------
# Rules tables (proficiency bonus, XP thresholds, etc.)
# ---------------------------------------------------------------------------


async def get_rules_table(table_name: str) -> dict[str, Any]:
    """Return a named reference table as a dict.

    Supported table names:
    - ``"proficiency_bonus"`` — dict[int, int]: level → bonus (levels 1-20)
    - ``"xp_thresholds"``    — list[int]: minimum XP for each level (index 0 = level 1)
    - ``"spell_slots_full"`` — list[dict[int,int]]: full-caster slot table
    - ``"spell_slots_half"`` — list[dict[int,int]]: half-caster slot table
    - ``"warlock_pact_magic"`` — list[tuple[int,int]]: (num_slots, slot_level)

    Raises:
        ValueError: If *table_name* is not recognised.
    """
    if table_name == "proficiency_bonus":
        return {"table": await _build_proficiency_bonus_table()}
    if table_name == "xp_thresholds":
        return {"table": await _build_xp_thresholds()}
    if table_name == "spell_slots_full":
        return {"table": await _build_full_caster_slots()}
    if table_name == "spell_slots_half":
        return {"table": await _build_half_caster_slots()}
    if table_name == "warlock_pact_magic":
        return {"table": await _build_warlock_pact_magic()}
    raise ValueError(f"Unknown rules table: {table_name!r}")


# ---------------------------------------------------------------------------
# Character-mechanics helpers — typed extractions used by core/characters.py
# ---------------------------------------------------------------------------


async def get_class_hit_die(class_name: str) -> int:
    """Return the hit die size for *class_name* (e.g. 12 for Barbarian).

    Raises:
        ValueError: If *class_name* is not a recognised SRD class.
    """
    doc = await get_class(class_name.lower())
    if doc is None:
        raise ValueError(f"Unknown class: {class_name!r}")
    return int(doc["hit_die"])


async def get_class_fixed_hp_per_level(class_name: str) -> int:
    """Return fixed HP gained per level for *class_name* (hit_die ÷ 2 + 1).

    Per SRD 5.2.1 p.23 "Fixed Hit Points by Class".

    Raises:
        ValueError: If *class_name* is not a recognised SRD class.
    """
    hit_die = await get_class_hit_die(class_name)
    return hit_die // 2 + 1


async def get_proficiency_bonus(level: int) -> int:
    """Return the proficiency bonus for character level *level* (1–20).

    Fetches from the ``levels`` collection using the ``barbarian`` class as a
    reference (proficiency bonus is identical for all classes at the same level).

    Raises:
        ValueError: If *level* is outside 1–20.
    """
    if not 1 <= level <= 20:
        raise ValueError(f"Level must be 1–20, got {level}")
    doc = await _get_level_doc("barbarian", level)
    if doc is None:
        raise ValueError(f"Level data not found for level {level}")
    prof_bonus: int = int(doc["prof_bonus"])
    return prof_bonus


async def get_xp_thresholds() -> list[int]:
    """Return the XP threshold list (index 0 = level 1, index 19 = level 20).

    Each value is the minimum XP required to reach that level.
    """
    thresholds: list[int] = []
    for level in range(1, 21):
        doc = await _get_level_doc("barbarian", level)
        if doc is None:
            raise ValueError(f"Level data not found for level {level}")
        # 5e-database field: experience_points
        xp_value = doc.get("experience_points", doc.get("experience_points_raw", 0))
        thresholds.append(int(xp_value))
    return thresholds


async def get_class_spell_slots(class_name: str, class_level: int) -> dict[int, int]:
    """Return spell slots for *class_name* at *class_level*.

    Returns a dict mapping spell level → number of slots.
    Returns an empty dict for non-casting classes.
    Warlock Pact Magic is handled separately via ``get_warlock_pact_magic()``.

    Raises:
        ValueError: If *class_name* is not recognised or *class_level* is invalid.
    """
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")

    if class_name == "Warlock":
        num_slots, slot_level = await get_warlock_pact_magic(class_level)
        return {slot_level: num_slots}

    if class_name in NON_CASTERS:
        return {}

    doc = await _get_level_doc(class_name.lower(), class_level)
    if doc is None:
        return {}

    spellcasting = doc.get("spellcasting")
    if not spellcasting:
        return {}

    return _extract_spell_slots(spellcasting)


def _extract_spell_slots(spellcasting: dict[str, Any]) -> dict[int, int]:
    """Extract spell slot dict from a 5e-database spellcasting sub-document.

    The 5e-database stores slots as individual fields:
    ``spell_slots_level_1`` through ``spell_slots_level_9``.
    """
    slots: dict[int, int] = {}
    for i in range(1, 10):
        count = spellcasting.get(f"spell_slots_level_{i}", 0)
        if count and int(count) > 0:
            slots[i] = int(count)
    return slots


async def get_warlock_pact_magic(class_level: int) -> tuple[int, int]:
    """Return ``(num_slots, slot_level)`` for Warlock Pact Magic at *class_level*.

    Raises:
        ValueError: If *class_level* is outside 1–20.
    """
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")
    doc = await _get_level_doc("warlock", class_level)
    if doc is None:
        raise ValueError(f"Warlock level data not found for level {class_level}")
    spellcasting = doc.get("spellcasting", {}) or {}
    num_slots = int(spellcasting.get("spell_slots_level_1", 0))
    # Determine the slot level from the spellcasting data
    for slot_level in range(5, 0, -1):
        count = int(spellcasting.get(f"spell_slots_level_{slot_level}", 0))
        if count > 0:
            return (count, slot_level)
    return (num_slots, 1)


async def get_class_cantrips_known(class_name: str, class_level: int) -> int:
    """Return the number of cantrips known for *class_name* at *class_level*.

    Returns 0 for classes with no cantrips.

    Raises:
        ValueError: If *class_name* is not recognised or *class_level* is invalid.
    """
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")

    doc = await _get_level_doc(class_name.lower(), class_level)
    if doc is None:
        return 0
    spellcasting = doc.get("spellcasting")
    if not spellcasting:
        return 0
    return int(spellcasting.get("cantrips_known", 0))


async def get_class_spells_prepared(class_name: str, class_level: int) -> int:
    """Return the number of spells prepared for *class_name* at *class_level*.

    Returns 0 for non-spellcasting classes.

    Raises:
        ValueError: If *class_name* is not recognised or *class_level* is invalid.
    """
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")

    doc = await _get_level_doc(class_name.lower(), class_level)
    if doc is None:
        return 0
    spellcasting = doc.get("spellcasting")
    if not spellcasting:
        return 0
    # 5e-database field: spells_known or spells_prepared (varies by class)
    count = spellcasting.get("spells_known", spellcasting.get("spells_prepared", 0))
    return int(count) if count else 0


async def get_class_features_at_level(class_name: str, class_level: int) -> list[str]:
    """Return feature names gained by *class_name* at *class_level*.

    Returns an empty list if no features are gained at that level.

    Raises:
        ValueError: If *class_name* is not recognised or *class_level* is invalid.
    """
    if class_name not in ALL_CLASSES:
        raise ValueError(f"Unknown class: {class_name!r}")
    if not 1 <= class_level <= 20:
        raise ValueError(f"Class level must be 1–20, got {class_level}")

    doc = await _get_level_doc(class_name.lower(), class_level)
    if doc is None:
        return []
    features = doc.get("features", [])
    return [f["name"] for f in features if isinstance(f, dict) and "name" in f]


async def get_class_proficiencies_data(class_name: str) -> dict[str, Any]:
    """Return proficiency data for *class_name*.

    The returned dict has the same shape as the old ``CLASS_PROFICIENCIES``
    constant: ``saving_throws``, ``skills_choose``, ``skills_from``,
    ``armor``, ``weapons``, ``tools``.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    doc = await get_class(class_name.lower())
    if doc is None:
        raise ValueError(f"Unknown class: {class_name!r}")

    # Saving throws: list of ability abbreviations e.g. ["STR", "CON"]
    saving_throws = [
        st.get("name", st.get("index", "")).upper()
        for st in doc.get("saving_throws", [])
        if isinstance(st, dict)
    ]

    # Proficiency choices (skills)
    skills_choose = 0
    skills_from: list[str] = []
    for choice in doc.get("proficiency_choices", []):
        if not isinstance(choice, dict):
            continue
        from_list = choice.get("from", {})
        options = from_list.get("options", []) if isinstance(from_list, dict) else []
        if options and isinstance(options[0], dict):
            # Check if these are skill proficiencies
            first_item = options[0].get("item", options[0])
            if isinstance(first_item, dict):
                item_index = first_item.get("index", "")
                if item_index.startswith("skill-"):
                    skills_choose = int(choice.get("choose", 0))
                    skills_from = (
                        [o.get("item", o).get("name", "") for o in options if isinstance(o, dict)]
                        if options
                        else ["any"]
                    )

    # Proficiencies: armor, weapons, tools
    armor: list[str] = []
    weapons: list[str] = []
    tools: list[str] = []
    for prof in doc.get("proficiencies", []):
        if not isinstance(prof, dict):
            continue
        name = prof.get("name", "")
        index = prof.get("index", "")
        if "armor" in index or "armour" in index:
            armor.append(name)
        elif "weapons" in index or "weapon" in index:
            weapons.append(name)
        elif any(t in index for t in ["tools", "supplies", "kit", "instruments", "gaming"]):
            tools.append(name)

    return {
        "saving_throws": saving_throws,
        "skills_choose": skills_choose,
        "skills_from": skills_from if skills_from else ["any"],
        "armor": armor,
        "weapons": weapons,
        "tools": tools,
    }


async def get_class_multiclass_proficiency_gains(class_name: str) -> dict[str, Any]:
    """Return proficiency gains when multiclassing *into* *class_name*.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    doc = await get_class(class_name.lower())
    if doc is None:
        raise ValueError(f"Unknown class: {class_name!r}")

    multi_classing = doc.get("multi_classing", {}) or {}
    proficiencies_gained = multi_classing.get("proficiencies", [])

    armor: list[str] = []
    weapons: list[str] = []
    tools: list[str] = []
    skills_choose = 0
    skills_from: list[str] = []

    for prof in proficiencies_gained:
        if not isinstance(prof, dict):
            continue
        name = prof.get("name", "")
        index = prof.get("index", "")
        if "armor" in index or "armour" in index:
            armor.append(name)
        elif "weapon" in index:
            weapons.append(name)
        elif any(t in index for t in ["tools", "supplies", "kit", "instruments", "gaming"]):
            tools.append(name)

    for choice in multi_classing.get("proficiency_choices", []):
        if not isinstance(choice, dict):
            continue
        skills_choose = int(choice.get("choose", 0))
        from_list = choice.get("from", {})
        options = from_list.get("options", []) if isinstance(from_list, dict) else []
        skills_from = [o.get("item", o).get("name", "") for o in options if isinstance(o, dict)]

    return {
        "armor": armor,
        "weapons": weapons,
        "tools": tools,
        "skills_choose": skills_choose,
        "skills_from": skills_from,
    }


async def get_class_starting_equipment_data(class_name: str) -> dict[str, list[str]]:
    """Return starting equipment options for *class_name*.

    Keys are ``"option_a"``, ``"option_b"``, and (for Fighter) ``"option_c"``.
    Each value is a list of item name strings.

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    doc = await get_class(class_name.lower())
    if doc is None:
        raise ValueError(f"Unknown class: {class_name!r}")

    options: dict[str, list[str]] = {}
    option_labels = ["option_a", "option_b", "option_c", "option_d"]

    for i, choice in enumerate(doc.get("starting_equipment_options", [])):
        if i >= len(option_labels):
            break
        if not isinstance(choice, dict):
            continue
        from_list = choice.get("from", {})
        choice_options = from_list.get("options", []) if isinstance(from_list, dict) else []
        items: list[str] = []
        for opt in choice_options:
            if not isinstance(opt, dict):
                continue
            # Each option may be a list of equipment items or a gold piece value
            of_list = opt.get("of", opt.get("items", []))
            if isinstance(of_list, list):
                for item in of_list:
                    if isinstance(item, dict):
                        qty = item.get("quantity", 1)
                        name = item.get("equipment", {}).get("name", "")
                        if name:
                            items.append(f"{name}" if qty == 1 else f"{name} x{qty}")
            elif isinstance(opt.get("equipment"), dict):
                name = opt["equipment"].get("name", "")
                qty = opt.get("quantity", 1)
                if name:
                    items.append(f"{name}" if qty == 1 else f"{name} x{qty}")
        if items:
            options[option_labels[i]] = items

    # Fallback: if no parsed options, provide a gold piece alternative
    if not options:
        options["option_a"] = []
        options["option_b"] = []

    return options


async def get_class_primary_abilities(class_name: str) -> list[str]:
    """Return ability prerequisites for multiclassing into *class_name*.

    Returns a list of ability abbreviations (e.g. ``["STR"]`` for Barbarian,
    ``["DEX", "WIS"]`` for Monk).

    Raises:
        ValueError: If *class_name* is not recognised.
    """
    doc = await get_class(class_name.lower())
    if doc is None:
        raise ValueError(f"Unknown class: {class_name!r}")

    multi_classing = doc.get("multi_classing", {}) or {}
    prerequisites = multi_classing.get("prerequisites", [])
    abilities: list[str] = []
    for prereq in prerequisites:
        if isinstance(prereq, dict):
            ability = prereq.get("ability_score", {})
            if isinstance(ability, dict):
                abilities.append(ability.get("index", "").upper())
    return abilities if abilities else []


async def get_species_data(species_name: str) -> dict[str, Any]:
    """Return the species document for *species_name*.

    Returns the raw 5e-database races document.

    Raises:
        ValueError: If *species_name* is not recognised.
    """
    doc = await get_species(species_name.lower())
    if doc is None:
        raise ValueError(f"Unknown species: {species_name!r}.")
    return doc


async def get_background_doc(background_name: str) -> dict[str, Any]:
    """Return the background document for *background_name*.

    Returns the raw 5e-database backgrounds document.

    Raises:
        ValueError: If *background_name* is not recognised.
    """
    doc = await get_background(background_name.lower())
    if doc is None:
        raise ValueError(f"Unknown background: {background_name!r}.")
    return doc


async def get_feat_doc(feat_name: str) -> dict[str, Any]:
    """Return the feat document for *feat_name*.

    Tries the lowercase slug, then a hyphenated slug for names with spaces.

    Raises:
        ValueError: If *feat_name* is not found.
    """
    # Try as-is (slug), then hyphenated
    index = feat_name.lower().replace(" ", "-").replace("(", "").replace(")", "")
    doc = await get_feat(index)
    if doc is None:
        raise ValueError(f"Unknown feat: {feat_name!r}.")
    return doc


# ---------------------------------------------------------------------------
# Private table-building helpers (used by get_rules_table)
# ---------------------------------------------------------------------------


async def _build_proficiency_bonus_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for level in range(1, 21):
        table[level] = await get_proficiency_bonus(level)
    return table


async def _build_xp_thresholds() -> list[int]:
    return await get_xp_thresholds()


async def _build_full_caster_slots() -> list[dict[int, int]]:
    slots: list[dict[int, int]] = []
    for level in range(1, 21):
        doc = await _get_level_doc("wizard", level)
        if doc and doc.get("spellcasting"):
            slots.append(_extract_spell_slots(doc["spellcasting"]))
        else:
            slots.append({})
    return slots


async def _build_half_caster_slots() -> list[dict[int, int]]:
    slots: list[dict[int, int]] = []
    for level in range(1, 21):
        doc = await _get_level_doc("paladin", level)
        if doc and doc.get("spellcasting"):
            slots.append(_extract_spell_slots(doc["spellcasting"]))
        else:
            slots.append({})
    return slots


async def _build_warlock_pact_magic() -> list[tuple[int, int]]:
    pact: list[tuple[int, int]] = []
    for level in range(1, 21):
        pact.append(await get_warlock_pact_magic(level))
    return pact
