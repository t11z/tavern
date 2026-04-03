"""Shared fixtures for API tests.

The test client overrides:
- get_db_session → SQLite in-memory (from parent conftest)
- get_narrator   → AsyncMock that returns fixed narrative text
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.api.dependencies import get_db_session, get_narrator
from tavern.dm.narrator import Narrator
from tavern.main import app

MOCK_NARRATIVE = "The goblin snarls and lunges forward, rusted blade flashing."
MOCK_SUMMARY = "Turn 1: The party engaged the goblins. Victory was costly."


@pytest.fixture
def mock_narrator() -> Narrator:
    """Narrator mock that never calls the Anthropic API."""
    narrator = MagicMock(spec=Narrator)
    narrator.narrate_turn = AsyncMock(return_value=MOCK_NARRATIVE)
    narrator.update_summary = AsyncMock(return_value=MOCK_SUMMARY)
    return narrator  # type: ignore[return-value]


@pytest.fixture
async def api_client(
    db_session: AsyncSession,
    mock_narrator: Narrator,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient connected to the FastAPI app with overridden dependencies."""

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_narrator] = lambda: mock_narrator

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
