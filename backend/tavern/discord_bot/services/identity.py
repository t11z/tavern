"""Identity service: maps Discord users to Tavern users and their characters.

The Discord bot needs to answer two questions during gameplay:
  1. "Which Tavern user corresponds to Discord user X?"
  2. "Which character is Discord user X playing in campaign Y?"

Both answers come from the Tavern API (ADR-0006).  Results are cached in
memory for the lifetime of the bot process, recoverable by restart.

User endpoints are planned per ADR-0006 and will be available once the auth
layer is implemented.  Until then, ``get_tavern_user`` may raise
``TavernAPIError`` if the endpoint is not yet deployed.

Cache invalidation is intentionally simple: ``clear_cache()`` resets both
caches entirely (e.g., for testing or on reconnect).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .api_client import TavernAPI, TavernAPIError

# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass
class TavernUser:
    """A Tavern user as described in ADR-0006."""

    id: UUID
    display_name: str
    auth_provider: str
    external_id: str | None = None


@dataclass
class Character:
    """A campaign character, projected from the Tavern API response."""

    id: UUID
    campaign_id: UUID
    name: str
    class_name: str
    level: int
    hp: int
    max_hp: int
    ac: int
    user_id: UUID | None = None
    """Populated once auth is implemented (ADR-0006).  None in the interim."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class IdentityService:
    """Maps Discord user IDs to Tavern users and characters.

    Args:
        api: A ``TavernAPI`` instance to call when the cache misses.
    """

    def __init__(self, api: TavernAPI) -> None:
        self._api = api
        self._user_cache: dict[int, TavernUser] = {}
        self._character_cache: dict[tuple[int, str], Character | None] = {}

    # ------------------------------------------------------------------
    # User resolution
    # ------------------------------------------------------------------

    async def get_tavern_user(self, discord_user_id: int, display_name: str) -> TavernUser:
        """Return the Tavern user for a Discord user, creating one if absent.

        Caches the result keyed by ``discord_user_id``.  On the first call the
        service queries ``GET /api/users?external_id=...&auth_provider=discord``
        and falls back to ``POST /api/users`` if the user does not exist yet.

        Raises:
            TavernAPIError: If the API returns an unexpected error.
        """
        if discord_user_id in self._user_cache:
            return self._user_cache[discord_user_id]

        user = await self._find_or_create_user(discord_user_id, display_name)
        self._user_cache[discord_user_id] = user
        return user

    async def _find_or_create_user(self, discord_user_id: int, display_name: str) -> TavernUser:
        try:
            data = await self._api._json(
                await self._api._client.get(
                    "/api/users",
                    params={
                        "external_id": str(discord_user_id),
                        "auth_provider": "discord",
                    },
                )
            )
            return _parse_user(data)
        except TavernAPIError as exc:
            if exc.status_code != 404:
                raise
        # Not found — create the user.
        data = await self._api._json(
            await self._api._client.post(
                "/api/users",
                json={
                    "display_name": display_name,
                    "auth_provider": "discord",
                    "external_id": str(discord_user_id),
                },
            )
        )
        return _parse_user(data)

    # ------------------------------------------------------------------
    # Character resolution
    # ------------------------------------------------------------------

    async def get_character(
        self, discord_user_id: int, campaign_id: str | UUID
    ) -> Character | None:
        """Return the character this Discord user is playing in the campaign.

        Looks up the Tavern user, then fetches the campaign's character list
        and returns the first character whose ``user_id`` matches.  Returns
        ``None`` if no character is linked yet (expected before auth is fully
        implemented or before the player has created a character).

        Results are cached per ``(discord_user_id, campaign_id)`` pair.
        """
        cache_key = (discord_user_id, str(campaign_id))
        if cache_key in self._character_cache:
            return self._character_cache[cache_key]

        character = await self._resolve_character(discord_user_id, campaign_id)
        self._character_cache[cache_key] = character
        return character

    async def _resolve_character(
        self, discord_user_id: int, campaign_id: str | UUID
    ) -> Character | None:
        try:
            tavern_user = self._user_cache.get(discord_user_id)
            if tavern_user is None:
                return None

            data = await self._api.get_characters(campaign_id)
            characters = data if isinstance(data, list) else data.get("characters", [])

            for raw in characters:
                raw_user_id = raw.get("user_id")
                if raw_user_id is not None and UUID(raw_user_id) == tavern_user.id:
                    return _parse_character(raw)
        except TavernAPIError:
            pass
        return None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Reset all caches.  Intended for tests and post-reconnect recovery."""
        self._user_cache.clear()
        self._character_cache.clear()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_user(data: dict) -> TavernUser:  # type: ignore[type-arg]
    return TavernUser(
        id=UUID(data["id"]),
        display_name=data["display_name"],
        auth_provider=data["auth_provider"],
        external_id=data.get("external_id"),
    )


def _parse_character(data: dict) -> Character:  # type: ignore[type-arg]
    raw_user_id = data.get("user_id")
    return Character(
        id=UUID(data["id"]),
        campaign_id=UUID(data["campaign_id"]),
        name=data["name"],
        class_name=data["class_name"],
        level=data["level"],
        hp=data["hp"],
        max_hp=data["max_hp"],
        ac=data["ac"],
        user_id=UUID(raw_user_id) if raw_user_id else None,
    )
