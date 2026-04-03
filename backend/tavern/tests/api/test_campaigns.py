"""Tests for campaign lifecycle endpoints."""

from __future__ import annotations

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Create campaign
# ---------------------------------------------------------------------------


class TestCreateCampaign:
    async def test_create_campaign_returns_201(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns",
            json={"name": "The Shattered Coast", "tone": "classic_fantasy"},
        )
        assert response.status_code == 201

    async def test_create_campaign_returns_id(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns",
            json={"name": "Test Campaign"},
        )
        body = response.json()
        assert "id" in body
        assert isinstance(body["id"], str)

    async def test_create_campaign_status_is_paused(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns",
            json={"name": "Test Campaign"},
        )
        assert response.json()["status"] == "paused"

    async def test_create_campaign_includes_state(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns",
            json={"name": "Test Campaign"},
        )
        body = response.json()
        assert "state" in body
        assert body["state"]["turn_count"] == 0

    async def test_create_campaign_tone_sets_world_seed(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns",
            json={"name": "Grim Campaign", "tone": "dark_gritty"},
        )
        body = response.json()
        assert body["world_seed"] is not None
        assert body["world_seed"] != ""

    async def test_create_campaign_missing_name_returns_422(self, api_client: AsyncClient) -> None:
        response = await api_client.post("/api/campaigns", json={"tone": "dark_gritty"})
        assert response.status_code == 422

    async def test_create_campaign_empty_name_returns_422(self, api_client: AsyncClient) -> None:
        response = await api_client.post("/api/campaigns", json={"name": ""})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# List campaigns
# ---------------------------------------------------------------------------


class TestListCampaigns:
    async def test_list_campaigns_returns_empty_array_initially(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.get("/api/campaigns")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_campaigns_returns_created_campaigns(self, api_client: AsyncClient) -> None:
        await api_client.post("/api/campaigns", json={"name": "Campaign A"})
        await api_client.post("/api/campaigns", json={"name": "Campaign B"})

        response = await api_client.get("/api/campaigns")
        assert response.status_code == 200
        names = [c["name"] for c in response.json()]
        assert "Campaign A" in names
        assert "Campaign B" in names


# ---------------------------------------------------------------------------
# Get campaign
# ---------------------------------------------------------------------------


class TestGetCampaign:
    async def test_get_campaign_returns_200(self, api_client: AsyncClient) -> None:
        created = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        response = await api_client.get(f"/api/campaigns/{created['id']}")
        assert response.status_code == 200

    async def test_get_campaign_includes_state(self, api_client: AsyncClient) -> None:
        created = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        response = await api_client.get(f"/api/campaigns/{created['id']}")
        assert "state" in response.json()

    async def test_get_nonexistent_campaign_returns_404(self, api_client: AsyncClient) -> None:
        response = await api_client.get("/api/campaigns/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    async def test_404_error_has_correct_shape(self, api_client: AsyncClient) -> None:
        response = await api_client.get("/api/campaigns/00000000-0000-0000-0000-000000000000")
        body = response.json()
        assert "error" in body
        assert "message" in body
        assert body["status"] == 404


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


class TestStartSession:
    async def test_start_session_returns_201(self, api_client: AsyncClient) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        response = await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")
        assert response.status_code == 201

    async def test_start_session_transitions_to_active(self, api_client: AsyncClient) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")

        detail = (await api_client.get(f"/api/campaigns/{campaign['id']}")).json()
        assert detail["status"] == "active"

    async def test_start_session_on_active_campaign_returns_409(
        self, api_client: AsyncClient
    ) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")

        # Try to start again
        response = await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")
        assert response.status_code == 409

    async def test_start_session_on_nonexistent_campaign_returns_404(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/sessions"
        )
        assert response.status_code == 404


class TestEndSession:
    async def test_end_session_returns_200(self, api_client: AsyncClient) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")

        response = await api_client.post(f"/api/campaigns/{campaign['id']}/sessions/end")
        assert response.status_code == 200

    async def test_end_session_transitions_to_paused(self, api_client: AsyncClient) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions/end")

        detail = (await api_client.get(f"/api/campaigns/{campaign['id']}")).json()
        assert detail["status"] == "paused"

    async def test_end_session_sets_end_reason(self, api_client: AsyncClient) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        await api_client.post(f"/api/campaigns/{campaign['id']}/sessions")

        response = await api_client.post(f"/api/campaigns/{campaign['id']}/sessions/end")
        assert response.json()["end_reason"] == "player_ended"

    async def test_end_session_on_paused_campaign_returns_409(
        self, api_client: AsyncClient
    ) -> None:
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        # Campaign is paused — no active session to end
        response = await api_client.post(f"/api/campaigns/{campaign['id']}/sessions/end")
        assert response.status_code == 409

    async def test_resume_campaign_after_end_session(self, api_client: AsyncClient) -> None:
        """Full lifecycle: pause → active → pause → active."""
        campaign = (await api_client.post("/api/campaigns", json={"name": "Test"})).json()
        cid = campaign["id"]

        await api_client.post(f"/api/campaigns/{cid}/sessions")
        await api_client.post(f"/api/campaigns/{cid}/sessions/end")
        await api_client.post(f"/api/campaigns/{cid}/sessions")

        detail = (await api_client.get(f"/api/campaigns/{cid}")).json()
        assert detail["status"] == "active"
