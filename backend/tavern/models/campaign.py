import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from tavern.models.base import JSONB, Base

if TYPE_CHECKING:
    from tavern.models.character import Character
    from tavern.models.session import Session

CAMPAIGN_STATUSES = {"active", "paused", "concluded", "abandoned"}


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'concluded', 'abandoned')",
            name="ck_campaigns_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    world_seed: Mapped[str | None] = mapped_column(Text, nullable=True)
    dm_persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_played_at: Mapped[datetime | None] = mapped_column(nullable=True)

    state: Mapped["CampaignState"] = relationship(back_populates="campaign", uselist=False)
    sessions: Mapped[list["Session"]] = relationship(back_populates="campaign")
    characters: Mapped[list["Character"]] = relationship(back_populates="campaign")

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        if value not in CAMPAIGN_STATUSES:
            raise ValueError(
                f"Invalid campaign status '{value}'. Must be one of: {CAMPAIGN_STATUSES}"
            )
        return value


class CampaignState(Base):
    __tablename__ = "campaign_states"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"), unique=True)
    rolling_summary: Mapped[str] = mapped_column(Text)
    scene_context: Mapped[str] = mapped_column(Text)
    world_state: Mapped[dict] = mapped_column(JSONB)
    turn_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    campaign: Mapped["Campaign"] = relationship(back_populates="state")
