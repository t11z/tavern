import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tavern.models.base import Base

if TYPE_CHECKING:
    from tavern.models.character import Character
    from tavern.models.session import Session


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    character_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    player_action: Mapped[str] = mapped_column(Text)
    rules_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    session: Mapped["Session"] = relationship(back_populates="turns")
    character: Mapped["Character"] = relationship(back_populates="turns")
