"""Async HTTP client for the Tavern REST API.

All methods raise TavernAPIError on 4xx/5xx responses. Callers receive the
raw JSON body (dict) on success — no deserialization into domain objects here;
that is the callers' responsibility.

Usage::

    async with TavernAPI("http://tavern:8000") as api:
        campaign = await api.get_campaign(campaign_id)

Or manage lifetime manually::

    api = TavernAPI(base_url)
    ...
    await api.aclose()
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx


class TavernAPIError(Exception):
    """Raised when the Tavern API returns a 4xx or 5xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"TavernAPI {status_code}: {message}")


def _id(value: str | UUID) -> str:
    return str(value)


class TavernAPI:
    """Async HTTP client wrapping the Tavern REST API.

    A single ``httpx.AsyncClient`` is shared for connection pooling.
    Timeout defaults to 10 seconds on all requests.
    """

    def __init__(self, base_url: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(10.0),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("message") or body.get("detail") or response.text
            except Exception:
                message = response.text
            raise TavernAPIError(response.status_code, str(message))

    async def _json(self, response: httpx.Response) -> dict[str, Any]:
        await self._raise_for_status(response)
        return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """GET /health — liveness probe."""
        r = await self._client.get("/health")
        return await self._json(r)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------

    async def list_campaigns(self) -> dict[str, Any]:
        """GET /api/campaigns"""
        r = await self._client.get("/api/campaigns")
        return await self._json(r)

    async def create_campaign(self, data: dict[str, Any]) -> dict[str, Any]:
        """POST /api/campaigns"""
        r = await self._client.post("/api/campaigns", json=data)
        return await self._json(r)

    async def get_campaign(self, campaign_id: str | UUID) -> dict[str, Any]:
        """GET /api/campaigns/{id}"""
        r = await self._client.get(f"/api/campaigns/{_id(campaign_id)}")
        return await self._json(r)

    async def get_campaign_config(self, campaign_id: str | UUID) -> dict[str, Any]:
        """GET /api/campaigns/{id}/config"""
        r = await self._client.get(f"/api/campaigns/{_id(campaign_id)}/config")
        return await self._json(r)

    async def patch_campaign_config(
        self, campaign_id: str | UUID, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /api/campaigns/{id}/config"""
        r = await self._client.patch(
            f"/api/campaigns/{_id(campaign_id)}/config", json=settings
        )
        return await self._json(r)

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    async def submit_turn(
        self, campaign_id: str | UUID, character_id: str | UUID, action: str
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/turns"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/turns",
            json={"character_id": _id(character_id), "action": action},
        )
        return await self._json(r)

    async def get_turn_history(
        self, campaign_id: str | UUID, limit: int = 5
    ) -> dict[str, Any]:
        """GET /api/campaigns/{id}/turns?limit=N"""
        r = await self._client.get(
            f"/api/campaigns/{_id(campaign_id)}/turns",
            params={"limit": limit},
        )
        return await self._json(r)

    # ------------------------------------------------------------------
    # Rolls  (ADR-0009)
    # ------------------------------------------------------------------

    async def execute_roll(
        self,
        campaign_id: str | UUID,
        turn_id: str | UUID,
        roll_id: str | UUID,
        pre_roll_options: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/turns/{turn_id}/rolls/{roll_id}/execute"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/turns/{_id(turn_id)}"
            f"/rolls/{_id(roll_id)}/execute",
            json={"pre_roll_options": pre_roll_options or []},
        )
        return await self._json(r)

    async def submit_reaction(
        self,
        campaign_id: str | UUID,
        turn_id: str | UUID,
        roll_id: str | UUID,
        character_id: str | UUID,
        reaction_id: str,
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/turns/{turn_id}/rolls/{roll_id}/react"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/turns/{_id(turn_id)}"
            f"/rolls/{_id(roll_id)}/react",
            json={"character_id": _id(character_id), "reaction_id": reaction_id},
        )
        return await self._json(r)

    async def submit_pass(
        self,
        campaign_id: str | UUID,
        turn_id: str | UUID,
        roll_id: str | UUID,
        character_id: str | UUID,
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/turns/{turn_id}/rolls/{roll_id}/pass"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/turns/{_id(turn_id)}"
            f"/rolls/{_id(roll_id)}/pass",
            json={"character_id": _id(character_id)},
        )
        return await self._json(r)

    async def standalone_roll(
        self, campaign_id: str | UUID, expression: str
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/rolls/standalone"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/rolls/standalone",
            json={"expression": expression},
        )
        return await self._json(r)

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------

    async def get_characters(self, campaign_id: str | UUID) -> dict[str, Any]:
        """GET /api/campaigns/{id}/characters"""
        r = await self._client.get(f"/api/campaigns/{_id(campaign_id)}/characters")
        return await self._json(r)

    async def create_character(
        self, campaign_id: str | UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/characters"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/characters", json=data
        )
        return await self._json(r)

    async def get_character(
        self, campaign_id: str | UUID, character_id: str | UUID
    ) -> dict[str, Any]:
        """GET /api/campaigns/{id}/characters/{character_id}"""
        r = await self._client.get(
            f"/api/campaigns/{_id(campaign_id)}/characters/{_id(character_id)}"
        )
        return await self._json(r)

    # ------------------------------------------------------------------
    # Members  (ADR-0006)
    # ------------------------------------------------------------------

    async def invite_player(
        self, campaign_id: str | UUID, user_id: str | UUID
    ) -> dict[str, Any]:
        """POST /api/campaigns/{id}/members"""
        r = await self._client.post(
            f"/api/campaigns/{_id(campaign_id)}/members",
            json={"user_id": _id(user_id)},
        )
        return await self._json(r)

    async def remove_player(
        self, campaign_id: str | UUID, user_id: str | UUID
    ) -> None:
        """DELETE /api/campaigns/{id}/members/{user_id}"""
        r = await self._client.delete(
            f"/api/campaigns/{_id(campaign_id)}/members/{_id(user_id)}"
        )
        await self._raise_for_status(r)

    # ------------------------------------------------------------------
    # Lifetime management
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> TavernAPI:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
