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

import json
import logging
import os
import time
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
from tavern.dm.gm_signals import (
    GMSignals,
    NPCUpdate,
    safe_default,
)
from tavern.dm.narrator import Narrator
from tavern.dm.summary import build_turn_summary_input, trim_summary
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.npc import NPC
from tavern.models.session import Session
from tavern.models.turn import Turn
from tavern.observability import (
    LLMCallRecord,
    PipelineStep,
    TurnEventLogAccumulator,
    turn_event_log_to_dict,
)

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


def _mechanical_results_from_attack(
    attack_result,
    character_name: str,
    target_name: str | None,
    damage_type: str,
) -> list[dict]:
    """Build mechanical_results entries from a single AttackResult.

    Produces an ``attack_roll`` entry and, on a hit, a ``damage`` entry.
    """
    entries: list[dict] = []

    target = target_name or "target"
    hit = attack_result.hit and not attack_result.total_cover

    attack_entry: dict = {
        "type": "attack_roll",
        "attacker": character_name,
        "target": target,
        "roll": attack_result.attack_roll.total,
        "ac": attack_result.effective_ac,
        "hit": hit,
    }
    if hit and attack_result.damage is not None:
        attack_entry["damage_amount"] = attack_result.damage.total
        attack_entry["damage_type"] = attack_result.damage.damage_type
    entries.append(attack_entry)

    if hit and attack_result.damage is not None:
        entries.append(
            {
                "type": "damage",
                "target": target,
                "amount": attack_result.damage.total,
                "damage_type": attack_result.damage.damage_type,
            }
        )

    return entries


def _mechanical_results_from_spell(
    spell_result,
    character_name: str,
    targets: list[dict],
) -> list[dict]:
    """Build mechanical_results entries from a SpellResult.

    Produces a ``spell_cast`` entry, per-target ``saving_throw`` / ``damage``
    / ``healing`` entries, and per-target ``condition_applied`` entries.
    """
    entries: list[dict] = []

    target_names = [t.get("name", f"target {i}") for i, t in enumerate(targets)]

    # spell_cast summary entry
    spell_entry: dict = {
        "type": "spell_cast",
        "caster": character_name,
        "spell_name": spell_result.spell_name,
        "slot_level": spell_result.slot_consumed,
        "targets": target_names,
    }
    entries.append(spell_entry)

    # attack_roll for spell attack spells (single target in M1)
    if spell_result.attack_result is not None:
        ar = spell_result.attack_result
        target = target_names[0] if target_names else "target"
        hit = ar.hit and not ar.total_cover
        attack_entry: dict = {
            "type": "attack_roll",
            "attacker": character_name,
            "target": target,
            "roll": ar.attack_roll.total,
            "ac": ar.effective_ac,
            "hit": hit,
        }
        if hit and ar.damage is not None:
            attack_entry["damage_amount"] = ar.damage.total
            attack_entry["damage_type"] = ar.damage.damage_type
        entries.append(attack_entry)

    # saving_throw entries (one per target that had a save)
    for dmg_app in spell_result.damage:
        if dmg_app.save_roll is not None:
            t_name = (
                target_names[dmg_app.target_index]
                if dmg_app.target_index < len(target_names)
                else f"target {dmg_app.target_index}"
            )
            entries.append(
                {
                    "type": "saving_throw",
                    "target": t_name,
                    "roll": dmg_app.save_roll.total,
                    "success": dmg_app.saved,
                }
            )

    # damage entries
    for dmg_app in spell_result.damage:
        if dmg_app.damage_total > 0:
            t_name = (
                target_names[dmg_app.target_index]
                if dmg_app.target_index < len(target_names)
                else f"target {dmg_app.target_index}"
            )
            entries.append(
                {
                    "type": "damage",
                    "target": t_name,
                    "amount": dmg_app.damage_total,
                    "damage_type": dmg_app.damage_type,
                }
            )

    # healing entries
    if spell_result.healing:
        for heal_app in spell_result.healing:
            t_name = (
                target_names[heal_app.target_index]
                if heal_app.target_index < len(target_names)
                else f"target {heal_app.target_index}"
            )
            entries.append(
                {
                    "type": "healing",
                    "target": t_name,
                    "amount": heal_app.healing_amount,
                }
            )

    # condition_applied / condition_removed entries
    for cond_app in spell_result.conditions_applied:
        t_name = (
            target_names[cond_app.target_index]
            if cond_app.target_index < len(target_names)
            else f"target {cond_app.target_index}"
        )
        entry_type = "condition_applied" if cond_app.applied else "condition_removed"
        entries.append(
            {
                "type": entry_type,
                "target": t_name,
                "condition": cond_app.condition_name,
                "source": spell_result.spell_name,
            }
        )

    return entries


