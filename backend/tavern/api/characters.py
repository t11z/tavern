"""Character management endpoints.

Character creation validates inputs via the Rules Engine and computes
derived fields (HP, AC, spell slots, proficiency bonus, ability modifiers).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tavern.api.dependencies import get_db_session
from tavern.api.errors import bad_request, not_found
from tavern.api.schemas import (
    CharacterCreateRequest,
    CharacterResponse,
    CharacterUpdateRequest,
)
from tavern.core import srd_data
from tavern.core.characters import (
    ability_modifier,
    apply_background_bonuses,
    max_hp_at_level_1,
    proficiency_bonus,
    spell_slots,
    starting_equipment,
    validate_background_ability_bonus,
    validate_standard_array,
)
from tavern.models.campaign import Campaign
from tavern.models.character import Character, InventoryItem

router = APIRouter(prefix="/campaigns", tags=["characters"])

_ABILITY_ORDER = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _character_to_response(character: Character) -> CharacterResponse:
    return CharacterResponse(
        id=character.id,
        campaign_id=character.campaign_id,
        name=character.name,
        class_name=character.class_name,
        level=character.level,
        hp=character.hp,
        max_hp=character.max_hp,
        ac=character.ac,
        ability_scores=character.ability_scores,
        spell_slots={str(k): v for k, v in character.spell_slots.items()},
        features=character.features,
    )


@router.post(
    "/{campaign_id}/characters",
    status_code=201,
    response_model=CharacterResponse,
)
async def create_character(
    campaign_id: uuid.UUID,
    body: CharacterCreateRequest,
    db: DbSession,
) -> CharacterResponse:
    """Create a character and attach it to the campaign.

    Validates:
    - Class must be a recognised SRD class
    - Species must be a recognised SRD species
    - Background must be a recognised SRD background
    - Ability scores must satisfy the chosen method (standard_array only for now)
    - Background bonuses must be valid for the background
    - No final score may exceed 20
    """
    # Campaign must exist
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)

    # --- Validate class / species / background via MongoDB ---
    if await srd_data.get_class(body.class_name.lower()) is None:
        raise bad_request("invalid_class", f"Unknown class: {body.class_name!r}")
    if await srd_data.get_species(body.species.lower()) is None:
        raise bad_request("invalid_species", f"Unknown species: {body.species!r}")
    if await srd_data.get_background(body.background.lower()) is None:
        raise bad_request("invalid_background", f"Unknown background: {body.background!r}")

    # --- Validate ability scores ---
    missing = [a for a in _ABILITY_ORDER if a not in body.ability_scores]
    if missing:
        raise bad_request(
            "missing_ability_scores",
            f"Missing ability scores: {', '.join(missing)}",
        )

    if body.ability_score_method == "standard_array":
        scores_list = [body.ability_scores[a] for a in _ABILITY_ORDER]
        if not validate_standard_array(scores_list):
            raise bad_request(
                "invalid_standard_array",
                "Ability scores must be a permutation of [15, 14, 13, 12, 10, 8]",
            )
    else:
        raise bad_request(
            "unsupported_method",
            f"Ability score method {body.ability_score_method!r} is not supported",
        )

    # --- Validate background bonuses ---
    if not await validate_background_ability_bonus(body.background, body.background_bonuses):
        raise bad_request(
            "invalid_background_bonuses",
            f"Background bonuses are not valid for background {body.background!r}. "
            "Must be +2/+1 or +1/+1/+1 on the background's eligible abilities.",
        )

    # --- Apply bonuses (raises ValueError if any score > 20) ---
    try:
        final_scores = apply_background_bonuses(body.ability_scores, body.background_bonuses)
    except ValueError as exc:
        raise bad_request("score_exceeds_maximum", str(exc)) from exc

    # --- Compute derived values ---
    con_mod = ability_modifier(final_scores["CON"])
    dex_mod = ability_modifier(final_scores["DEX"])
    max_hp = await max_hp_at_level_1(body.class_name, con_mod)
    prof_bonus = await proficiency_bonus(1)

    # Unarmored AC (base; armor integration is a future phase)
    ac = 10 + dex_mod

    # Spell slots at level 1 (empty dict for non-casters)
    slots = await spell_slots(body.class_name, 1)
    slots_str = {str(k): v for k, v in slots.items()}

    ability_modifiers_map = {a: ability_modifier(final_scores[a]) for a in _ABILITY_ORDER}

    features: dict = {
        "species": body.species,
        "background": body.background,
        "proficiency_bonus": prof_bonus,
        "ability_modifiers": ability_modifiers_map,
        "languages": body.languages,
    }

    # --- Validate equipment choice ---
    equip = await starting_equipment(body.class_name)
    option_key = body.equipment_choices.replace("package_", "option_")
    if option_key not in equip:
        valid_choices = [f"package_{k.split('_', 1)[1]}" for k in equip]
        raise bad_request(
            "invalid_equipment_choice",
            f"Equipment choice {body.equipment_choices!r} is not valid for "
            f"{body.class_name}. Valid choices: {', '.join(valid_choices)}",
        )

    # --- Persist character ---
    character = Character(
        campaign_id=campaign_id,
        name=body.name,
        class_name=body.class_name,
        level=1,
        hp=max_hp,
        max_hp=max_hp,
        ac=ac,
        ability_scores=final_scores,
        spell_slots=slots_str,
        features=features,
    )
    db.add(character)
    await db.flush()  # Get character.id

    # Create inventory items from chosen equipment package
    for item_name in equip[option_key]:
        db.add(InventoryItem(character_id=character.id, name=item_name))

    await db.commit()
    await db.refresh(character)

    return _character_to_response(character)


@router.get("/{campaign_id}/characters", response_model=list[CharacterResponse])
async def list_characters(
    campaign_id: uuid.UUID,
    db: DbSession,
) -> list[CharacterResponse]:
    """List all characters belonging to the campaign."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    chars_result = await db.execute(select(Character).where(Character.campaign_id == campaign_id))
    return [_character_to_response(c) for c in chars_result.scalars().all()]


@router.get(
    "/{campaign_id}/characters/{character_id}",
    response_model=CharacterResponse,
)
async def get_character(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    db: DbSession,
) -> CharacterResponse:
    """Get a single character, enforcing campaign membership."""
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.campaign_id == campaign_id,
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise not_found("character", character_id)
    return _character_to_response(character)


@router.patch(
    "/{campaign_id}/characters/{character_id}",
    response_model=CharacterResponse,
)
async def update_character(
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    body: CharacterUpdateRequest,
    db: DbSession,
) -> CharacterResponse:
    """Update a character's name or HP."""
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.campaign_id == campaign_id,
        )
    )
    character = result.scalar_one_or_none()
    if character is None:
        raise not_found("character", character_id)

    if body.name is not None:
        character.name = body.name
    if body.hp is not None:
        if body.hp < 0:
            raise bad_request("invalid_hp", "HP cannot be negative")
        character.hp = body.hp

    await db.commit()
    await db.refresh(character)
    return _character_to_response(character)


# Suppress F401 for selectinload import used in future queries
_ = selectinload
