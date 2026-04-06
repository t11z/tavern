"""Shared fixtures for API tests.

Uses a dedicated SQLite in-memory engine with StaticPool so that:
- All sessions in a test share the same in-memory database
- Background tasks (turn streaming) use the same DB as the request session

Overrides:
- get_db_session      → sessions from _TEST_SESSION_FACTORY
- get_narrator        → Mock with fixed narrative + async generator stream
- get_session_factory → _TEST_SESSION_FACTORY (for background tasks)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tavern.api.dependencies import get_db_session, get_narrator, get_session_factory
from tavern.dm.gm_signals import safe_default
from tavern.dm.narrator import Narrator
from tavern.main import app
from tavern.models.base import Base

MOCK_NARRATIVE = "The goblin snarls and lunges forward, rusted blade flashing."
MOCK_SUMMARY = "Turn 1: The party engaged the goblins. Victory was costly."
MOCK_CHUNKS = ["The goblin ", "snarls and ", "lunges forward."]
MOCK_CAMPAIGN_BRIEF = {
    "campaign_brief": "An ancient evil stirs beneath the cobblestones of Thornwall.",
    "opening_scene": "You stand at the gates of Thornwall as torches flicker in the evening wind.",
    "location": "Thornwall",
    "environment": "stone-cobbled city square, evening",
    "time_of_day": "evening",
}

# ---------------------------------------------------------------------------
# Dedicated test database (StaticPool: all sessions share the same connection)
# ---------------------------------------------------------------------------

_TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TEST_SESSION_FACTORY: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _TEST_ENGINE, expire_on_commit=False
)


@pytest.fixture(autouse=True)
async def _reset_api_test_db() -> AsyncGenerator[None, None]:
    """Create tables before each test, drop them after."""
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Narrator mock
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_narrator() -> Narrator:
    """Narrator mock that never calls the Anthropic API.

    narrate_turn_stream returns (MOCK_NARRATIVE, safe_default(), {}) — matching
    the updated Narrator.narrate_turn_stream signature (ADR-0018).
    """
    narrator = MagicMock(spec=Narrator)
    narrator.narrate_turn = AsyncMock(return_value=MOCK_NARRATIVE)
    narrator.update_summary = AsyncMock(return_value=MOCK_SUMMARY)
    narrator.generate_campaign_brief = AsyncMock(return_value=MOCK_CAMPAIGN_BRIEF)
    narrator.narrate_turn_stream = AsyncMock(return_value=(MOCK_NARRATIVE, safe_default(), {}))
    return narrator  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Async HTTP client
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_client(
    mock_narrator: Narrator,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient connected to the FastAPI app with overridden dependencies."""

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with _TEST_SESSION_FACTORY() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_narrator] = lambda: mock_narrator
    app.dependency_overrides[get_session_factory] = lambda: _TEST_SESSION_FACTORY

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