async def _resolve_action(
    analysis: ActionAnalysis,
    character: Character,
    campaign_id: uuid.UUID,
) -> tuple[str | None, dict | None, list[dict] | None]:
    """Route the classified action to the appropriate Rules Engine function.

    Returns:
        ``(rules_result, char_update, mechanical_results)`` where
        *rules_result* is a human-readable summary string for the Context
        Builder, *char_update* is a dict broadcast via the
        ``character.updated`` WebSocket event (or ``None`` if no character
        state changed), and *mechanical_results* is a list of typed entry
        dicts for the JSONB column (or ``None`` for narrative-only turns).
    """
    char_update: dict | None = None

    if analysis.category == ActionCategory.CAST_SPELL:
        if analysis.spell_index is None:
            return ("Cast a spell (unrecognized — no mechanical resolution).", None, None)

        caster = _character_to_caster_state(character)

        # Determine slot level: use lowest available slot that can cast this spell.
        available_slots = {int(k): v for k, v in character.spell_slots.items() if int(v) > 0}
        slot_level: int | None = min(available_slots.keys()) if available_slots else None

        # Build a minimal placeholder target
        placeholder_target = {
            "ac": _PLACEHOLDER_TARGET_AC,
            "name": "target",
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
            return (f"Attempted to cast {analysis.spell_index} — {exc}", None, None)

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

        mechanical_results = _mechanical_results_from_spell(
            result,
            character_name=character.name,
            targets=[placeholder_target],
        )
        return (result.description, char_update, mechanical_results)

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
        mechanical_results = _mechanical_results_from_attack(
            attack_result,
            character_name=character.name,
            target_name=analysis.target_name,
            damage_type=damage_type,
        )
        return (f"Attacks{target}: {summary}", None, mechanical_results)

    if analysis.category == ActionCategory.ABILITY_CHECK:
        mods = character.features.get("ability_modifiers", {})
        ability = analysis.ability or "STR"
        modifier = mods.get(ability, 0)
        d20_result = roll_d20(modifier=modifier)
        return (
            f"{ability} check: rolled {d20_result.natural} + {modifier} = {d20_result.total}.",
            None,
            None,
        )

    # Movement, Interaction, Narrative, Unknown — no mechanical resolution
    return (None, None, None)


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
    logger.debug(
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

    Spawned NPCs receive scene_location=NULL. The pipeline's post-signal
    finalisation step (ADR-0019, Package C) assigns the final current_scene_id
    to all NULL-location NPCs from this turn after location_change is processed.
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

        # Create new NPC record.
        # scene_location is intentionally left NULL here (ADR-0019, Package C).
        # After all signals are processed, any NULL-location NPCs from this turn
        # are assigned the final current_scene_id in the post-signal finalisation
        # step (handles both the no-location-change and location-change cases).
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
            scene_location=None,
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
    character_id: uuid.UUID,
    snapshot,
    narrator: Narrator,
    character_name: str,
    sequence_number: int,
    current_summary: str,
    session_factory: async_sessionmaker,
    world_state: dict,
    mechanical_results: list[dict] | None = None,
    pre_steps: list[PipelineStep] | None = None,
    pre_llm_calls: list[LLMCallRecord] | None = None,
) -> None:
    """Run the full post-narration pipeline as a background task.

    Pipeline:
    1. Narrate → (narrative_text, gm_signals)
    2. Broadcast narrative start / chunk / end events
    3. (DB session) Process gm_signals in order per ADR-0019 §3:
       a. npc_updates
       b. location_change    ← ADR-0019: update current_scene_id; auto-assign NPC locations
       c. time_progression   ← ADR-0019: update time_of_day
       d. scene_transition   (Engine combat_end takes precedence)
    4. Broadcast location_change and time_progression WebSocket events (after narrative_end)
    5. Persist turn narrative + gm_signals JSON + event_log
    6. Update rolling summary

    Creates its own DB session because the request session is already closed.
    """
    from tavern.api.ws import manager

    # Observability accumulator for this turn's pipeline
    acc = TurnEventLogAccumulator(turn_id=str(turn_id))

    # Inject pre-background steps/calls captured during the request phase
    for step in pre_steps or []:
        acc.add_step(step)
    for call in pre_llm_calls or []:
        acc.add_llm_call(call)

    full_narrative = ""
    gm_signals: GMSignals = safe_default()
    llm_meta: dict = {}
    gm_diag: dict = {"fallback_used": False, "raw_input_truncated": "", "parse_error": None}

    await manager.broadcast(
        campaign_id,
        {"event": "turn.narrative_start", "payload": {"turn_id": str(turn_id)}},
    )

    # --- narration step ---
    narration_start = datetime.now(UTC)
    narration_start_mono = time.monotonic()
    try:
        full_narrative, gm_signals, llm_meta = await narrator.narrate_turn_stream(snapshot)
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
        llm_meta = {}
        acc.add_error(f"Narrator error: {exc}")
    narration_duration_ms = int((time.monotonic() - narration_start_mono) * 1000)

    # Record narration LLM call if we have metadata
    if llm_meta:
        acc.add_llm_call(
            LLMCallRecord(
                call_type=llm_meta.get("call_type", "narration"),
                model_id=llm_meta.get("model_id", "unknown"),
                model_tier=llm_meta.get("model_tier", "high"),
                input_tokens=llm_meta.get("input_tokens", 0),
                output_tokens=llm_meta.get("output_tokens", 0),
                cache_read_tokens=llm_meta.get("cache_read_tokens", 0),
                cache_creation_tokens=llm_meta.get("cache_creation_tokens", 0),
                latency_ms=llm_meta.get("latency_ms", narration_duration_ms),
                stream_first_token_ms=llm_meta.get("stream_first_token_ms"),
                estimated_cost_usd=llm_meta.get("estimated_cost_usd", 0.0),
                success=llm_meta.get("success", True),
                error=llm_meta.get("error"),
            )
        )

    # model_routing step (extracted from llm_meta)
    if llm_meta:
        acc.add_step(
            PipelineStep(
                step="model_routing",
                started_at=narration_start,
                duration_ms=0,
                input_summary={"request_type": "narration"},
                output_summary={
                    "model_id": llm_meta.get("model_id", "unknown"),
                    "model_tier": llm_meta.get("model_tier", "high"),
                },
                decision=(
                    f"{llm_meta.get('model_tier', 'high')} tier — "
                    f"{llm_meta.get('model_id', 'unknown')}"
                ),
            )
        )

    # narration step
    acc.add_step(
        PipelineStep(
            step="narration",
            started_at=narration_start,
            duration_ms=narration_duration_ms,
            input_summary={"snapshot_hash": hash(str(snapshot)) % 100000},
            output_summary={
                "narrative_length": len(full_narrative),
                "stream_duration_ms": llm_meta.get("latency_ms", narration_duration_ms),
            },
            decision=(
                f"Narrated — {len(full_narrative)} chars, "
                f"{llm_meta.get('latency_ms', narration_duration_ms)}ms stream"
            ),
        )
    )

    # gm_signals_parse step — gm_signals already parsed inside narrate_turn_stream;
    # we reconstruct diagnostics from what's available on the gm_signals object.
    # parse_gm_signals is called inside narrator.narrate_turn_stream and the
    # result is returned as gm_signals.  We can't get the raw diag from there,
    # so we infer fallback from llm_meta.success being False.
    if llm_meta.get("success", True) is False:
        gm_diag = {
            "fallback_used": True,
            "raw_input_truncated": "",
            "parse_error": llm_meta.get("error", "narration error"),
        }
    else:
        gm_diag = {
            "fallback_used": False,
            "raw_input_truncated": "",
            "parse_error": None,
        }

    if gm_diag["fallback_used"]:
        acc.add_warning(f"GMSignals parse fallback: {gm_diag['parse_error']}")

    acc.add_step(
        PipelineStep(
            step="gm_signals_parse",
            started_at=narration_start,
            duration_ms=0,
            input_summary={"raw_input_length": len(gm_diag.get("raw_input_truncated", ""))},
            output_summary={
                "fallback_used": gm_diag["fallback_used"],
                "has_scene_transition": gm_signals.scene_transition.type != "none",
                "npc_update_count": len(gm_signals.npc_updates),
                "has_location_change": gm_signals.location_change is not None,
                "has_time_progression": gm_signals.time_progression is not None,
                "suggested_actions_count": len(gm_signals.suggested_actions),
            },
            decision=(
                "Parse failed — safe default used"
                if gm_diag["fallback_used"]
                else (
                    f"Parsed — transition={gm_signals.scene_transition.type}, "
                    f"npc_updates={len(gm_signals.npc_updates)}, "
                    f"location_change={'yes' if gm_signals.location_change else 'no'}, "
                    f"time_progression={'yes' if gm_signals.time_progression else 'no'}, "
                    f"suggested={len(gm_signals.suggested_actions)}"
                )
            ),
        )
    )

    await manager.broadcast(
        campaign_id,
        {
            "event": "turn.narrative_end",
            "payload": {
                "turn_id": str(turn_id),
                "narrative": full_narrative,
                "mechanical_results": mechanical_results,
            },
        },
    )

    # WebSocket events for location_change and time_progression are emitted
    # after narrative_end and before suggested_actions (ADR-0019 §6).
    # The DB handlers run inside the session block below; we capture the
    # normalised values here so we can broadcast after the commit.
    _ws_location_change: str | None = None
    _ws_time_progression: str | None = None

    # Persist narrative and process GMSignals (own session)
    async with session_factory() as db:
        try:
            # Re-load campaign state (may have been updated by request-phase combat start)
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == campaign_id)
            )
            campaign_state = state_result.scalar_one_or_none()

            # -------------------------------------------------------------------
            # Step A: Process npc_updates BEFORE location_change (ADR-0019 §3)
            # -------------------------------------------------------------------
            npc_spawned = 0
            npc_updated = 0
            npc_update_start = datetime.now(UTC)
            npc_update_start_mono = time.monotonic()
            for npc_update in gm_signals.npc_updates:
                try:
                    await _process_npc_update(
                        update=npc_update,
                        campaign_id=campaign_id,
                        db=db,
                        sequence_number=sequence_number,
                    )
                    if npc_update.event == "spawn":
                        npc_spawned += 1
                    else:
                        npc_updated += 1
                except Exception as exc:
                    logger.error(
                        "Failed to process NPCUpdate %r for campaign %s: %s",
                        npc_update,
                        campaign_id,
                        exc,
                    )
            npc_update_duration_ms = int((time.monotonic() - npc_update_start_mono) * 1000)
            acc.add_step(
                PipelineStep(
                    step="npc_update_apply",
                    started_at=npc_update_start,
                    duration_ms=npc_update_duration_ms,
                    input_summary={"npc_update_count": len(gm_signals.npc_updates)},
                    output_summary={"spawned": npc_spawned, "updated": npc_updated},
                    decision=f"Spawned {npc_spawned}, updated {npc_updated} NPCs",
                )
            )

            # -------------------------------------------------------------------
            # Step B: Process location_change (ADR-0019 §3, step 2)
            # -------------------------------------------------------------------
            if gm_signals.location_change is not None and campaign_state is not None:
                lc_start = datetime.now(UTC)
                lc_start_mono = time.monotonic()
                try:
                    new_scene_id = normalise_scene_id(gm_signals.location_change.new_location)
                    campaign_state.current_scene_id = new_scene_id
                    campaign_state.updated_at = datetime.now(tz=UTC)

                    # Pre-assign scene_location for NPCs spawned this turn so
                    # they immediately reflect the new location (ADR-0019 §3 step 2).
                    # The C+ finalise step below will pick up any that remain NULL.
                    null_loc_result = await db.execute(
                        select(NPC).where(
                            NPC.campaign_id == campaign_id,
                            NPC.first_appeared_turn == sequence_number,
                            NPC.scene_location.is_(None),
                        )
                    )
                    auto_assigned = 0
                    for npc_to_assign in null_loc_result.scalars().all():
                        npc_to_assign.scene_location = new_scene_id
                        auto_assigned += 1

                    await db.flush()
                    _ws_location_change = new_scene_id
                    lc_duration_ms = int((time.monotonic() - lc_start_mono) * 1000)
                    acc.add_step(
                        PipelineStep(
                            step="location_change_apply",
                            started_at=lc_start,
                            duration_ms=lc_duration_ms,
                            input_summary={
                                "raw_location": gm_signals.location_change.new_location,
                            },
                            output_summary={
                                "new_scene_id": new_scene_id,
                                "npcs_auto_assigned": auto_assigned,
                            },
                            decision=(
                                gm_signals.location_change.reason or f"Location → {new_scene_id}"
                            ),
                        )
                    )
                    logger.info(
                        "Location changed to %r for campaign %s (%d NPCs auto-assigned)",
                        new_scene_id,
                        campaign_id,
                        auto_assigned,
                    )
                except ValueError as exc:
                    lc_duration_ms = int((time.monotonic() - lc_start_mono) * 1000)
                    acc.add_warning(f"location_change rejected — invalid scene identifier: {exc}")
                    acc.add_step(
                        PipelineStep(
                            step="location_change_apply",
                            started_at=lc_start,
                            duration_ms=lc_duration_ms,
                            input_summary={
                                "raw_location": gm_signals.location_change.new_location,
                            },
                            output_summary={"rejected": True},
                            decision=f"Rejected — {exc}",
                        )
                    )
                    logger.error(
                        "location_change for campaign %s rejected — invalid scene identifier: %s",
                        campaign_id,
                        exc,
                    )

            # -------------------------------------------------------------------
            # Step C: Process time_progression (ADR-0019 §3, step 3)
            # -------------------------------------------------------------------
            if gm_signals.time_progression is not None and campaign_state is not None:
                tp_start = datetime.now(UTC)
                tp_start_mono = time.monotonic()
                campaign_state.time_of_day = gm_signals.time_progression.new_time_of_day
                campaign_state.updated_at = datetime.now(tz=UTC)
                await db.flush()
                _ws_time_progression = gm_signals.time_progression.new_time_of_day
                tp_duration_ms = int((time.monotonic() - tp_start_mono) * 1000)
                acc.add_step(
                    PipelineStep(
                        step="time_progression_apply",
                        started_at=tp_start,
                        duration_ms=tp_duration_ms,
                        input_summary={
                            "new_time_of_day": gm_signals.time_progression.new_time_of_day,
                        },
                        output_summary={
                            "time_of_day": gm_signals.time_progression.new_time_of_day,
                        },
                        decision=(
                            gm_signals.time_progression.reason
                            or f"Time → {gm_signals.time_progression.new_time_of_day}"
                        ),
                    )
                )
                logger.info(
                    "Time of day advanced to %r for campaign %s",
                    gm_signals.time_progression.new_time_of_day,
                    campaign_id,
                )

            # -------------------------------------------------------------------
            # Step C+: Finalise NPC scene_location for NPCs spawned this turn
            # (ADR-0019, Package C).  Any NPCs spawned in step A that still
            # have scene_location = NULL are assigned the final current_scene_id
            # (which may have been updated by the location_change handler above).
            # -------------------------------------------------------------------
            if campaign_state is not None and npc_spawned > 0:
                final_scene_id = campaign_state.current_scene_id
                if final_scene_id:
                    null_loc_result = await db.execute(
                        select(NPC).where(
                            NPC.campaign_id == campaign_id,
                            NPC.first_appeared_turn == sequence_number,
                            NPC.scene_location.is_(None),
                        )
                    )
                    for npc_to_finalise in null_loc_result.scalars().all():
                        npc_to_finalise.scene_location = final_scene_id
                    await db.flush()

            # -------------------------------------------------------------------
            # Step D: Process scene_transition (ADR-0019 §3, step 4)
            # -------------------------------------------------------------------
            current_mode = str(world_state.get("mode", "exploration"))

            # campaign_state was loaded at the top of this block.
            # Check whether the Rules Engine ended combat (all NPCs at 0 HP).
            # For M1 we detect this via the world_state "engine_combat_end" flag
            # that submit_turn may have set.  If not set, we rely on Narrator signals.
            engine_combat_end = bool(world_state.get("engine_combat_end", False))

            scene_transition_start = datetime.now(UTC)
            scene_transition_start_mono = time.monotonic()
            scene_transition_applied = False

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
                logger.debug("Combat ended (Engine authority) for campaign %s", campaign_id)
                scene_transition_applied = True

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
                scene_transition_applied = True

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
                logger.debug("Combat ended (Narrator signal) for campaign %s", campaign_id)
                scene_transition_applied = True

            if gm_signals.scene_transition.type != "none" or scene_transition_applied:
                scene_transition_duration_ms = int(
                    (time.monotonic() - scene_transition_start_mono) * 1000
                )
                acc.add_step(
                    PipelineStep(
                        step="scene_transition_apply",
                        started_at=scene_transition_start,
                        duration_ms=scene_transition_duration_ms,
                        input_summary={
                            "transition_type": gm_signals.scene_transition.type,
                        },
                        output_summary={
                            "mode_change": str(gm_signals.scene_transition.type),
                            "applied": scene_transition_applied,
                        },
                        decision=(
                            gm_signals.scene_transition.reason or gm_signals.scene_transition.type
                        ),
                    )
                )

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
                summary_compress_start = datetime.now(UTC)
                summary_compress_start_mono = time.monotonic()
                new_summary, trim_meta = trim_summary(new_summary)
                summary_compress_duration_ms = int(
                    (time.monotonic() - summary_compress_start_mono) * 1000
                )
                acc.add_step(
                    PipelineStep(
                        step="summary_compression",
                        started_at=summary_compress_start,
                        duration_ms=summary_compress_duration_ms,
                        input_summary={"before_tokens": trim_meta.get("before_tokens", 0)},
                        output_summary={"after_tokens": trim_meta.get("after_tokens", 0)},
                        decision=(
                            f"Summary {trim_meta.get('before_tokens', 0)}"
                            f"→{trim_meta.get('after_tokens', 0)} tokens"
                        ),
                    )
                )
            except Exception as exc:
                logger.warning("Summary update failed: %s — keeping previous summary", exc)
                summary_compress_start = datetime.now(UTC)
                summary_compress_start_mono = time.monotonic()
                new_summary, trim_meta = trim_summary(current_summary)
                summary_compress_duration_ms = int(
                    (time.monotonic() - summary_compress_start_mono) * 1000
                )
                acc.add_step(
                    PipelineStep(
                        step="summary_compression",
                        started_at=summary_compress_start,
                        duration_ms=summary_compress_duration_ms,
                        input_summary={"before_tokens": trim_meta.get("before_tokens", 0)},
                        output_summary={"after_tokens": trim_meta.get("after_tokens", 0)},
                        decision=(
                            f"Summary {trim_meta.get('before_tokens', 0)}"
                            f"→{trim_meta.get('after_tokens', 0)} tokens (fallback)"
                        ),
                    )
                )

            if campaign_state is not None:
                campaign_state.rolling_summary = new_summary
                campaign_state.updated_at = datetime.now(tz=UTC)

            camp = await db.get(Campaign, campaign_id)
            if camp is not None:
                camp.last_played_at = datetime.now(tz=UTC)

            # -------------------------------------------------------------------
            # Step E: Finalize event_log and persist atomically with the turn
            # -------------------------------------------------------------------
            event_log_obj = acc.finalize()
            event_log_dict = turn_event_log_to_dict(event_log_obj)

            json_bytes = json.dumps(event_log_dict).encode()
            if len(json_bytes) > 20480:
                logger.warning(
                    "tavern.api.turns: event_log size %d bytes exceeds 20 KB threshold on turn %s",
                    len(json_bytes),
                    str(turn_id),
                )

            if turn is not None:
                turn.event_log = event_log_dict

            await db.commit()

        except Exception as exc:
            logger.error("DB persist failed for turn %s: %s", turn_id, exc)
            return

    # Emit location_change and time_progression events after narrative_end,
    # before suggested_actions (ADR-0019 §6 emission sequence)
    if _ws_location_change is not None:
        await manager.broadcast(
            campaign_id,
            {
                "event": "turn.location_change",
                "payload": {
                    "turn_id": str(turn_id),
                    "campaign_id": str(campaign_id),
                    "new_location": _ws_location_change,
                },
            },
        )

    if _ws_time_progression is not None:
        await manager.broadcast(
            campaign_id,
            {
                "event": "turn.time_progression",
                "payload": {
                    "turn_id": str(turn_id),
                    "campaign_id": str(campaign_id),
                    "new_time_of_day": _ws_time_progression,
                },
            },
        )

    # Emit suggested actions after location/time events (ADR-0019 §6, ADR-0015)
    logger.debug(
        "GMSignals suggested_actions after parsing: %r (turn_id=%s)",
        gm_signals.suggested_actions,
        turn_id,
    )
    if gm_signals.suggested_actions:
        await manager.broadcast(
            campaign_id,
            {
                "event": "turn.suggested_actions",
                "payload": {
                    "turn_id": str(turn_id),
                    "character_id": str(character_id),
                    "suggestions": gm_signals.suggested_actions,
                },
            },
        )

    # suggested_actions_emit step
    suggestion_count = len(gm_signals.suggested_actions)
    acc.add_step(
        PipelineStep(
            step="suggested_actions_emit",
            started_at=datetime.now(UTC),
            duration_ms=0,
            input_summary={"raw_count": suggestion_count},
            output_summary={"emitted": suggestion_count},
            decision=f"{suggestion_count} suggestions emitted",
        )
    )

    # Emit turn.event_log WebSocket event (after DB commit)
    pipeline_duration_ms = int(
        (event_log_obj.pipeline_finished_at - event_log_obj.pipeline_started_at).total_seconds()
        * 1000
    )
    await manager.broadcast(
        campaign_id,
        {
            "type": "turn.event_log",
            "payload": {
                "turn_id": str(turn_id),
                "sequence_number": sequence_number,
                "pipeline_duration_ms": pipeline_duration_ms,
                "steps": event_log_dict["steps"],
                "llm_calls": event_log_dict["llm_calls"],
                "warnings": event_log_dict["warnings"],
                "errors": event_log_dict["errors"],
                "admin_only": True,
            },
        },
    )

    # Emit session.telemetry every 10 turns
    if sequence_number % 10 == 0:
        await _emit_session_telemetry(
            campaign_id=campaign_id,
            session_factory=session_factory,
        )


