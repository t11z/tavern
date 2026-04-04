"""Turn submission and retrieval endpoints.

Turn processing pipeline (Phase 5b — streaming via WebSocket):
  1. Validate campaign is Active with an open session
  2. Validate character belongs to the campaign
  3. Run Rules Engine: classify action → resolve mechanics → apply DB state
  4. Build state snapshot (Context Builder) — uses request DB session
  5. Create pending Turn record (narrative_response=None)
  6. Return 202 Accepted with turn_id
  7. Background task: stream narrative → broadcast WebSocket events
     → persist full narrative → update rolling summary
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from tavern.api.dependencies import get_db_session, get_narrator, get_session_factory
from tavern.api.errors import bad_request, conflict, not_found
from tavern.api.schemas import (
    TurnCreateRequest,
    TurnListItem,
    TurnListResponse,
    TurnSubmitResponse,
)
from tavern.core.action_analyzer import ActionAnalysis, ActionCategory, analyze_action
from tavern.core.dice import roll_d20
from tavern.core.spells import resolve_spell
from tavern.dm.context_builder import TurnContext, build_snapshot
from tavern.dm.narrator import Narrator
from tavern.dm.summary import build_turn_summary_input, trim_summary
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.session import Session
from tavern.models.turn import Turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["turns"])

# ---------------------------------------------------------------------------
# Spellcasting ability by class (SRD 5.2.1)
# ---------------------------------------------------------------------------

_SPELLCASTING_ABILITY: dict[str, str] = {
    "Bard": "CHA",
    "Cleric": "WIS",
    "Druid": "WIS",
    "Paladin": "CHA",
    "Ranger": "WIS",
    "Sorcerer": "CHA",
    "Warlock": "CHA",
    "Wizard": "INT",
}

# Default placeholder AC used when no target state is available in M1.
_PLACEHOLDER_TARGET_AC = 13


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------


def _character_to_caster_state(character: Character) -> dict:
    """Convert a Character ORM object to the caster dict expected by resolve_spell."""
    mods: dict[str, int] = character.features.get("ability_modifiers", {})
    return {
        "class_name": character.class_name,
        "level": character.level,
        "hp": character.hp,
        "max_hp": character.max_hp,
        "con_modifier": mods.get("CON", 0),
        "ability_scores": character.ability_scores,
        "ability_modifiers": mods,
        "proficiency_bonus": character.features.get("proficiency_bonus", 2),
        "spellcasting_ability": _SPELLCASTING_ABILITY.get(character.class_name, "INT"),
        "spell_slots": {int(k): v for k, v in character.spell_slots.items() if v > 0},
        "spell_slots_used": {},
    }


async def _consume_spell_slot(character: Character, slot_level: int) -> bool:
    """Decrement one spell slot of *slot_level* on *character*.

    Returns True if successful, False if no slot of that level is available.
    SQLAlchemy requires reassignment (not in-place mutation) to track changes.
    """
    current = int(character.spell_slots.get(str(slot_level), 0))
    if current <= 0:
        return False
    new_slots = dict(character.spell_slots)
    new_slots[str(slot_level)] = current - 1
    character.spell_slots = new_slots
    return True


async def _resolve_action(
    analysis: ActionAnalysis,
    character: Character,
    campaign_id: uuid.UUID,
) -> tuple[str | None, dict | None]:
    """Route the classified action to the appropriate Rules Engine function.

    Returns:
        ``(rules_result, char_update)`` where *rules_result* is a human-readable
        summary string for the Context Builder and *char_update* is a dict
        broadcast via the ``character.updated`` WebSocket event, or ``None``
        if no character state changed.
    """
    char_update: dict | None = None

    if analysis.category == ActionCategory.CAST_SPELL:
        if analysis.spell_index is None:
            return ("Cast a spell (unrecognized — no mechanical resolution).", None)

        caster = _character_to_caster_state(character)

        # Determine slot level: use lowest available slot that can cast this spell.
        # For M1, attempt slot 1 → 9 until one is available; fall back to 0 (cantrip attempt).
        available_slots = {int(k): v for k, v in character.spell_slots.items() if int(v) > 0}
        slot_level: int | None = min(available_slots.keys()) if available_slots else None

        # Build a minimal placeholder target
        placeholder_target = {
            "ac": _PLACEHOLDER_TARGET_AC,
            "ability_scores": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
            "saving_throw_modifiers": {},
        }

        try:
            result = await resolve_spell(
                spell_index=analysis.spell_index,
                caster=caster,
                targets=[placeholder_target],
                slot_level=slot_level,
                campaign_id=str(campaign_id),
            )
        except ValueError as exc:
            logger.debug("Spell resolution skipped for %r: %s", analysis.spell_index, exc)
            return (f"Attempted to cast {analysis.spell_index} — {exc}", None)

        # Consume the spell slot if one was used
        if result.slot_consumed is not None:
            await _consume_spell_slot(character, result.slot_consumed)

        # Apply healing to character HP
        hp_changed = False
        if result.healing:
            for h in result.healing:
                new_hp = min(character.max_hp, character.hp + h.hp_restored)
                character.hp = new_hp
                hp_changed = True

        if result.slot_consumed is not None or hp_changed:
            char_update = {
                "character_id": str(character.id),
                "campaign_id": str(campaign_id),
                "hp": character.hp,
                "spell_slots": character.spell_slots,
            }

        return (result.description, char_update)

    if analysis.category in (ActionCategory.MELEE_ATTACK, ActionCategory.RANGED_ATTACK):
        mods = character.features.get("ability_modifiers", {})
        prof = character.features.get("proficiency_bonus", 2)

        if analysis.category == ActionCategory.MELEE_ATTACK:
            ability_mod = mods.get("STR", 0)
            damage_dice = "1d6"
            damage_type = "Slashing"
        else:
            ability_mod = mods.get("DEX", 0)
            damage_dice = "1d8"
            damage_type = "Piercing"

        attack_mod = ability_mod + prof
        from tavern.core.combat import resolve_attack

        attack_result = resolve_attack(
            attack_modifier=attack_mod,
            target_ac=_PLACEHOLDER_TARGET_AC,
            damage_dice=damage_dice,
            damage_modifier=ability_mod,
            damage_type=damage_type,
        )

        if attack_result.total_cover:
            summary = "Attack blocked by total cover."
        elif attack_result.hit:
            dmg = attack_result.damage.total if attack_result.damage else 0
            crit = " (Critical Hit!)" if attack_result.is_critical else ""
            summary = (
                f"Attack roll {attack_result.attack_roll.total} — hit! "
                f"Deals {dmg} {damage_type} damage{crit}."
            )
        else:
            summary = f"Attack roll {attack_result.attack_roll.total} — miss."

        target = f" {analysis.target_name}" if analysis.target_name else ""
        return (f"Attacks{target}: {summary}", None)

    if analysis.category == ActionCategory.ABILITY_CHECK:
        mods = character.features.get("ability_modifiers", {})
        ability = analysis.ability or "STR"
        modifier = mods.get(ability, 0)
        d20_result = roll_d20(modifier=modifier)
        return (
            f"{ability} check: rolled {d20_result.natural} + {modifier} = {d20_result.total}.",
            None,
        )

    # Movement, Interaction, Narrative, Unknown — no mechanical resolution
    return (None, None)


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
NarratorDep = Annotated[Narrator, Depends(get_narrator)]
SessionFactoryDep = Annotated[async_sessionmaker, Depends(get_session_factory)]


# ---------------------------------------------------------------------------
# Background streaming task
# ---------------------------------------------------------------------------


async def _stream_narrative(
    *,
    campaign_id: uuid.UUID,
    turn_id: uuid.UUID,
    snapshot,
    narrator: Narrator,
    character_name: str,
    sequence_number: int,
    current_summary: str,
    session_factory: async_sessionmaker,
) -> None:
    """Stream narrative chunks via WebSocket and persist the completed turn.

    Runs as a BackgroundTask after the 202 response is sent.
    Creates its own DB session because the request session is already closed.
    """
    # Lazy import to avoid circular dependency (ws imports from models, turns imports ws)
    from tavern.api.ws import manager

    full_narrative = ""

    await manager.broadcast(
        campaign_id,
        {"event": "turn.narrative_start", "payload": {"turn_id": str(turn_id)}},
    )

    try:
        seq = 0
        async for chunk in narrator.narrate_turn_stream(snapshot):
            full_narrative += chunk
            await manager.broadcast(
                campaign_id,
                {
                    "event": "turn.narrative_chunk",
                    "payload": {
                        "turn_id": str(turn_id),
                        "chunk": chunk,
                        "sequence": seq,
                    },
                },
            )
            seq += 1
    except Exception as exc:
        logger.error("Narrative streaming error for turn %s: %s", turn_id, exc)
        await manager.broadcast(
            campaign_id,
            {
                "event": "system.error",
                "payload": {"message": f"Narrator error: {exc}"},
            },
        )
        full_narrative = full_narrative or "[Narrator error — please retry]"

    await manager.broadcast(
        campaign_id,
        {
            "event": "turn.narrative_end",
            "payload": {"turn_id": str(turn_id), "narrative": full_narrative},
        },
    )

    # Persist narrative and update rolling summary (own session)
    async with session_factory() as db:
        try:
            turn = await db.get(Turn, turn_id)
            if turn is not None:
                turn.narrative_response = full_narrative

            # Update rolling summary with an informative turn line
            turn_line = build_turn_summary_input(
                character_name=character_name,
                player_action=snapshot.current_turn.player_action,
                rules_result=snapshot.current_turn.rules_result,
                narrative_excerpt=full_narrative,
                sequence_number=sequence_number,
            )
            try:
                new_summary = await narrator.update_summary(
                    recent_turns=[turn_line],
                    current_summary=current_summary,
                )
                # Enforce the 500-token budget as a hard safety net after LLM compression.
                new_summary = trim_summary(new_summary)
            except Exception as exc:
                logger.warning("Summary update failed: %s — keeping previous summary", exc)
                new_summary = trim_summary(current_summary)

            # Update CampaignState
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == campaign_id)
            )
            campaign_state = state_result.scalar_one_or_none()
            if campaign_state is not None:
                campaign_state.rolling_summary = new_summary
                campaign_state.updated_at = datetime.now(tz=UTC)

            # Update last_played_at
            camp = await db.get(Campaign, campaign_id)
            if camp is not None:
                camp.last_played_at = datetime.now(tz=UTC)

            await db.commit()
        except Exception as exc:
            logger.error("DB persist failed for turn %s: %s", turn_id, exc)


# ---------------------------------------------------------------------------
# Turn submission
# ---------------------------------------------------------------------------


@router.post(
    "/{campaign_id}/turns",
    status_code=202,
    response_model=TurnSubmitResponse,
)
async def submit_turn(
    campaign_id: uuid.UUID,
    body: TurnCreateRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    narrator: NarratorDep,
    session_factory: SessionFactoryDep,
) -> TurnSubmitResponse:
    """Submit a player action. Returns 202; narrative arrives via WebSocket.

    The narrative is streamed token-by-token to all WebSocket connections
    for this campaign. On completion, the Turn record is persisted.
    """
    # 1. Load campaign with state and characters
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(
            selectinload(Campaign.state),
            selectinload(Campaign.characters).selectinload(Character.inventory),
            selectinload(Campaign.characters).selectinload(Character.conditions),
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)

    if campaign.status != "active":
        raise conflict(
            "campaign_not_active",
            f"Campaign is {campaign.status} — start a session before submitting turns",
        )
    if campaign.state is None:
        raise bad_request("missing_campaign_state", "Campaign has no state record")

    # 2. Find the open session
    session_result = await db.execute(
        select(Session).where(
            Session.campaign_id == campaign_id,
            Session.ended_at.is_(None),
        )
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        raise conflict("no_open_session", "No open session found — start a session first")

    # 3. Validate character belongs to campaign
    char_result = await db.execute(
        select(Character).where(
            Character.id == body.character_id,
            Character.campaign_id == campaign_id,
        )
    )
    character = char_result.scalar_one_or_none()
    if character is None:
        raise bad_request(
            "character_not_in_campaign",
            f"Character {body.character_id} does not belong to campaign {campaign_id}",
        )

    # 4. Run Rules Engine: classify action → resolve mechanics → update character state
    try:
        analysis = analyze_action(body.action, _character_to_caster_state(character))
        rules_result, char_update = await _resolve_action(analysis, character, campaign_id)
    except Exception as exc:
        logger.warning("Rules Engine error for turn (campaign=%s): %s", campaign_id, exc)
        rules_result, char_update = None, None

    # 5. Determine sequence number and build snapshot
    sequence_number = campaign.state.turn_count + 1

    turn_ctx = TurnContext(player_action=body.action, rules_result=rules_result)
    snapshot = await build_snapshot(
        campaign_id=campaign_id,
        current_turn=turn_ctx,
        db_session=db,
    )

    # 6. Create pending Turn record (ADR-0004: atomic, autosave every turn)
    turn = Turn(
        session_id=session.id,
        character_id=body.character_id,
        sequence_number=sequence_number,
        player_action=body.action,
        rules_result=rules_result,
        narrative_response=None,  # Set by background task when streaming completes
    )
    db.add(turn)

    campaign_state: CampaignState = campaign.state
    campaign_state.turn_count = sequence_number
    campaign.last_played_at = datetime.now(tz=UTC)

    await db.commit()
    await db.refresh(turn)

    # Broadcast character state change if the engine mutated it
    if char_update:
        from tavern.api.ws import manager

        await manager.broadcast(
            campaign_id,
            {"event": "character.updated", "payload": char_update},
        )

    # 7. Schedule streaming as background task
    background_tasks.add_task(
        _stream_narrative,
        campaign_id=campaign_id,
        turn_id=turn.id,
        snapshot=snapshot,
        narrator=narrator,
        character_name=character.name,
        sequence_number=sequence_number,
        current_summary=campaign_state.rolling_summary,
        session_factory=session_factory,
    )

    return TurnSubmitResponse(turn_id=turn.id, sequence_number=sequence_number)


# ---------------------------------------------------------------------------
# Turn retrieval
# ---------------------------------------------------------------------------


@router.get("/{campaign_id}/turns", response_model=TurnListResponse)
async def list_turns(
    campaign_id: uuid.UUID,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TurnListResponse:
    """List turns for the campaign, paginated, in sequence order."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    count_result = await db.execute(
        select(func.count(Turn.id))
        .join(Session, Turn.session_id == Session.id)
        .where(Session.campaign_id == campaign_id)
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    turns_result = await db.execute(
        select(Turn)
        .join(Session, Turn.session_id == Session.id)
        .where(Session.campaign_id == campaign_id)
        .order_by(Turn.sequence_number)
        .offset(offset)
        .limit(page_size)
    )
    turns = turns_result.scalars().all()

    items = [
        TurnListItem(
            turn_id=t.id,
            sequence_number=t.sequence_number,
            character_id=t.character_id,
            player_action=t.player_action,
            rules_result=t.rules_result,
            narrative_response=t.narrative_response,
            created_at=t.created_at,
        )
        for t in turns
    ]

    return TurnListResponse(turns=items, total=total, page=page, page_size=page_size)


@router.get("/{campaign_id}/turns/{turn_id}", response_model=TurnListItem)
async def get_turn(
    campaign_id: uuid.UUID,
    turn_id: uuid.UUID,
    db: DbSession,
) -> TurnListItem:
    """Get a single turn, enforcing campaign membership."""
    result = await db.execute(
        select(Turn)
        .join(Session, Turn.session_id == Session.id)
        .where(
            Turn.id == turn_id,
            Session.campaign_id == campaign_id,
        )
    )
    turn = result.scalar_one_or_none()
    if turn is None:
        raise not_found("turn", turn_id)

    return TurnListItem(
        turn_id=turn.id,
        sequence_number=turn.sequence_number,
        character_id=turn.character_id,
        player_action=turn.player_action,
        rules_result=turn.rules_result,
        narrative_response=turn.narrative_response,
        created_at=turn.created_at,
    )
