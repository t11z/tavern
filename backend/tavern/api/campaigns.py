"""Campaign lifecycle endpoints.

State machine (ADR-0004):
  paused ──(start session)──> active ──(end session)──> paused
  any    ──(update)──> same status (name / status changes only)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tavern.api.dependencies import get_db_session, get_narrator
from tavern.api.errors import bad_request, conflict, not_found
from tavern.api.schemas import (
    CampaignCreateRequest,
    CampaignDetailResponse,
    CampaignResponse,
    CampaignStateResponse,
    CampaignUpdateRequest,
    SessionResponse,
)
from tavern.dm.narrator import Narrator
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.session import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# ---------------------------------------------------------------------------
# Tone presets → world_seed / dm_persona defaults
# ---------------------------------------------------------------------------

_TONE_PRESETS: dict[str, dict[str, str | None]] = {
    "dark_gritty": {
        "world_seed": (
            "A harsh world of moral ambiguity where survival demands hard choices "
            "and victory comes at a price."
        ),
        "dm_persona": (
            "You are a grim, grounded Dungeon Master. Emphasise consequence, danger, "
            "and moral complexity. Victories are costly; the world does not bend to heroes."
        ),
    },
    "lighthearted": {
        "world_seed": "A vibrant world where adventure beckons around every corner.",
        "dm_persona": (
            "You are a warm, enthusiastic Dungeon Master who celebrates creativity, "
            "humour, and heroic moments. Keep the tone playful without sacrificing stakes."
        ),
    },
    "classic_fantasy": {
        "world_seed": "A world of ancient magic, forgotten kingdoms, and quests of destiny.",
        "dm_persona": None,  # Use the default persona from context_builder.py
    },
    "epic_high_fantasy": {
        "world_seed": "A world of gods, chosen heroes, and cataclysmic threats.",
        "dm_persona": (
            "You are a dramatic, sweeping Dungeon Master who narrates with mythic scale. "
            "Every action feels significant; characters are the pivots of fate."
        ),
    },
    "mystery_intrigue": {
        "world_seed": "A world of hidden agendas, unreliable allies, and buried secrets.",
        "dm_persona": (
            "You are a subtle, atmospheric Dungeon Master who rewards careful observation "
            "and the right questions."
        ),
    },
}

_DEFAULT_WORLD_STATE: dict = {
    "location": "Unknown",
    "npcs": [],
    "environment": "",
    "threats": [],
    "time_of_day": "morning",
}


def _tone_preset(tone: str) -> dict[str, str | None]:
    return _TONE_PRESETS.get(tone, _TONE_PRESETS["classic_fantasy"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _campaign_to_response(campaign: Campaign) -> CampaignResponse:
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        created_at=campaign.created_at,
        last_played_at=campaign.last_played_at,
    )


def _campaign_to_detail(campaign: Campaign) -> CampaignDetailResponse:
    state_resp: CampaignStateResponse | None = None
    if campaign.state is not None:
        s = campaign.state
        state_resp = CampaignStateResponse(
            rolling_summary=s.rolling_summary,
            scene_context=s.scene_context,
            world_state=s.world_state,
            turn_count=s.turn_count,
            updated_at=s.updated_at,
        )
    return CampaignDetailResponse(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        created_at=campaign.created_at,
        last_played_at=campaign.last_played_at,
        world_seed=campaign.world_seed,
        dm_persona=campaign.dm_persona,
        state=state_resp,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
NarratorDep = Annotated[Narrator, Depends(get_narrator)]

_FALLBACK_SCENE_CONTEXT = "Your adventure is about to begin."


@router.post("", status_code=201, response_model=CampaignDetailResponse)
async def create_campaign(
    body: CampaignCreateRequest,
    db: DbSession,
    narrator: NarratorDep,
) -> CampaignDetailResponse:
    """Create a new campaign in Paused status.

    Calls Claude (Haiku) to generate a campaign brief and opening scene.
    If the call fails, the campaign is still created with static fallback text.
    """
    preset = _tone_preset(body.tone)
    world_state = dict(_DEFAULT_WORLD_STATE)
    world_state["tone"] = body.tone

    # Fallback values — overwritten on successful brief generation
    world_seed: str = preset["world_seed"] or ""
    scene_context: str = _FALLBACK_SCENE_CONTEXT

    # Attempt to generate a Claude-authored brief and opening scene (Haiku, non-blocking failure)
    try:
        brief = await narrator.generate_campaign_brief(name=body.name, tone=body.tone)
        world_seed = brief["campaign_brief"]
        scene_context = brief["opening_scene"]
        world_state["location"] = brief["location"]
        world_state["environment"] = brief["environment"]
        world_state["time_of_day"] = brief["time_of_day"]
    except Exception as exc:
        logger.warning(
            "Campaign brief generation failed for %r (tone=%r) — using fallback: %s",
            body.name,
            body.tone,
            exc,
        )

    campaign = Campaign(
        name=body.name,
        status="paused",
        world_seed=world_seed,
        dm_persona=preset["dm_persona"],
    )
    db.add(campaign)
    await db.flush()  # Populate campaign.id without committing

    state = CampaignState(
        campaign_id=campaign.id,
        rolling_summary="",
        scene_context=scene_context,
        world_state=world_state,
        turn_count=0,
    )
    db.add(state)
    await db.commit()
    await db.refresh(campaign)
    await db.refresh(state)

    campaign.state = state  # Attach for serialisation
    return _campaign_to_detail(campaign)


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(db: DbSession) -> list[CampaignResponse]:
    """List all campaigns (summary, no state)."""
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    campaigns = result.scalars().all()
    return [_campaign_to_response(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: uuid.UUID,
    db: DbSession,
) -> CampaignDetailResponse:
    """Get campaign details including current state."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.state))
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)
    return _campaign_to_detail(campaign)


