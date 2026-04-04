"""Tests for Claude-generated campaign brief in create_campaign()."""

from __future__ import annotations

from unittest.mock import AsyncMock

from httpx import AsyncClient

from tavern.tests.api.conftest import MOCK_CAMPAIGN_BRIEF

_FALLBACK = "Your adventure is about to begin."

_CREATE_PAYLOAD = {"name": "The Lost Throne", "tone": "classic_fantasy"}


# ---------------------------------------------------------------------------
# Happy path — narrator returns a valid brief
# ---------------------------------------------------------------------------


class TestCampaignBriefGenerated:
    async def test_create_campaign_returns_201(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        assert resp.status_code == 201

    async def test_scene_context_is_generated_not_fallback(self, api_client: AsyncClient) -> None:
        """When Claude succeeds, scene_context is the generated opening scene."""
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        body = resp.json()
        assert body["state"]["scene_context"] == MOCK_CAMPAIGN_BRIEF["opening_scene"]
        assert body["state"]["scene_context"] != _FALLBACK

    async def test_world_seed_is_campaign_brief(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        body = resp.json()
        assert body["world_seed"] == MOCK_CAMPAIGN_BRIEF["campaign_brief"]

    async def test_world_state_location_populated(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        world_state = resp.json()["state"]["world_state"]
        assert world_state["location"] == MOCK_CAMPAIGN_BRIEF["location"]

    async def test_world_state_environment_populated(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        world_state = resp.json()["state"]["world_state"]
        assert world_state["environment"] == MOCK_CAMPAIGN_BRIEF["environment"]

    async def test_world_state_time_of_day_populated(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        world_state = resp.json()["state"]["world_state"]
        assert world_state["time_of_day"] == MOCK_CAMPAIGN_BRIEF["time_of_day"]


# ---------------------------------------------------------------------------
# Failure path — narrator raises an exception
# ---------------------------------------------------------------------------


class TestCampaignBriefFallback:
    async def test_campaign_created_when_narrator_raises_runtime_error(
        self,
        api_client: AsyncClient,
        mock_narrator,
    ) -> None:
        """RuntimeError (rate limit) must not block campaign creation."""
        mock_narrator.generate_campaign_brief = AsyncMock(
            side_effect=RuntimeError("rate limit exceeded")
        )
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        assert resp.status_code == 201

    async def test_fallback_scene_context_on_narrator_failure(
        self,
        api_client: AsyncClient,
        mock_narrator,
    ) -> None:
        mock_narrator.generate_campaign_brief = AsyncMock(
            side_effect=TimeoutError("request timed out")
        )
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        body = resp.json()
        assert body["state"]["scene_context"] == _FALLBACK

    async def test_fallback_world_seed_on_narrator_failure(
        self,
        api_client: AsyncClient,
        mock_narrator,
    ) -> None:
        mock_narrator.generate_campaign_brief = AsyncMock(side_effect=ValueError("invalid JSON"))
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        body = resp.json()
        # world_seed falls back to the tone preset string, not the Claude-generated brief
        assert body["world_seed"] != MOCK_CAMPAIGN_BRIEF["campaign_brief"]

    async def test_campaign_id_present_on_fallback(
        self,
        api_client: AsyncClient,
        mock_narrator,
    ) -> None:
        mock_narrator.generate_campaign_brief = AsyncMock(side_effect=RuntimeError("API error"))
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        body = resp.json()
        assert "id" in body
        assert body["name"] == "The Lost Throne"


# ---------------------------------------------------------------------------
# Field completeness — generated response has all required fields
# ---------------------------------------------------------------------------


class TestCampaignBriefFieldCompleteness:
    async def test_response_has_world_seed(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        assert "world_seed" in resp.json()
        assert resp.json()["world_seed"]  # non-empty

    async def test_response_state_has_scene_context(self, api_client: AsyncClient) -> None:
        resp = await api_client.post("/api/campaigns", json=_CREATE_PAYLOAD)
        assert "scene_context" in resp.json()["state"]
        assert resp.json()["state"]["scene_context"]  # non-empty

    async def test_different_tones_use_correct_preset_on_failure(
        self,
        api_client: AsyncClient,
        mock_narrator,
    ) -> None:
        """On failure, dark_gritty tone falls back to its own preset, not classic_fantasy."""
        mock_narrator.generate_campaign_brief = AsyncMock(side_effect=RuntimeError("down"))
        resp = await api_client.post(
            "/api/campaigns", json={"name": "Grim Times", "tone": "dark_gritty"}
        )
        body = resp.json()
        assert (
            "moral ambiguity" in body["world_seed"].lower()
            or "harsh" in body["world_seed"].lower()
        )
