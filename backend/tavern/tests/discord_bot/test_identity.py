"""Tests for IdentityService — cache hit, cache miss, user creation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from tavern.discord_bot.services.api_client import TavernAPI, TavernAPIError
from tavern.discord_bot.services.identity import (
    Character,
    IdentityService,
    TavernUser,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

TAVERN_USER_ID = str(uuid.uuid4())
DISCORD_USER_ID = 123456789
CAMPAIGN_ID = str(uuid.uuid4())
CHARACTER_ID = str(uuid.uuid4())

_USER_PAYLOAD = {
    "id": TAVERN_USER_ID,
    "display_name": "Alice",
    "auth_provider": "discord",
    "external_id": str(DISCORD_USER_ID),
}

_CHAR_PAYLOAD = {
    "id": CHARACTER_ID,
    "campaign_id": CAMPAIGN_ID,
    "name": "Kael",
    "class_name": "Fighter",
    "level": 3,
    "hp": 28,
    "max_hp": 32,
    "ac": 18,
    "user_id": TAVERN_USER_ID,
}


def ok(body: object) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body
    r.text = str(body)
    return r


def not_found() -> MagicMock:
    r = MagicMock()
    r.status_code = 404
    r.json.return_value = {"message": "Not found"}
    r.text = "Not found"
    return r


@pytest.fixture
def api() -> TavernAPI:
    return TavernAPI("http://localhost:8000")


@pytest.fixture
def service(api: TavernAPI) -> IdentityService:
    return IdentityService(api)


# ---------------------------------------------------------------------------
# get_tavern_user — cache hit
# ---------------------------------------------------------------------------


class TestGetTavernUserCacheHit:
    async def test_returns_cached_user_without_api_call(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        cached_user = TavernUser(
            id=uuid.UUID(TAVERN_USER_ID),
            display_name="Alice",
            auth_provider="discord",
            external_id=str(DISCORD_USER_ID),
        )
        service._user_cache[DISCORD_USER_ID] = cached_user
        api._client.get = AsyncMock()

        result = await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        assert result == cached_user
        api._client.get.assert_not_called()

    async def test_second_call_does_not_hit_api(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=ok(_USER_PAYLOAD))
        api._client.post = AsyncMock()

        await service.get_tavern_user(DISCORD_USER_ID, "Alice")
        await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        # API should only be called once (on the first miss)
        assert api._client.get.call_count == 1


# ---------------------------------------------------------------------------
# get_tavern_user — cache miss, user exists in API
# ---------------------------------------------------------------------------


class TestGetTavernUserCacheMissFound:
    async def test_queries_api_by_discord_id(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=ok(_USER_PAYLOAD))

        await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        api._client.get.assert_called_once_with(
            "/api/users",
            params={"external_id": str(DISCORD_USER_ID), "auth_provider": "discord"},
        )

    async def test_returns_parsed_user(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=ok(_USER_PAYLOAD))

        result = await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        assert isinstance(result, TavernUser)
        assert result.id == uuid.UUID(TAVERN_USER_ID)
        assert result.display_name == "Alice"
        assert result.auth_provider == "discord"
        assert result.external_id == str(DISCORD_USER_ID)

    async def test_caches_user_after_api_call(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=ok(_USER_PAYLOAD))

        await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        assert DISCORD_USER_ID in service._user_cache


# ---------------------------------------------------------------------------
# get_tavern_user — cache miss, user does not exist → create
# ---------------------------------------------------------------------------


class TestGetTavernUserCacheMissCreate:
    async def test_creates_user_when_404(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=not_found())
        api._client.post = AsyncMock(return_value=ok(_USER_PAYLOAD))

        result = await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        api._client.post.assert_called_once_with(
            "/api/users",
            json={
                "display_name": "Alice",
                "auth_provider": "discord",
                "external_id": str(DISCORD_USER_ID),
            },
        )
        assert isinstance(result, TavernUser)

    async def test_caches_created_user(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=not_found())
        api._client.post = AsyncMock(return_value=ok(_USER_PAYLOAD))

        await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        assert DISCORD_USER_ID in service._user_cache

    async def test_non_404_error_propagates(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        server_error = MagicMock()
        server_error.status_code = 500
        server_error.json.return_value = {"message": "Internal error"}
        server_error.text = "Internal error"
        api._client.get = AsyncMock(return_value=server_error)

        with pytest.raises(TavernAPIError) as exc_info:
            await service.get_tavern_user(DISCORD_USER_ID, "Alice")
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_character
# ---------------------------------------------------------------------------


class TestGetCharacter:
    async def test_returns_none_when_user_not_cached(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock()

        result = await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)

        assert result is None

    async def test_returns_matching_character(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        # Pre-warm user cache
        service._user_cache[DISCORD_USER_ID] = TavernUser(
            id=uuid.UUID(TAVERN_USER_ID),
            display_name="Alice",
            auth_provider="discord",
            external_id=str(DISCORD_USER_ID),
        )
        api._client.get = AsyncMock(return_value=ok([_CHAR_PAYLOAD]))

        result = await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)

        assert isinstance(result, Character)
        assert result.id == uuid.UUID(CHARACTER_ID)
        assert result.name == "Kael"
        assert result.user_id == uuid.UUID(TAVERN_USER_ID)

    async def test_returns_none_when_no_character_matches(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        service._user_cache[DISCORD_USER_ID] = TavernUser(
            id=uuid.UUID(TAVERN_USER_ID),
            display_name="Alice",
            auth_provider="discord",
        )
        other_user_char = dict(_CHAR_PAYLOAD)
        other_user_char["user_id"] = str(uuid.uuid4())  # different user
        api._client.get = AsyncMock(return_value=ok([other_user_char]))

        result = await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)

        assert result is None

    async def test_caches_character_lookup(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        service._user_cache[DISCORD_USER_ID] = TavernUser(
            id=uuid.UUID(TAVERN_USER_ID),
            display_name="Alice",
            auth_provider="discord",
        )
        api._client.get = AsyncMock(return_value=ok([_CHAR_PAYLOAD]))

        await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)
        await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)

        # Characters endpoint only called once — second call is cached
        assert api._client.get.call_count == 1

    async def test_returns_none_on_api_error(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        service._user_cache[DISCORD_USER_ID] = TavernUser(
            id=uuid.UUID(TAVERN_USER_ID),
            display_name="Alice",
            auth_provider="discord",
        )
        api._client.get = AsyncMock(
            return_value=MagicMock(
                status_code=500,
                json=MagicMock(return_value={"message": "error"}),
                text="error",
            )
        )

        result = await service.get_character(DISCORD_USER_ID, CAMPAIGN_ID)

        assert result is None


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    async def test_clears_user_cache(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        service._user_cache[DISCORD_USER_ID] = TavernUser(
            id=uuid.uuid4(), display_name="Alice", auth_provider="discord"
        )
        service.clear_cache()
        assert service._user_cache == {}

    async def test_clears_character_cache(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        service._character_cache[(DISCORD_USER_ID, CAMPAIGN_ID)] = None
        service.clear_cache()
        assert service._character_cache == {}

    async def test_api_called_again_after_clear(
        self, service: IdentityService, api: TavernAPI
    ) -> None:
        api._client.get = AsyncMock(return_value=ok(_USER_PAYLOAD))

        await service.get_tavern_user(DISCORD_USER_ID, "Alice")
        service.clear_cache()
        await service.get_tavern_user(DISCORD_USER_ID, "Alice")

        assert api._client.get.call_count == 2