@router.patch("/{campaign_id}", response_model=CampaignDetailResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdateRequest,
    db: DbSession,
) -> CampaignDetailResponse:
    """Update campaign name or status."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.state))
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)

    if body.name is not None:
        campaign.name = body.name
    if body.status is not None:
        valid_statuses = {"active", "paused", "concluded", "abandoned"}
        if body.status not in valid_statuses:
            raise bad_request(
                "invalid_status",
                f"Status must be one of: {', '.join(sorted(valid_statuses))}",
            )
        campaign.status = body.status

    await db.commit()
    await db.refresh(campaign)
    return _campaign_to_detail(campaign)


@router.post("/{campaign_id}/sessions", status_code=201, response_model=SessionResponse)
async def start_session(
    campaign_id: uuid.UUID,
    db: DbSession,
) -> SessionResponse:
    """Start a new session, transitioning the campaign from Paused to Active."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)

    if campaign.status == "active":
        raise conflict("session_already_active", "Campaign already has an active session")
    if campaign.status not in {"paused"}:
        raise bad_request(
            "invalid_campaign_status",
            f"Cannot start a session on a {campaign.status} campaign",
        )

    # Check for existing open session
    open_result = await db.execute(
        select(Session).where(
            Session.campaign_id == campaign_id,
            Session.ended_at.is_(None),
        )
    )
    if open_result.scalar_one_or_none() is not None:
        raise conflict("session_already_active", "Campaign already has an open session")

    session = Session(campaign_id=campaign_id)
    db.add(session)

    campaign.status = "active"
    campaign.last_played_at = datetime.now(tz=UTC)

    await db.commit()
    await db.refresh(session)

    return SessionResponse(
        id=session.id,
        campaign_id=session.campaign_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        end_reason=session.end_reason,
    )


@router.post("/{campaign_id}/sessions/end", response_model=SessionResponse)
async def end_session(
    campaign_id: uuid.UUID,
    db: DbSession,
) -> SessionResponse:
    """End the current session, transitioning the campaign from Active to Paused."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)

    if campaign.status != "active":
        raise conflict(
            "session_not_active",
            f"Campaign is {campaign.status}, not active — no session to end",
        )

    open_result = await db.execute(
        select(Session).where(
            Session.campaign_id == campaign_id,
            Session.ended_at.is_(None),
        )
    )
    session = open_result.scalar_one_or_none()
    if session is None:
        raise conflict("no_open_session", "No open session found for this campaign")

    session.ended_at = datetime.now(tz=UTC)
    session.end_reason = "player_ended"
    campaign.status = "paused"

    await db.commit()
    await db.refresh(session)

    return SessionResponse(
        id=session.id,
        campaign_id=session.campaign_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        end_reason=session.end_reason,
    )
