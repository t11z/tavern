import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tavern.models.base import JSONB, Base

if TYPE_CHECKING:
    from tavern.models.campaign import Campaign
    from tavern.models.turn import Turn


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str] = mapped_column(String)
    class_name: Mapped[str] = mapped_column(String)
    level: Mapped[int] = mapped_column(default=1)
    hp: Mapped[int] = mapped_column()
    max_hp: Mapped[int] = mapped_column()
    ac: Mapped[int] = mapped_column()
    ability_scores: Mapped[dict] = mapped_column(JSONB)
    spell_slots: Mapped[dict] = mapped_column(JSONB)
    features: Mapped[dict] = mapped_column(JSONB)

    campaign: Mapped["Campaign"] = relationship(back_populates="characters")
    inventory: Mapped[list["InventoryItem"]] = relationship(back_populates="character")
    conditions: Mapped[list["CharacterCondition"]] = relationship(back_populates="character")
    turns: Mapped[list["Turn"]] = relationship(back_populates="character")


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(default=1)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    character: Mapped["Character"] = relationship(back_populates="inventory")


class CharacterCondition(Base):
    __tablename__ = "character_conditions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id"))
    condition_name: Mapped[str] = mapped_column(String)
    duration_rounds: Mapped[int | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    character: Mapped["Character"] = relationship(back_populates="conditions")
