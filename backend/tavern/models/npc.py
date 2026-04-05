"""NPC persistence model (ADR-0013).

NPCs are tracked per-campaign with immutable core identity attributes
(name, species, appearance) and mutable state (disposition, hp, status, etc.).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tavern.models.base import Base

# ---------------------------------------------------------------------------
# Allowed literal values
# ---------------------------------------------------------------------------

NPC_ORIGINS = {"predefined", "narrator_spawned"}
NPC_STATUSES = {"alive", "dead", "fled", "unknown"}
NPC_DISPOSITIONS = {"friendly", "neutral", "hostile", "unknown"}

# Fields that are immutable after creation.
_IMMUTABLE_FIELDS = frozenset({"name", "species", "appearance"})


class NPC(Base):
    """Persistent NPC record scoped to a campaign (ADR-0013)."""

    __tablename__ = "npcs"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('predefined', 'narrator_spawned')",
            name="ck_npcs_origin",
        ),
        CheckConstraint(
            "status IN ('alive', 'dead', 'fled', 'unknown')",
            name="ck_npcs_status",
        ),
        CheckConstraint(
            "disposition IN ('friendly', 'neutral', 'hostile', 'unknown')",
            name="ck_npcs_disposition",
        ),
        Index("ix_npcs_campaign_id", "campaign_id"),
    )

    # --- Identity ---
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )

    # --- Immutable core ---
    name: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    species: Mapped[str | None] = mapped_column(String, nullable=True)
    appearance: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Mutable state ---
    status: Mapped[str] = mapped_column(String, nullable=False, default="alive")
    plot_significant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition: Mapped[str] = mapped_column(String, nullable=False, default="unknown")

    # --- Combat stats (mutable) ---
    hp_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hp_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ac: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creature_type: Mapped[str | None] = mapped_column(String, nullable=True)
    stat_block_ref: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Scene tracking (mutable) ---
    first_appeared_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_location: Mapped[str | None] = mapped_column(String, nullable=True)

    # ---------------------------------------------------------------------------
    # Immutability enforcement
    # ---------------------------------------------------------------------------

    @classmethod
    def validate_immutable_update(cls, updates: dict) -> None:
        """Raise ValueError if *updates* attempts to change an immutable field.

        Immutable fields (name, species, appearance) cannot be modified after
        creation.  Call this from PATCH endpoints before applying any changes.

        Args:
            updates: Dict of field names to new values (e.g. the parsed request body).

        Raises:
            ValueError: If any immutable field is present in *updates*.
        """
        forbidden = _IMMUTABLE_FIELDS & set(updates.keys())
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(
                f"The following NPC fields are immutable and cannot be updated: {names}"
            )
