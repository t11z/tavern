"""Turn submission and retrieval endpoints.

Turn processing pipeline (Phase 5b — streaming via WebSocket):
  1. Validate campaign is Active with an open session
  2. Validate character belongs to the campaign
  3. Build state snapshot (Context Builder) — uses request DB session
  4. Create pending Turn record (narrative_response=None)
  5. Return 202 Accepted with turn_id
  6. Background task: stream narrative → broadcast WebSocket events
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
from tavern.api.schemas import TurnCreateRequest, TurnListItem, TurnListResponse, TurnSubmitResponse
from tavern.dm.context_builder import TurnContext, build_snapshot
from tavern.dm.narrator import Narrator
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.session import Session
from tavern.models.turn import Turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["turns"])

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

            # Update rolling summary
            turn_line = f"Turn {sequence_number}: {character_name} — action completed."
            try:
                new_summary = await narrator.update_summary(
                    recent_turns=[turn_line],
                    current_summary=current_summary,
                )
            except Exception as exc:
                logger.warning("Summary update failed: %s — keeping previous summary", exc)
                new_summary = current_summary

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

    # 4. Determine sequence number and build snapshot
    sequence_number = campaign.state.turn_count + 1

    turn_ctx = TurnContext(player_action=body.action, rules_result=None)
    snapshot = await build_snapshot(
        campaign_id=campaign_id,
        current_turn=turn_ctx,
        db_session=db,
    )

    # 5. Create pending Turn record (ADR-0004: atomic, autosave every turn)
    turn = Turn(
        session_id=session.id,
        character_id=body.character_id,
        sequence_number=sequence_number,
        player_action=body.action,
        rules_result=None,
        narrative_response=None,  # Set by background task when streaming completes
    )
    db.add(turn)

    campaign_state: CampaignState = campaign.state
    campaign_state.turn_count = sequence_number
    campaign.last_played_at = datetime.now(tz=UTC)

    await db.commit()
    await db.refresh(turn)

    # 6. Schedule streaming as background task
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
        narrative_response=turn.narrative_response,
        created_at=turn.created_at,
    )
