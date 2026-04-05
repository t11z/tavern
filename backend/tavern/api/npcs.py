"""NPC CRUD endpoints (ADR-0013).

Endpoints are scoped to a campaign:
  POST   /api/campaigns/{campaign_id}/npcs        — create predefined NPC
  GET    /api/campaigns/{campaign_id}/npcs        — list NPCs (optional ?status= filter)
  GET    /api/campaigns/{campaign_id}/npcs/{id}   — get single NPC
  PATCH  /api/campaigns/{campaign_id}/npcs/{id}   — update mutable fields
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.api.dependencies import get_db_session
from tavern.api.errors import APIError, not_found
from tavern.core.scene import normalise_scene_id
from tavern.models.campaign import Campaign
from tavern.models.npc import NPC

router = APIRouter(prefix="/campaigns/{campaign_id}/npcs", tags=["npcs"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# ---------------------------------------------------------------------------
# Mutable fields allowed in PATCH
# ---------------------------------------------------------------------------

_MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "motivation",
        "disposition",
        "hp_current",
        "hp_max",
        "ac",
        "creature_type",
        "stat_block_ref",
        "status",
        "scene_location",
        "last_seen_turn",
        "plot_significant",
    }
)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class NPCCreateRequest(BaseModel):
    name: str
    species: str | None = None
    appearance: str | None = None
    role: str | None = None
    status: str = "alive"
    plot_significant: bool = False
    motivation: str | None = None
    disposition: str = "unknown"
    hp_current: int | None = None
    hp_max: int | None = None
    ac: int | None = None
    creature_type: str | None = None
    stat_block_ref: str | None = None
    first_appeared_turn: int | None = None
    last_seen_turn: int | None = None
    scene_location: str | None = None


class NPCPatchRequest(BaseModel):
    # All fields optional — caller sends only what they want to change.
    motivation: str | None = None
    disposition: str | None = None
    hp_current: int | None = None
    hp_max: int | None = None
    ac: int | None = None
    creature_type: str | None = None
    stat_block_ref: str | None = None
    status: str | None = None
    scene_location: str | None = None
    last_seen_turn: int | None = None
    plot_significant: bool | None = None

    # Immutable fields listed here so Pydantic can parse them — but they are
    # rejected by validate_immutable_update before being applied.
    name: str | None = None
    species: str | None = None
    appearance: str | None = None


class NPCResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    origin: str
    status: str
    plot_significant: bool
    species: str | None = None
    appearance: str | None = None
    role: str | None = None
    motivation: str | None = None
    disposition: str
    hp_current: int | None = None
    hp_max: int | None = None
    ac: int | None = None
    creature_type: str | None = None
    stat_block_ref: str | None = None
    first_appeared_turn: int | None = None
    last_seen_turn: int | None = None
    scene_location: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _npc_to_response(npc: NPC) -> NPCResponse:
    return NPCResponse.model_validate(npc)


async def _get_campaign_or_404(campaign_id: uuid.UUID, db: AsyncSession) -> Campaign:
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise not_found("campaign", campaign_id)
    return campaign


async def _get_npc_or_404(
    npc_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession,
) -> NPC:
    result = await db.execute(select(NPC).where(NPC.id == npc_id, NPC.campaign_id == campaign_id))
    npc = result.scalar_one_or_none()
    if npc is None:
        raise not_found("npc", npc_id)
    return npc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=NPCResponse)
async def create_npc(
    campaign_id: uuid.UUID,
    body: NPCCreateRequest,
    db: DbSession,
) -> NPCResponse:
    """Create a predefined NPC for a campaign."""
    await _get_campaign_or_404(campaign_id, db)

    try:
        scene_location = (
            normalise_scene_id(body.scene_location) if body.scene_location is not None else None
        )
    except ValueError as exc:
        raise APIError(status_code=422, error="invalid_scene_id", message=str(exc)) from exc

    npc = NPC(
        campaign_id=campaign_id,
        origin="predefined",
        name=body.name,
        species=body.species,
        appearance=body.appearance,
        role=body.role,
        status=body.status,
        plot_significant=body.plot_significant,
        motivation=body.motivation,
        disposition=body.disposition,
        hp_current=body.hp_current,
        hp_max=body.hp_max,
        ac=body.ac,
        creature_type=body.creature_type,
        stat_block_ref=body.stat_block_ref,
        first_appeared_turn=body.first_appeared_turn,
        last_seen_turn=body.last_seen_turn,
        scene_location=scene_location,
    )
    db.add(npc)
    await db.commit()
    await db.refresh(npc)
    return _npc_to_response(npc)


@router.get("", response_model=list[NPCResponse])
async def list_npcs(
    campaign_id: uuid.UUID,
    db: DbSession,
    status: str | None = Query(default=None),
) -> list[NPCResponse]:
    """List all NPCs for a campaign, with optional status filter."""
    await _get_campaign_or_404(campaign_id, db)

    stmt = select(NPC).where(NPC.campaign_id == campaign_id)
    if status is not None:
        stmt = stmt.where(NPC.status == status)

    result = await db.execute(stmt)
    npcs = result.scalars().all()
    return [_npc_to_response(n) for n in npcs]


@router.get("/{npc_id}", response_model=NPCResponse)
async def get_npc(
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    db: DbSession,
) -> NPCResponse:
    """Get a single NPC by ID."""
    npc = await _get_npc_or_404(npc_id, campaign_id, db)
    return _npc_to_response(npc)


@router.patch("/{npc_id}", response_model=NPCResponse)
async def update_npc(
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    body: NPCPatchRequest,
    db: DbSession,
) -> NPCResponse:
    """Update mutable NPC fields. Returns 422 if immutable fields are included."""
    # Build dict of fields explicitly provided (exclude unset to allow partial updates)
    updates: dict[str, Any] = body.model_dump(exclude_unset=True)

    # Enforce immutability
    try:
        NPC.validate_immutable_update(updates)
    except ValueError as exc:
        raise APIError(status_code=422, error="immutable_field", message=str(exc)) from exc

    # Normalise scene_location if provided
    if "scene_location" in updates and updates["scene_location"] is not None:
        try:
            updates["scene_location"] = normalise_scene_id(updates["scene_location"])
        except ValueError as exc:
            raise APIError(status_code=422, error="invalid_scene_id", message=str(exc)) from exc

    npc = await _get_npc_or_404(npc_id, campaign_id, db)

    for field, value in updates.items():
        if field in _MUTABLE_FIELDS:
            setattr(npc, field, value)

    await db.commit()
    await db.refresh(npc)
    return _npc_to_response(npc)
