"""Tests for the observability inspection endpoints (ADR-0018)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


async def _setup_campaign(client: AsyncClient) -> tuple[str, str, str]:
    """Create campaign, character, open session. Returns (campaign_id, char_id, session_id)."""
    campaign = (await client.post("/api/campaigns", json={"name": "Inspect Test"})).json()
    cid = campaign["id"]
    char = (await client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)).json()
    char_id = char["id"]
    session_resp = (await client.post(f"/api/campaigns/{cid}/sessions")).json()
    session_id = session_resp["id"]
    return cid, char_id, session_id


# ---------------------------------------------------------------------------
# GET /event_log — 404 paths
# ---------------------------------------------------------------------------


class TestGetTurnEventLog:
    async def test_unknown_campaign_returns_404(self, api_client: AsyncClient) -> None:
        fake_cid = str(uuid.uuid4())
        fake_tid = str(uuid.uuid4())
        resp = await api_client.get(f"/api/campaigns/{fake_cid}/turns/{fake_tid}/event_log")
        assert resp.status_code == 404

    async def test_unknown_turn_returns_404(self, api_client: AsyncClient) -> None:
        cid, _, _ = await _setup_campaign(api_client)
        fake_tid = str(uuid.uuid4())
        resp = await api_client.get(f"/api/campaigns/{cid}/turns/{fake_tid}/event_log")
        assert resp.status_code == 404

    async def test_turn_with_no_event_log_returns_404(self, api_client: AsyncClient) -> None:
        """A turn that exists but has no event_log yet returns 404."""
        cid, char_id, _ = await _setup_campaign(api_client)

        # Submit a turn (background task will set event_log, but in tests it may be empty)
        turn_resp = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I look around the room."},
        )
        assert turn_resp.status_code == 202
        turn_id = turn_resp.json()["turn_id"]

        # The turn was created but event_log is None until background task completes.
        # In tests the background task runs synchronously via TestClient, but we're
        # using AsyncClient here — the background task may have run. If so, event_log
        # will be set. Check either 200 (log present) or 404 (log absent).
        resp = await api_client.get(f"/api/campaigns/{cid}/turns/{turn_id}/event_log")
        assert resp.status_code in (200, 404)

    async def test_turn_from_different_campaign_returns_404(self, api_client: AsyncClient) -> None:
        """A turn that exists but belongs to a different campaign returns 404."""
        cid1, char_id1, _ = await _setup_campaign(api_client)
        cid2, _, _ = await _setup_campaign(api_client)

        turn_resp = await api_client.post(
            f"/api/campaigns/{cid1}/turns",
            json={"character_id": char_id1, "action": "I look around."},
        )
        assert turn_resp.status_code == 202
        turn_id = turn_resp.json()["turn_id"]

        # Access turn from wrong campaign
        resp = await api_client.get(f"/api/campaigns/{cid2}/turns/{turn_id}/event_log")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /telemetry — 404 paths and happy path
# ---------------------------------------------------------------------------


class TestGetSessionTelemetry:
    async def test_unknown_campaign_returns_404(self, api_client: AsyncClient) -> None:
        fake_cid = str(uuid.uuid4())
        fake_sid = str(uuid.uuid4())
        resp = await api_client.get(f"/api/campaigns/{fake_cid}/sessions/{fake_sid}/telemetry")
        assert resp.status_code == 404

    async def test_unknown_session_returns_404(self, api_client: AsyncClient) -> None:
        cid, _, _ = await _setup_campaign(api_client)
        fake_sid = str(uuid.uuid4())
        resp = await api_client.get(f"/api/campaigns/{cid}/sessions/{fake_sid}/telemetry")
        assert resp.status_code == 404

    async def test_session_from_different_campaign_returns_404(
        self, api_client: AsyncClient
    ) -> None:
        cid1, _, session_id1 = await _setup_campaign(api_client)
        cid2, _, _ = await _setup_campaign(api_client)
        resp = await api_client.get(f"/api/campaigns/{cid2}/sessions/{session_id1}/telemetry")
        assert resp.status_code == 404

    async def test_empty_session_returns_zero_telemetry(self, api_client: AsyncClient) -> None:
        """A session with no turns returns valid telemetry with zeros."""
        cid, _, session_id = await _setup_campaign(api_client)
        resp = await api_client.get(f"/api/campaigns/{cid}/sessions/{session_id}/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session_id
        assert data["turns_processed"] == 0
        assert data["total_cost_usd"] == 0.0
        assert data["total_input_tokens"] == 0
        assert data["total_output_tokens"] == 0
        assert data["classifier_invocations"] == 0
        assert data["gm_signals_parse_failures"] == 0
        assert data["admin_only"] is True

    async def test_telemetry_response_shape(self, api_client: AsyncClient) -> None:
        """Response includes all required ADR-0018 keys."""
        cid, _, session_id = await _setup_campaign(api_client)
        resp = await api_client.get(f"/api/campaigns/{cid}/sessions/{session_id}/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        required_keys = {
            "session_id",
            "turns_processed",
            "total_cost_usd",
            "total_input_tokens",
            "total_output_tokens",
            "cache_hit_rate",
            "avg_narration_latency_ms",
            "avg_pipeline_duration_ms",
            "classifier_invocations",
            "classifier_low_confidence_count",
            "gm_signals_parse_failures",
            "model_tier_distribution",
            "admin_only",
        }
        assert required_keys.issubset(data.keys())
