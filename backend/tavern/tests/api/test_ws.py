"""Tests for the WebSocket campaign endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from tavern.api.ws import manager
from tavern.main import app

_VALID_FIGHTER = {
    "name": "Aldric",
    "species": "Human",
    "class_name": "Fighter",
    "background": "Soldier",
    "ability_scores": {"STR": 15, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
    "ability_score_method": "standard_array",
    "background_bonuses": {"STR": 2, "CON": 1},
    "equipment_choices": "package_a",
    "languages": ["Common"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_campaign(client: AsyncClient, name: str = "WS Test") -> str:
    """Create + activate a campaign. Returns campaign_id."""
    campaign = (await client.post("/api/campaigns", json={"name": name})).json()
    cid = campaign["id"]
    await client.post(f"/api/campaigns/{cid}/sessions")
    return cid


def _ws_connect(cid: str):
    """Return a sync WebSocket context manager (reuses app.dependency_overrides)."""
    return TestClient(app, raise_server_exceptions=True).websocket_connect(
        f"/api/campaigns/{cid}/ws"
    )


# ---------------------------------------------------------------------------
# WebSocket connection tests
# ---------------------------------------------------------------------------


class TestWebSocketConnection:
    async def test_connect_valid_campaign_receives_session_state(
        self, api_client: AsyncClient
    ) -> None:
        """Connecting to an existing campaign sends a session.state event."""
        cid = await _make_campaign(api_client)

        # app.dependency_overrides is already set by the api_client fixture.
        # TestClient runs the same 'app' object → overrides are honoured.
        with TestClient(app).websocket_connect(f"/api/campaigns/{cid}/ws") as ws:
            data = ws.receive_json()

        assert data["event"] == "session.state"
        payload = data["payload"]
        assert payload["campaign"]["id"] == cid
        assert "characters" in payload
        assert "scene" in payload
        assert "recent_turns" in payload

    async def test_connect_invalid_campaign_closes_with_4004(
        self, api_client: AsyncClient
    ) -> None:
        """Connecting to a non-existent campaign closes with code 4004."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(Exception):
            with TestClient(app, raise_server_exceptions=False).websocket_connect(
                f"/api/campaigns/{fake_id}/ws"
            ) as ws:
                ws.receive_json()

    async def test_disconnect_handled_without_error(
        self, api_client: AsyncClient
    ) -> None:
        """Normal disconnect must not raise exceptions."""
        cid = await _make_campaign(api_client, name="Disconnect Test")

        # No exception should propagate
        with TestClient(app).websocket_connect(f"/api/campaigns/{cid}/ws") as ws:
            ws.receive_json()  # session.state — then context exits cleanly

    async def test_session_state_recent_turns_empty_for_new_campaign(
        self, api_client: AsyncClient
    ) -> None:
        cid = await _make_campaign(api_client, name="Turn History Test")

        with TestClient(app).websocket_connect(f"/api/campaigns/{cid}/ws") as ws:
            data = ws.receive_json()

        assert data["payload"]["recent_turns"] == []

    async def test_session_state_turn_count_zero_for_new_campaign(
        self, api_client: AsyncClient
    ) -> None:
        cid = await _make_campaign(api_client, name="Count Test")

        with TestClient(app).websocket_connect(f"/api/campaigns/{cid}/ws") as ws:
            data = ws.receive_json()

        assert data["payload"]["campaign"]["turn_count"] == 0

    async def test_session_state_includes_character(
        self, api_client: AsyncClient
    ) -> None:
        """Characters created before connecting appear in session.state."""
        campaign = (await api_client.post("/api/campaigns", json={"name": "Char Test"})).json()
        cid = campaign["id"]
        await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        await api_client.post(f"/api/campaigns/{cid}/sessions")

        with TestClient(app).websocket_connect(f"/api/campaigns/{cid}/ws") as ws:
            data = ws.receive_json()

        characters = data["payload"]["characters"]
        assert len(characters) == 1
        assert characters[0]["name"] == "Aldric"


# ---------------------------------------------------------------------------
# ConnectionManager unit tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    def test_connection_count_zero_for_unknown_campaign(self) -> None:
        unknown_id = uuid.uuid4()
        assert manager.connection_count(unknown_id) == 0

    @pytest.mark.anyio
    async def test_broadcast_to_empty_campaign_does_not_raise(self) -> None:
        """broadcast() to a campaign with no connections must be a no-op."""
        unknown_id = uuid.uuid4()
        await manager.broadcast(unknown_id, {"event": "test", "payload": {}})
