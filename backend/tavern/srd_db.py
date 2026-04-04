"""MongoDB connection for SRD reference data (5e-bits/5e-database).

Provides an async Motor client connected to the 5e-database MongoDB instance.
The client is initialised at application startup via the FastAPI lifespan event
and closed at shutdown.

All SRD data access must go through ``core/srd_data.py``, not this module
directly. This module is infrastructure only.

Usage::

    # In main.py lifespan:
    await connect_srd_db()
    ...
    await close_srd_db()

    # In srd_data.py:
    db = get_srd_db()
    doc = await db["monsters"].find_one({"index": "goblin"})
"""

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

MONGODB_URI: str = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/5e-database")
_DB_NAME: str = "5e-database"

_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


async def connect_srd_db() -> None:
    """Initialise the Motor client.

    Must be called at application startup before any SRD data access.
    """
    global _client
    _client = AsyncIOMotorClient(MONGODB_URI)


async def close_srd_db() -> None:
    """Close the Motor client.

    Must be called at application shutdown to release resources.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_srd_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    """Return the ``5e-database`` database handle.

    Raises:
        RuntimeError: If ``connect_srd_db()`` has not been called.
    """
    if _client is None:
        raise RuntimeError(
            "SRD database not initialised. "
            "Ensure connect_srd_db() is called at application startup."
        )
    return _client[_DB_NAME]
