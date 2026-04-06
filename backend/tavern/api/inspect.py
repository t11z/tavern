"""Observability inspection endpoints — ADR-0018.

Provides REST access to per-turn event logs and per-session telemetry.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.api.dependencies import get_db_session
from tavern.api.errors import not_found
from tavern.api.turns import _compute_session_telemetry
from tavern.models.campaign import Campaign
from tavern.models.session import Session
from tavern.models.turn import Turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["inspect"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/{campaign_id}/turns/{turn_id}/event_log")
async def get_turn_event_log(
    campaign_id: uuid.UUID,
    turn_id: uuid.UUID,
    db: DbSession,
) -> dict:
    """Return the event_log JSONB for a specific turn.

    Validates that the turn belongs to the given campaign.
    Returns 404 if the campaign or turn does not exist, or if no event log
    has been recorded yet (narrative processing not complete).
    """
    # Validate campaign exists
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if campaign_result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    # Fetch turn, enforcing campaign membership via Session join
    turn_result = await db.execute(
        select(Turn)
        .join(Session, Turn.session_id == Session.id)
        .where(
            Turn.id == turn_id,
            Session.campaign_id == campaign_id,
        )
    )
    turn = turn_result.scalar_one_or_none()
    if turn is None:
        raise not_found("turn", turn_id)

    if turn.event_log is None:
        raise not_found("event_log", turn_id)

    return {
        "turn_id": str(turn_id),
        "event_log": turn.event_log,
    }


@router.get("/{campaign_id}/sessions/{session_id}/telemetry")
async def get_session_telemetry(
    campaign_id: uuid.UUID,
    session_id: uuid.UUID,
    db: DbSession,
) -> dict:
    """Compute and return session telemetry aggregated from turn event logs.

    Logs a warning if the query takes more than 200 ms.
    Returns 404 if the campaign or session does not exist.
    """
    # Validate campaign exists
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if campaign_result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    # Validate session belongs to campaign
    session_result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.campaign_id == campaign_id,
        )
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        raise not_found("session", session_id)

    # Fetch turns with event_log, timing the query
    query_start = time.monotonic()
    turns_result = await db.execute(
        select(Turn).where(
            Turn.session_id == session_id,
            Turn.event_log.isnot(None),
        )
    )
    turns_with_logs = turns_result.scalars().all()
    elapsed_ms = (time.monotonic() - query_start) * 1000

    if elapsed_ms > 200:
        logger.warning(
            "Session telemetry query took %.0f ms for session %s",
            elapsed_ms,
            str(session_id),
        )

    telemetry = _compute_session_telemetry(str(session_id), list(turns_with_logs))
    return telemetry
