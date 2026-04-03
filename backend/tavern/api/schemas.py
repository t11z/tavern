"""Pydantic request/response schemas for the Tavern REST API.

Kept separate from SQLAlchemy models — they serve different purposes
(API contract vs. DB schema). Changes here are breaking API changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Campaign schemas
# ---------------------------------------------------------------------------


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    tone: str = "classic_fantasy"
    campaign_length: str = "full"
    setting_type: str = "coastal_city"
    play_focus: str = "balanced"
    difficulty: str = "balanced"


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: str | None = None


class CampaignStateResponse(BaseModel):
    rolling_summary: str
    scene_context: str
    world_state: dict[str, Any]
    turn_count: int
    updated_at: datetime


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    last_played_at: datetime | None = None


class CampaignDetailResponse(CampaignResponse):
    world_seed: str | None = None
    dm_persona: str | None = None
    state: CampaignStateResponse | None = None


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None


# ---------------------------------------------------------------------------
# Character schemas
# ---------------------------------------------------------------------------


class CharacterCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    species: str
    class_name: str
    background: str
    ability_scores: dict[str, int]
    """Base scores before background bonuses: {"STR": 15, "DEX": 13, ...}"""
    ability_score_method: str = "standard_array"
    background_bonuses: dict[str, int]
    """Background ability bonuses: {"STR": 2, "CON": 1}"""
    equipment_choices: str = "package_a"
    """Starting equipment package: "package_a" or "package_b"."""
    languages: list[str] = Field(default_factory=list)


class CharacterUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    hp: int | None = None


class CharacterResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    class_name: str
    level: int
    hp: int
    max_hp: int
    ac: int
    ability_scores: dict[str, int]
    """Final ability scores after background bonuses."""
    spell_slots: dict[str, int]
    features: dict[str, Any]
    """Computed fields: species, background, proficiency_bonus, ability_modifiers, languages."""


# ---------------------------------------------------------------------------
# Turn schemas
# ---------------------------------------------------------------------------


class TurnCreateRequest(BaseModel):
    character_id: uuid.UUID
    action: str = Field(..., min_length=1)


class TurnSubmitResponse(BaseModel):
    """202 Accepted response for turn submission.

    The narrative arrives via WebSocket turn.narrative_* events.
    Use turn_id to correlate WebSocket events with this submission.
    """

    turn_id: uuid.UUID
    sequence_number: int


class TurnResponse(BaseModel):
    """Full turn response — used as the turn.narrative_end WebSocket payload."""

    turn_id: uuid.UUID
    sequence_number: int
    narrative: str
    mechanical_results: list[Any] = Field(default_factory=list)
    """Populated in Phase 6 when the Rules Engine is integrated."""
    character_updates: list[Any] = Field(default_factory=list)
    """Populated in Phase 6."""
    scene_updates: dict[str, Any] = Field(default_factory=dict)
    """Populated when scene transitions occur."""


class TurnListItem(BaseModel):
    turn_id: uuid.UUID
    sequence_number: int
    character_id: uuid.UUID
    player_action: str
    narrative_response: str | None = None
    created_at: datetime


class TurnListResponse(BaseModel):
    turns: list[TurnListItem]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Error schema (documented for OpenAPI — raised by error handlers, not routes)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    error: str
    message: str
    status: int
