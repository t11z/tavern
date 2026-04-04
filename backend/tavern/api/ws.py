"""WebSocket endpoint for real-time campaign events.

Event model (ADR-0005):
  Client connects → server sends session.state
  Turn submitted via REST → server streams turn.narrative_* events

All events follow the shape: {"event": "<type>", "payload": {...}}

Sequence numbers for WebSocket events must be monotonically increasing
per campaign (ADR-0007). The Turn.sequence_number serves as the
canonical event sequence — clients use it to detect missed events
and recover via REST GET /api/campaigns/{id}/turns.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tavern.api.dependencies import get_db_session
from tavern.models.campaign import Campaign
from tavern.models.session import Session
from tavern.models.turn import Turn

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manage WebSocket connections grouped by campaign_id.

    Connections are stored as a plain dict of sets. No locks are needed
    because FastAPI/anyio is single-threaded within an event loop — all
    coroutines run serially.
    """

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, campaign_id: uuid.UUID) -> None:
        await websocket.accept()
        self._connections[campaign_id].add(websocket)
        count = len(self._connections[campaign_id])
        logger.debug("WS connect: campaign=%s total=%d", campaign_id, count)

    def disconnect(self, websocket: WebSocket, campaign_id: uuid.UUID) -> None:
        self._connections[campaign_id].discard(websocket)
        if not self._connections[campaign_id]:
            del self._connections[campaign_id]
        logger.debug("WS disconnect: campaign=%s", campaign_id)

    async def broadcast(self, campaign_id: uuid.UUID, event: dict) -> None:
        """Send an event to all connections for a campaign.

        Dead connections are silently removed — a disconnect is not an error.
        """
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(campaign_id, [])):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, campaign_id)

    def connection_count(self, campaign_id: uuid.UUID) -> int:
        return len(self._connections.get(campaign_id, []))


# Module-level singleton — shared across all requests in the same process.
manager = ConnectionManager()

# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


router = APIRouter(tags=["websocket"])


@router.websocket("/campaigns/{campaign_id}/ws")
async def campaign_ws(
    websocket: WebSocket,
    campaign_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Campaign WebSocket connection.

    Lifecycle:
    1. Accept connection and validate campaign exists.
    2. Send current session.state snapshot.
    3. Keep connection open; the server pushes events as turns are submitted.
    4. On disconnect, clean up gracefully.
    """
    # Validate campaign exists
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.state), selectinload(Campaign.characters))
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        await websocket.close(code=4004, reason="Campaign not found")
        return

    await manager.connect(websocket, campaign_id)

    try:
        # Send initial session.state
        await _send_session_state(websocket, campaign, db)

        # Keep the connection alive waiting for the client to disconnect
        # (events are pushed from the turn submission pipeline)
        try:
            while True:
                # We don't process incoming messages (Phase 5b is server-push only).
                # Calling receive_text keeps the loop alive and detects disconnects.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

    finally:
        manager.disconnect(websocket, campaign_id)


# ---------------------------------------------------------------------------
# Initial state helpers
# ---------------------------------------------------------------------------


async def _send_session_state(
    websocket: WebSocket,
    campaign: Campaign,
    db: AsyncSession,
) -> None:
    """Send the session.state event with the current game snapshot."""
    scene: dict = {}
    if campaign.state:
        ws_data = campaign.state.world_state or {}
        scene = {
            "location": ws_data.get("location", ""),
            "time_of_day": ws_data.get("time_of_day", ""),
            "environment": ws_data.get("environment", ""),
            "npcs": ws_data.get("npcs", []),
            "threats": ws_data.get("threats", []),
            "description": campaign.state.scene_context,
        }

    characters = [
        {
            "id": str(c.id),
            "name": c.name,
            "class_name": c.class_name,
            "level": c.level,
            "hp": c.hp,
            "max_hp": c.max_hp,
            "ac": c.ac,
            "spell_slots": c.spell_slots,
            "features": c.features,
        }
        for c in campaign.characters
    ]

    # Fetch the last 20 turns for context
    turns_result = await db.execute(
        select(Turn)
        .join(Session, Turn.session_id == Session.id)
        .where(Session.campaign_id == campaign.id)
        .order_by(Turn.sequence_number.desc())
        .limit(20)
    )
    recent_turns = [
        {
            "turn_id": str(t.id),
            "sequence_number": t.sequence_number,
            "character_id": str(t.character_id),
            "player_action": t.player_action,
            "rules_result": t.rules_result,
            "narrative": t.narrative_response,
        }
        for t in reversed(turns_result.scalars().all())
    ]

    await websocket.send_json(
        {
            "event": "session.state",
            "payload": {
                "campaign": {
                    "id": str(campaign.id),
                    "name": campaign.name,
                    "status": campaign.status,
                    "turn_count": campaign.state.turn_count if campaign.state else 0,
                },
                "characters": characters,
                "scene": scene,
                "recent_turns": recent_turns,
            },
        }
    )
