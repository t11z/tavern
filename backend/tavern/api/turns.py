"""Turn submission and retrieval endpoints.

Turn processing pipeline (Task D — full combat lifecycle):
  1. Validate campaign is Active with an open session
  2. Validate character belongs to the campaign
  3. Run Rules Engine: classify action → resolve mechanics → apply DB state
  4. [Exploration mode only] CombatClassifier → if combat starts, roll
     initiative and transition to combat mode (Flow B: player-initiated)
  5. Build state snapshot (Context Builder) — uses request DB session
  6. Create pending Turn record (narrative_response=None)
  7. Return 202 Accepted with turn_id
  8. Background task:
     a. narrator.narrate_turn_stream() → (narrative_text, gm_signals)
     b. Process gm_signals.npc_updates (BEFORE scene_transition)
     c. Process gm_signals.scene_transition — Engine combat_end takes
        precedence over Narrator signals
     d. Persist narrative_text + gm_signals JSON in turn record
     e. Broadcast narrative_text + update rolling summary
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy import func as sa_func
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
from tavern.core.combat import (
    CombatParticipant,
    CombatSnapshot,
    CombatSnapshotCharacter,
    _has_surprise_immunity,
    determine_surprise,
    roll_initiative_order,
)
from tavern.core.dice import roll_d20
from tavern.core.scene import normalise_scene_id
from tavern.core.spells import resolve_spell
from tavern.dm.context_builder import TurnContext, build_snapshot
from tavern.dm.gm_signals import GMSignals, NPCUpdate, safe_default
from tavern.dm.narrator import Narrator
from tavern.dm.summary import build_turn_summary_input, trim_summary
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.npc import NPC
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

        if result.slot_consumed is not None:
            await _consume_spell_slot(character, result.slot_consumed)

        hp_changed = False
        if result.healing:
            for h in result.healing:
                new_hp = min(character.max_hp, character.hp + h.healing_amount)
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


# ---------------------------------------------------------------------------
# Combat helpers
# ---------------------------------------------------------------------------


def _build_combat_snapshot(characters: list[Character]) -> CombatSnapshot:
    """Build a CombatSnapshot from a list of Character ORM records.

    Populates WIS modifier, Perception proficiency, proficiency bonus, and feats
    for each character so that determine_surprise() can compute passive Perception.
    """
    snap_chars: dict[str, CombatSnapshotCharacter] = {}
    for char in characters:
        mods = char.features.get("ability_modifiers", {})
        wis_mod = mods.get("WIS", 0)
        # Perception proficiency — stored in features.proficiencies or similar
        proficiencies = char.features.get("proficiencies", [])
        perception_proficient = "Perception" in proficiencies
        prof_bonus = char.features.get("proficiency_bonus", 2)
        feats = char.features.get("feats", [])
        snap_chars[str(char.id)] = CombatSnapshotCharacter(
            wis_modifier=wis_mod,
            perception_proficient=perception_proficient,
            proficiency_bonus=prof_bonus,
            feats=feats,
        )
    return CombatSnapshot(characters=snap_chars)


def _build_initiative_order_payload(
    participants: list[CombatParticipant],
) -> tuple[list[dict], list[str]]:
    """Convert CombatParticipant list to WS payload format.

    Returns (initiative_order_dicts, surprised_character_ids).
    """
    order = [
        {
            "character_id": p.character_id,
            "participant_type": p.participant_type,
            "initiative_result": p.initiative_result,
            "surprised": p.surprised,
        }
        for p in participants
    ]
    surprised = [p.character_id for p in participants if p.surprised]
    return order, surprised


async def _run_combat_start(
    *,
    campaign_id: uuid.UUID,
    db: AsyncSession,
    campaign_state: CampaignState,
    characters: list[Character],
    combatant_names: list[str],
    stealth_results: dict[str, int],
    potential_surprised: list[str],
    combat_snapshot: CombatSnapshot,
) -> None:
    """Execute initiative roll and broadcast combat.started.

    Updates world_state["mode"] = "combat" and persists via db.flush().
    Does NOT commit — caller is responsible for committing the transaction.
    Broadcasts "combat.started" via WebSocket.

    Args:
        campaign_id: Campaign UUID.
        db: Active async DB session.
        campaign_state: CampaignState record (will be mutated).
        characters: PC Character records.
        combatant_names: NPC names to include as combatants.
        stealth_results: Stealth totals for concealing characters.
        potential_surprised: character_ids that could be surprised.
        combat_snapshot: Pre-built CombatSnapshot for determine_surprise.
    """
    from tavern.api.ws import manager

    # Determine surprise
    surprised_map = determine_surprise(
        potential_surprised=potential_surprised,
        stealth_results=stealth_results,
        snapshot=combat_snapshot,
    )

    # Build participants: PCs first
    participants: list[CombatParticipant] = []
    dex_modifiers: dict[str, int] = {}

    for char in characters:
        cid = str(char.id)
        mods = char.features.get("ability_modifiers", {})
        dex_mod = mods.get("DEX", 0)
        dex_modifiers[cid] = dex_mod
        participants.append(
            CombatParticipant(
                character_id=cid,
                participant_type="pc",
                initiative_roll=0,
                initiative_result=0,
                surprised=surprised_map.get(cid, False),
            )
        )

    # Add NPC combatants (use name as id for now — no persistent NPC id lookup here)
    for npc_name in combatant_names:
        # Look up NPC record for DEX modifier
        npc_result = await db.execute(
            select(NPC).where(
                NPC.campaign_id == campaign_id,
                sa_func.lower(NPC.name) == npc_name.lower(),
            )
        )
        npc_record = npc_result.scalar_one_or_none()
        npc_id = str(npc_record.id) if npc_record else npc_name
        participants.append(
            CombatParticipant(
                character_id=npc_id,
                participant_type="npc",
                initiative_roll=0,
                initiative_result=0,
                surprised=False,  # NPCs initiating combat are not surprised
            )
        )

    # Roll initiative
    ordered = roll_initiative_order(
        participants,
        surprised_map=surprised_map,
        dex_modifiers=dex_modifiers,
    )

    # Transition to combat mode
    order_payload, surprised_ids = _build_initiative_order_payload(ordered)
    world_state = dict(campaign_state.world_state or {})
    world_state["mode"] = "combat"
    world_state["initiative_order"] = order_payload
    world_state["surprised"] = surprised_ids
    campaign_state.world_state = world_state
    campaign_state.updated_at = datetime.now(tz=UTC)
    await db.flush()

    # Broadcast
    await manager.broadcast_combat_started(campaign_id, order_payload, surprised_ids)
    logger.info(
        "Combat started (campaign=%s): %d participants, %d surprised",
        campaign_id,
        len(ordered),
        len(surprised_ids),
    )


# ---------------------------------------------------------------------------
# NPC update processing
# ---------------------------------------------------------------------------


async def _process_npc_update(
    *,
    update: NPCUpdate,
    campaign_id: uuid.UUID,
    db: AsyncSession,
    sequence_number: int,
) -> None:
    """Apply a single NPCUpdate from GMSignals to the database.

    Performs name-based lookup (case-insensitive within campaign).
    Broadcasts npc.spawned or npc.updated via WebSocket.
    Does NOT commit — caller is responsible for the transaction boundary.
    """
    from tavern.api.ws import manager

    # Name-based lookup (case-insensitive)
    npc_result = await db.execute(
        select(NPC).where(
            NPC.campaign_id == campaign_id,
            sa_func.lower(NPC.name) == update.npc_name.lower(),
        )
    )
    existing = npc_result.scalar_one_or_none()

    if update.event == "spawn":
        if existing is not None:
            logger.info(
                "Duplicate spawn signal discarded for NPC %r in campaign %s — "
                "record already exists",
                update.npc_name,
                campaign_id,
            )
            return

        # Create new NPC record
        npc = NPC(
            campaign_id=campaign_id,
            name=update.npc_name,
            origin="narrator_spawned",
            species=update.species,
            appearance=update.appearance,
            role=update.role,
            motivation=update.motivation,
            disposition=update.disposition or "unknown",
            hp_max=update.hp_max,
            ac=update.ac,
            first_appeared_turn=sequence_number,
            last_seen_turn=sequence_number,
        )

        # Resolve stat block if provided
        if update.stat_block_ref:
            try:
                from tavern.core.srd_data import resolve_npc_stat_block

                stat_block = await resolve_npc_stat_block(update.stat_block_ref, campaign_id)
                if stat_block:
                    npc.stat_block_ref = update.stat_block_ref
                    # Narrator overrides take precedence — only fill if not set
                    if npc.hp_max is None:
                        npc.hp_max = stat_block.get("hit_points")
                    if npc.ac is None:
                        npc.ac = stat_block.get("armor_class")
                    if npc.creature_type is None:
                        npc.creature_type = stat_block.get("type")
            except Exception as exc:
                logger.warning(
                    "Failed to resolve stat_block_ref %r for NPC %r: %s",
                    update.stat_block_ref,
                    update.npc_name,
                    exc,
                )

        db.add(npc)
        await db.flush()  # Obtain NPC id

        await manager.broadcast_npc_spawned(
            campaign_id,
            npc_id=str(npc.id),
            name=npc.name,
            role=npc.role,
        )
        logger.info(
            "NPC spawned: %r (id=%s) in campaign %s",
            npc.name,
            npc.id,
            campaign_id,
        )

    else:
        # Non-spawn update — NPC must already exist
        if existing is None:
            logger.error(
                "GMSignals %s update for unknown NPC %r in campaign %s — skipping",
                update.event,
                update.npc_name,
                campaign_id,
            )
            return

        changes: dict = {}

        # Validate no immutable fields are being changed
        try:
            NPC.validate_immutable_update({})
        except ValueError:
            pass  # validate_immutable_update only raises if forbidden keys present

        if update.event == "status_change" and update.new_status is not None:
            existing.status = update.new_status
            changes["status"] = update.new_status

        elif update.event == "disposition_change" and update.new_disposition is not None:
            existing.disposition = update.new_disposition
            changes["disposition"] = update.new_disposition

        elif update.event == "location_change" and update.new_location is not None:
            try:
                normalised_location = normalise_scene_id(update.new_location)
            except ValueError as exc:
                logger.error(
                    "GMSignals location_change for NPC %r in campaign %s rejected — "
                    "invalid scene identifier: %s",
                    update.npc_name,
                    campaign_id,
                    exc,
                )
                return
            existing.scene_location = normalised_location
            changes["scene_location"] = normalised_location

        existing.last_seen_turn = sequence_number

        await manager.broadcast_npc_updated(
            campaign_id,
            npc_id=str(existing.id),
            changes=changes,
        )
        logger.info(
            "NPC updated: %r (id=%s) event=%s changes=%s",
            existing.name,
            existing.id,
            update.event,
            changes,
        )


# ---------------------------------------------------------------------------
# Dependency annotations
# ---------------------------------------------------------------------------

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
    world_state: dict,
) -> None:
    """Run the full post-narration pipeline as a background task.

    Pipeline:
    1. Narrate → (narrative_text, gm_signals)
    2. Broadcast narrative start / chunk / end events
    3. Process gm_signals.npc_updates (within DB transaction)
    4. Process gm_signals.scene_transition (Engine combat_end takes precedence)
    5. Persist turn narrative + gm_signals JSON
    6. Update rolling summary

    Creates its own DB session because the request session is already closed.
    """
    from tavern.api.ws import manager

    full_narrative = ""
    gm_signals: GMSignals = safe_default()

    await manager.broadcast(
        campaign_id,
        {"event": "turn.narrative_start", "payload": {"turn_id": str(turn_id)}},
    )

    try:
        full_narrative, gm_signals = await narrator.narrate_turn_stream(snapshot)
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
        gm_signals = safe_default()

    await manager.broadcast(
        campaign_id,
        {
            "event": "turn.narrative_end",
            "payload": {"turn_id": str(turn_id), "narrative": full_narrative},
        },
    )

    # Emit suggested actions immediately after narrative_end (ADR-0015)
    if gm_signals.suggested_actions:
        await manager.broadcast(
            campaign_id,
            {
                "type": "turn.suggested_actions",
                "payload": {
                    "turn_id": str(turn_id),
                    "suggestions": gm_signals.suggested_actions,
                },
            },
        )

    # Persist narrative and process GMSignals (own session)
    async with session_factory() as db:
        try:
            # -------------------------------------------------------------------
            # Step A: Process npc_updates BEFORE scene_transition
            # -------------------------------------------------------------------
            for npc_update in gm_signals.npc_updates:
                try:
                    await _process_npc_update(
                        update=npc_update,
                        campaign_id=campaign_id,
                        db=db,
                        sequence_number=sequence_number,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to process NPCUpdate %r for campaign %s: %s",
                        npc_update,
                        campaign_id,
                        exc,
                    )

            # -------------------------------------------------------------------
            # Step B: Process scene_transition
            # -------------------------------------------------------------------
            current_mode = str(world_state.get("mode", "exploration"))

            # Re-load campaign state to get latest world_state (may have been
            # updated by the request-phase combat start)
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == campaign_id)
            )
            campaign_state = state_result.scalar_one_or_none()

            # Check whether the Rules Engine ended combat (all NPCs at 0 HP).
            # For M1 we detect this via the world_state "engine_combat_end" flag
            # that submit_turn may have set.  If not set, we rely on Narrator signals.
            engine_combat_end = bool(world_state.get("engine_combat_end", False))

            if engine_combat_end and campaign_state is not None:
                # Engine authority — always transitions to exploration
                updated_ws = dict(campaign_state.world_state or {})
                updated_ws["mode"] = "exploration"
                updated_ws.pop("engine_combat_end", None)
                updated_ws.pop("initiative_order", None)
                updated_ws.pop("surprised", None)
                campaign_state.world_state = updated_ws
                campaign_state.updated_at = datetime.now(tz=UTC)
                await db.flush()
                await manager.broadcast_combat_ended(campaign_id)
                logger.info("Combat ended (Engine authority) for campaign %s", campaign_id)

                if gm_signals.scene_transition.type == "combat_end":
                    logger.info(
                        "Narrator combat_end signal discarded — Engine takes precedence "
                        "(campaign=%s)",
                        campaign_id,
                    )

            elif (
                gm_signals.scene_transition.type == "combat_start"
                and current_mode == "exploration"
                and campaign_state is not None
            ):
                # NPC-initiated combat (Flow A) — narrator signalled combat start
                # Load characters for CombatSnapshot
                chars_result = await db.execute(
                    select(Character).where(Character.campaign_id == campaign_id)
                )
                chars = list(chars_result.scalars().all())
                combat_snapshot = _build_combat_snapshot(chars)

                # Pre-filter Alert feat
                raw_potential = gm_signals.scene_transition.potential_surprised_characters
                potential_surprised = [
                    cid
                    for cid in raw_potential
                    if not _has_surprise_immunity(cid, combat_snapshot)
                ]

                # Auto-roll NPC stealth for concealers
                npc_stealth: dict[str, int] = {}
                for npc_name in gm_signals.scene_transition.combatants:
                    npc_result = await db.execute(
                        select(NPC).where(
                            NPC.campaign_id == campaign_id,
                            sa_func.lower(NPC.name) == npc_name.lower(),
                        )
                    )
                    npc_record = npc_result.scalar_one_or_none()

                    stealth_mod = 0
                    if npc_record and npc_record.stat_block_ref:
                        try:
                            from tavern.core.srd_data import resolve_npc_stat_block

                            sb = await resolve_npc_stat_block(
                                npc_record.stat_block_ref, campaign_id
                            )
                            if sb:
                                stealth_mod = sb.get("stealth_modifier", 0)
                        except Exception as exc:
                            logger.warning(
                                "Could not resolve stat block for NPC stealth "
                                "(npc=%r, campaign=%s): %s",
                                npc_name,
                                campaign_id,
                                exc,
                            )
                    else:
                        logger.warning(
                            "No stat block for NPC stealth roll (npc=%r, campaign=%s)",
                            npc_name,
                            campaign_id,
                        )

                    npc_key = str(npc_record.id) if npc_record else npc_name
                    npc_stealth[npc_key] = roll_d20(modifier=stealth_mod).total

                await _run_combat_start(
                    campaign_id=campaign_id,
                    db=db,
                    campaign_state=campaign_state,
                    characters=chars,
                    combatant_names=gm_signals.scene_transition.combatants,
                    stealth_results=npc_stealth,
                    potential_surprised=potential_surprised,
                    combat_snapshot=combat_snapshot,
                )

            elif (
                gm_signals.scene_transition.type == "combat_end"
                and current_mode == "combat"
                and not engine_combat_end
                and campaign_state is not None
            ):
                # Narrator-signalled combat end (no Engine authority override)
                updated_ws = dict(campaign_state.world_state or {})
                updated_ws["mode"] = "exploration"
                updated_ws.pop("initiative_order", None)
                updated_ws.pop("surprised", None)
                campaign_state.world_state = updated_ws
                campaign_state.updated_at = datetime.now(tz=UTC)
                await db.flush()
                await manager.broadcast_combat_ended(campaign_id)
                logger.info("Combat ended (Narrator signal) for campaign %s", campaign_id)

            # -------------------------------------------------------------------
            # Step C: Persist turn narrative and gm_signals JSON
            # -------------------------------------------------------------------
            turn = await db.get(Turn, turn_id)
            if turn is not None:
                turn.narrative_response = full_narrative

            # -------------------------------------------------------------------
            # Step D: Update rolling summary
            # -------------------------------------------------------------------
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
                new_summary = trim_summary(new_summary)
            except Exception as exc:
                logger.warning("Summary update failed: %s — keeping previous summary", exc)
                new_summary = trim_summary(current_summary)

            if campaign_state is not None:
                campaign_state.rolling_summary = new_summary
                campaign_state.updated_at = datetime.now(tz=UTC)

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

    # 6. [Exploration mode only] CombatClassifier pre-narration check (Flow B)
    current_mode = str((campaign.state.world_state or {}).get("mode", "exploration"))
    world_state_copy = dict(campaign.state.world_state or {})

    if current_mode == "exploration":
        try:
            from tavern.dm.combat_classifier import CombatClassifier

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            classifier = CombatClassifier(api_key=api_key)
            classification = await classifier.classify(body.action, snapshot)
            logger.debug(
                "CombatClassifier result (campaign=%s): combat_starts=%s confidence=%s reason=%s",
                campaign_id,
                classification.combat_starts,
                classification.confidence,
                classification.reason,
            )

            if classification.combat_starts:
                # Flow B: player-initiated combat
                combat_snapshot = _build_combat_snapshot(campaign.characters)

                # Stealth rolls from the current turn context (if any)
                stealth_rolls = snapshot.current_turn.stealth_rolls or {}

                # For player-initiated combat, potential_surprised are scene NPCs
                # whose ids we can match by name from combatants list
                potential_surprised: list[str] = []
                for npc_name in classification.combatants:
                    npc_res = await db.execute(
                        select(NPC).where(
                            NPC.campaign_id == campaign_id,
                            sa_func.lower(NPC.name) == npc_name.lower(),
                        )
                    )
                    npc_rec = npc_res.scalar_one_or_none()
                    if npc_rec:
                        potential_surprised.append(str(npc_rec.id))

                # Pre-filter Alert feat
                potential_surprised = [
                    cid
                    for cid in potential_surprised
                    if not _has_surprise_immunity(cid, combat_snapshot)
                ]

                await _run_combat_start(
                    campaign_id=campaign_id,
                    db=db,
                    campaign_state=campaign.state,
                    characters=list(campaign.characters),
                    combatant_names=classification.combatants,
                    stealth_results=stealth_rolls,
                    potential_surprised=potential_surprised,
                    combat_snapshot=combat_snapshot,
                )
                # Update local copy for background task
                world_state_copy["mode"] = "combat"

        except RuntimeError as exc:
            # CombatClassifier raises RuntimeError if called in combat mode
            logger.warning("CombatClassifier RuntimeError (campaign=%s): %s", campaign_id, exc)
        except Exception as exc:
            logger.warning(
                "CombatClassifier error (campaign=%s): %s — continuing without classification",
                campaign_id,
                exc,
            )

    # 7. Create pending Turn record (ADR-0004: atomic, autosave every turn)
    # Note: Turn model may or may not have a gm_signals column yet — we store
    # it in the background task after narration.
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

    # 8. Schedule background task
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
        world_state=world_state_copy,
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
