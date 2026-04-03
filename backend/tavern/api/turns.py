"""Turn submission and retrieval endpoints.

Turn processing pipeline (Phase 5a — no Rules Engine integration yet):
  1. Validate campaign is Active with an open session
  2. Validate character belongs to the campaign
  3. Build state snapshot (Context Builder)
  4. Get narration (Narrator)
  5. Persist Turn record
  6. Update CampaignState rolling summary
  7. Return turn response
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tavern.api.dependencies import get_db_session, get_narrator
from tavern.api.errors import bad_request, conflict, not_found
from tavern.api.schemas import TurnCreateRequest, TurnListItem, TurnListResponse, TurnResponse
from tavern.dm.context_builder import TurnContext, build_snapshot
from tavern.dm.narrator import Narrator
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.session import Session
from tavern.models.turn import Turn

router = APIRouter(prefix="/campaigns", tags=["turns"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
NarratorDep = Annotated[Narrator, Depends(get_narrator)]


@router.post(
    "/{campaign_id}/turns",
    status_code=201,
    response_model=TurnResponse,
)
async def submit_turn(
    campaign_id: uuid.UUID,
    body: TurnCreateRequest,
    db: DbSession,
    narrator: NarratorDep,
) -> TurnResponse:
    """Submit a player action and receive a narrative response.

    Validates campaign state, builds a snapshot, calls the Narrator,
    persists the turn, and updates the rolling summary.
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

    # 4. Determine sequence number
    sequence_number = campaign.state.turn_count + 1

    # 5. Build state snapshot and get narration
    turn_ctx = TurnContext(
        player_action=body.action,
        rules_result=None,  # Phase 6: Rules Engine integration
    )
    snapshot = await build_snapshot(
        campaign_id=campaign_id,
        current_turn=turn_ctx,
        db_session=db,
    )
    narrative = await narrator.narrate_turn(snapshot)

    # 6. Persist the Turn record (ADR-0004: atomic commit)
    turn = Turn(
        session_id=session.id,
        character_id=body.character_id,
        sequence_number=sequence_number,
        player_action=body.action,
        rules_result=None,
        narrative_response=narrative,
    )
    db.add(turn)

    # 7. Update CampaignState (ADR-0004: autosave after every turn)
    turn_summary_line = f"Turn {sequence_number}: {character.name} — {body.action}"
    new_summary = await narrator.update_summary(
        recent_turns=[turn_summary_line],
        current_summary=campaign.state.rolling_summary,
    )

    campaign_state: CampaignState = campaign.state
    campaign_state.rolling_summary = new_summary
    campaign_state.turn_count = sequence_number
    campaign_state.updated_at = datetime.now(tz=UTC)

    campaign.last_played_at = datetime.now(tz=UTC)

    await db.commit()
    await db.refresh(turn)

    return TurnResponse(
        turn_id=turn.id,
        sequence_number=turn.sequence_number,
        narrative=narrative,
    )


@router.get("/{campaign_id}/turns", response_model=TurnListResponse)
async def list_turns(
    campaign_id: uuid.UUID,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TurnListResponse:
    """List turns for the campaign, paginated, in sequence order."""
    # Verify campaign exists
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    # Count total turns across all sessions for this campaign
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
