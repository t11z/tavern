import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from tavern.models.base import Base

if TYPE_CHECKING:
    from tavern.models.campaign import Campaign
    from tavern.models.turn import Turn

END_REASONS = {"player_ended", "connection_lost"}


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('player_ended', 'connection_lost')",
            name="ck_sessions_end_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="sessions")
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session", order_by="Turn.sequence_number"
    )

    @validates("end_reason")
    def validate_end_reason(self, key: str, value: str | None) -> str | None:
        if value is not None and value not in END_REASONS:
            raise ValueError(f"Invalid end_reason '{value}'. Must be one of: {END_REASONS}")
        return value