async def _emit_session_telemetry(
    *,
    campaign_id: uuid.UUID,
    session_factory: async_sessionmaker,
) -> None:
    """Query session telemetry from recent turns and broadcast session.telemetry."""
    from tavern.api.ws import manager

    try:
        async with session_factory() as db:
            query_start = time.monotonic()
            # Find the open session for this campaign
            session_result = await db.execute(
                select(Session).where(
                    Session.campaign_id == campaign_id,
                    Session.ended_at.is_(None),
                )
            )
            session = session_result.scalar_one_or_none()
            if session is None:
                return

            # Fetch all turns with event_log for this session
            turns_result = await db.execute(
                select(Turn).where(
                    Turn.session_id == session.id,
                    Turn.event_log.isnot(None),
                )
            )
            turns_with_logs = turns_result.scalars().all()
            elapsed_ms = (time.monotonic() - query_start) * 1000

            if elapsed_ms > 200:
                logger.warning(
                    "tavern.api.turns: session telemetry query took %.0f ms for session %s",
                    elapsed_ms,
                    str(session.id),
                )

            telemetry = _compute_session_telemetry(str(session.id), list(turns_with_logs))
            await manager.broadcast(
                campaign_id,
                {"type": "session.telemetry", "payload": telemetry},
            )
    except Exception as exc:
        logger.warning("Failed to emit session.telemetry for campaign %s: %s", campaign_id, exc)


