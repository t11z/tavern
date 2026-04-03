"""FastAPI dependency functions.

All injectable dependencies live here so they can be overridden in tests
without importing the full application.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from tavern.db import AsyncSessionLocal
from tavern.dm.narrator import AnthropicProvider, Narrator


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, closing it after the request."""
    async with AsyncSessionLocal() as session:
        yield session


def get_narrator() -> Narrator:
    """Return a Narrator backed by the Anthropic API.

    Reads ANTHROPIC_API_KEY from the environment. Overridden in tests
    to avoid real API calls.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return Narrator(AnthropicProvider(api_key=api_key))
