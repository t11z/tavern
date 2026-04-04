"""FastAPI dependency functions.

All injectable dependencies live here so they can be overridden in tests
without importing the full application.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tavern.db import AsyncSessionLocal
from tavern.dm.narrator import AnthropicProvider, Narrator


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, closing it after the request."""
    async with AsyncSessionLocal() as session:
        yield session


def get_session_factory() -> async_sessionmaker:
    """Return the async session factory.

    Separate from get_db_session so background tasks (which cannot use
    FastAPI DI) can receive the factory and open their own sessions.
    Overridden in tests to point background tasks at the test database.
    """
    return AsyncSessionLocal


def get_narrator() -> Narrator:
    """Return a Narrator backed by the Anthropic API.

    Reads ANTHROPIC_API_KEY from the environment. Overridden in tests
    to avoid real API calls.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return Narrator(AnthropicProvider(api_key=api_key))