def _compute_session_telemetry(session_id: str, turns_with_logs: list) -> dict:
    """Compute session telemetry aggregates from a list of Turn records."""
    turns_processed = len(turns_with_logs)
    total_cost_usd = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    narration_latencies: list[int] = []
    pipeline_durations: list[int] = []
    classifier_invocations = 0
    classifier_low_confidence = 0
    gm_signals_parse_failures = 0
    model_tier_distribution: dict[str, int] = {}

    for t in turns_with_logs:
        if not t.event_log:
            continue
        log = t.event_log

        for call in log.get("llm_calls", []):
            total_cost_usd += call.get("estimated_cost_usd", 0.0)
            total_input_tokens += call.get("input_tokens", 0)
            total_output_tokens += call.get("output_tokens", 0)
            total_cache_read_tokens += call.get("cache_read_tokens", 0)
            call_type = call.get("call_type", "")
            tier = call.get("model_tier", "high")
            if call_type == "classification":
                classifier_invocations += 1
            model_tier_distribution[tier] = model_tier_distribution.get(tier, 0) + 1

        for step in log.get("steps", []):
            step_name = step.get("step", "")
            if step_name == "narration":
                out = step.get("output_summary", {})
                dur = out.get("stream_duration_ms")
                if dur is not None:
                    narration_latencies.append(int(dur))
            if step_name == "gm_signals_parse":
                out = step.get("output_summary", {})
                if out.get("fallback_used", False):
                    gm_signals_parse_failures += 1

        # Pipeline duration from started_at to finished_at in the log
        started = log.get("pipeline_started_at")
        finished = log.get("pipeline_finished_at")
        if started and finished:
            try:
                from datetime import datetime as _dt

                s = _dt.fromisoformat(started)
                f = _dt.fromisoformat(finished)
                pipeline_durations.append(int((f - s).total_seconds() * 1000))
            except Exception:
                pass

    # Cache hit rate = cache_read_tokens / (total_input_tokens + cache_read_tokens)
    cache_denom = total_input_tokens + total_cache_read_tokens
    cache_hit_rate = total_cache_read_tokens / cache_denom if cache_denom > 0 else 0.0

    avg_narration_latency_ms = (
        int(sum(narration_latencies) / len(narration_latencies)) if narration_latencies else 0
    )
    avg_pipeline_duration_ms = (
        int(sum(pipeline_durations) / len(pipeline_durations)) if pipeline_durations else 0
    )

    return {
        "session_id": session_id,
        "turns_processed": turns_processed,
        "total_cost_usd": round(total_cost_usd, 6),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "cache_hit_rate": round(cache_hit_rate, 4),
        "avg_narration_latency_ms": avg_narration_latency_ms,
        "avg_pipeline_duration_ms": avg_pipeline_duration_ms,
        "classifier_invocations": classifier_invocations,
        "classifier_low_confidence_count": classifier_low_confidence,
        "gm_signals_parse_failures": gm_signals_parse_failures,
        "model_tier_distribution": model_tier_distribution,
        "admin_only": True,
    }


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

    # Pre-background pipeline steps collected here and forwarded to the background task
    pre_steps: list[PipelineStep] = []
    pre_llm_calls: list[LLMCallRecord] = []

    # 4. Run Rules Engine: classify action → resolve mechanics → update character state
    action_text = body.action

    # action_analysis step
    analysis_start = datetime.now(UTC)
    analysis_start_mono = time.monotonic()
    try:
        analysis = analyze_action(action_text, _character_to_caster_state(character))
        analysis_duration_ms = int((time.monotonic() - analysis_start_mono) * 1000)
        pre_steps.append(
            PipelineStep(
                step="action_analysis",
                started_at=analysis_start,
                duration_ms=analysis_duration_ms,
                input_summary={
                    "action_text_length": len(action_text),
                    "action_preview": action_text[:80],
                },
                output_summary={
                    "category": analysis.category.value,
                    "matched_keywords": analysis.matched_keywords,
                },
                decision=analysis.decision_summary,
            )
        )
    except Exception as exc:
        logger.warning("Rules Engine error for turn (campaign=%s): %s", campaign_id, exc)
        # Create a minimal analysis for the error case
        analysis = ActionAnalysis(
            category=ActionCategory.UNKNOWN,
            raw_action=action_text,
        )
        analysis_duration_ms = int((time.monotonic() - analysis_start_mono) * 1000)
        pre_steps.append(
            PipelineStep(
                step="action_analysis",
                started_at=analysis_start,
                duration_ms=analysis_duration_ms,
                input_summary={
                    "action_text_length": len(action_text),
                    "action_preview": action_text[:80],
                },
                output_summary={"category": "unknown", "matched_keywords": None},
                decision=f"Error: {exc}",
            )
        )

    try:
        rules_result, char_update, mechanical_results = await _resolve_action(
            analysis, character, campaign_id
        )
    except Exception as exc:
        logger.warning("Rules Engine error for turn (campaign=%s): %s", campaign_id, exc)
        rules_result, char_update, mechanical_results = None, None, None

    # 5. Determine sequence number and build snapshot
    sequence_number = campaign.state.turn_count + 1

    turn_ctx = TurnContext(player_action=body.action, rules_result=rules_result)

    # snapshot_build step
    snapshot_start = datetime.now(UTC)
    snapshot_start_mono = time.monotonic()
    snapshot = await build_snapshot(
        campaign_id=campaign_id,
        current_turn=turn_ctx,
        db_session=db,
    )
    snapshot_duration_ms = int((time.monotonic() - snapshot_start_mono) * 1000)
    pre_steps.append(
        PipelineStep(
            step="snapshot_build",
            started_at=snapshot_start,
            duration_ms=snapshot_duration_ms,
            input_summary={"session_mode": snapshot.session_mode},
            output_summary={"estimated_token_count": snapshot.estimated_token_count},
            decision=(
                f"{snapshot.estimated_token_count} tokens"
                if snapshot.estimated_token_count
                else None
            ),
        )
    )

    # 6. [Exploration mode only] CombatClassifier pre-narration check (Flow B)
    current_mode = str((campaign.state.world_state or {}).get("mode", "exploration"))
    world_state_copy = dict(campaign.state.world_state or {})

    if current_mode == "exploration":
        try:
            from tavern.dm.combat_classifier import CombatClassifier

            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            classifier = CombatClassifier(api_key=api_key)
            classify_start = datetime.now(UTC)
            classify_start_mono = time.monotonic()
            classification, classifier_meta = await classifier.classify(body.action, snapshot)
            classify_duration_ms = int((time.monotonic() - classify_start_mono) * 1000)
            logger.debug(
                "CombatClassifier result (campaign=%s): combat_starts=%s confidence=%s reason=%s",
                campaign_id,
                classification.combat_starts,
                classification.confidence,
                classification.reason,
            )

            pre_steps.append(
                PipelineStep(
                    step="combat_classification",
                    started_at=classify_start,
                    duration_ms=classify_duration_ms,
                    input_summary={
                        "action_text_length": len(body.action),
                        "session_mode": snapshot.session_mode,
                    },
                    output_summary={
                        "combat_starts": classification.combat_starts,
                        "confidence": classification.confidence,
                        "combatants": classification.combatants,
                    },
                    decision=classification.reason,
                )
            )
            pre_llm_calls.append(
                LLMCallRecord(
                    call_type=classifier_meta.get("call_type", "classification"),
                    model_id=classifier_meta.get("model_id", "unknown"),
                    model_tier=classifier_meta.get("model_tier", "low"),
                    input_tokens=classifier_meta.get("input_tokens", 0),
                    output_tokens=classifier_meta.get("output_tokens", 0),
                    cache_read_tokens=classifier_meta.get("cache_read_tokens", 0),
                    cache_creation_tokens=classifier_meta.get("cache_creation_tokens", 0),
                    latency_ms=classifier_meta.get("latency_ms", classify_duration_ms),
                    stream_first_token_ms=classifier_meta.get("stream_first_token_ms"),
                    estimated_cost_usd=classifier_meta.get("estimated_cost_usd", 0.0),
                    success=classifier_meta.get("success", True),
                    error=classifier_meta.get("error"),
                )
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
        mechanical_results=mechanical_results,
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
        character_id=body.character_id,
        snapshot=snapshot,
        narrator=narrator,
        character_name=character.name,
        sequence_number=sequence_number,
        current_summary=campaign_state.rolling_summary,
        session_factory=session_factory,
        world_state=world_state_copy,
        mechanical_results=mechanical_results,
        pre_steps=pre_steps,
        pre_llm_calls=pre_llm_calls,
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
