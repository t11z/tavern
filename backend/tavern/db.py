import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tavern.models import (  # noqa: F401 — imported so alembic autogenerate detects all tables
    Campaign,
    CampaignState,
    Character,
    CharacterCondition,
    InventoryItem,
    Session,
    Turn,
)
from tavern.models.base import Base  # noqa: F401 — re-exported for alembic env.py

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://tavern:tavern@localhost:5432/tavern"
)

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)
