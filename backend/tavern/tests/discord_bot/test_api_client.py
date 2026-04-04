"""Tests for TavernAPI — mock httpx, verify correct URLs/methods/bodies."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tavern.discord_bot.services.api_client import TavernAPI, TavernAPIError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CAMPAIGN_ID = str(uuid.uuid4())
CHARACTER_ID = str(uuid.uuid4())
TURN_ID = str(uuid.uuid4())
ROLL_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def ok(body: Any = None) -> MagicMock:
    """Build a mock 200 httpx response."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body if body is not None else {}
    r.text = str(body)
    return r


def err(status: int, message: str = "error") -> MagicMock:
    """Build a mock error httpx response."""
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"message": message}
    r.text = message
    return r


@pytest.fixture
def api() -> TavernAPI:
    return TavernAPI("http://localhost:8000")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_calls_health_endpoint(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"status": "ok"}))
        await api.health_check()
        api._client.get.assert_called_once_with("/health")

    async def test_returns_json_body(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"status": "ok"}))
        result = await api.health_check()
        assert result == {"status": "ok"}

    async def test_raises_on_503(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=err(503, "service unavailable"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.health_check()
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class TestListCampaigns:
    async def test_calls_correct_url(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok([]))
        await api.list_campaigns()
        api._client.get.assert_called_once_with("/api/campaigns")


class TestCreateCampaign:
    async def test_posts_to_campaigns(self, api: TavernAPI) -> None:
        data = {"name": "Shattered Coast"}
        api._client.post = AsyncMock(return_value=ok({"id": CAMPAIGN_ID}))
        await api.create_campaign(data)
        api._client.post.assert_called_once_with("/api/campaigns", json=data)

    async def test_returns_created_campaign(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({"id": CAMPAIGN_ID, "name": "X"}))
        result = await api.create_campaign({"name": "X"})
        assert result["id"] == CAMPAIGN_ID


class TestGetCampaign:
    async def test_calls_correct_url(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"id": CAMPAIGN_ID}))
        await api.get_campaign(CAMPAIGN_ID)
        api._client.get.assert_called_once_with(f"/api/campaigns/{CAMPAIGN_ID}")

    async def test_accepts_uuid_type(self, api: TavernAPI) -> None:
        cid = uuid.UUID(CAMPAIGN_ID)
        api._client.get = AsyncMock(return_value=ok({"id": CAMPAIGN_ID}))
        await api.get_campaign(cid)
        api._client.get.assert_called_once_with(f"/api/campaigns/{CAMPAIGN_ID}")

    async def test_raises_404(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=err(404, "Not found"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.get_campaign(CAMPAIGN_ID)
        assert exc_info.value.status_code == 404


class TestGetCampaignConfig:
    async def test_calls_correct_url(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"rolling_mode": "interactive"}))
        await api.get_campaign_config(CAMPAIGN_ID)
        api._client.get.assert_called_once_with(f"/api/campaigns/{CAMPAIGN_ID}/config")


class TestPatchCampaignConfig:
    async def test_calls_patch_with_settings(self, api: TavernAPI) -> None:
        settings = {"rolling_mode": "hybrid", "reaction_window": 10}
        api._client.patch = AsyncMock(return_value=ok(settings))
        await api.patch_campaign_config(CAMPAIGN_ID, settings)
        api._client.patch.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/config", json=settings
        )

    async def test_raises_422_on_invalid_value(self, api: TavernAPI) -> None:
        api._client.patch = AsyncMock(return_value=err(422, "Invalid value"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.patch_campaign_config(CAMPAIGN_ID, {"turn_timeout": 5})
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------


class TestSubmitTurn:
    async def test_posts_correct_body(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({"turn_id": TURN_ID}))
        await api.submit_turn(CAMPAIGN_ID, CHARACTER_ID, "I attack the goblin")
        api._client.post.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/turns",
            json={"character_id": CHARACTER_ID, "action": "I attack the goblin"},
        )


class TestGetTurnHistory:
    async def test_passes_limit_param(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"turns": []}))
        await api.get_turn_history(CAMPAIGN_ID, limit=10)
        api._client.get.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/turns", params={"limit": 10}
        )

    async def test_default_limit_is_5(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"turns": []}))
        await api.get_turn_history(CAMPAIGN_ID)
        _, kwargs = api._client.get.call_args
        assert kwargs["params"]["limit"] == 5


# ---------------------------------------------------------------------------
# Rolls  (ADR-0009)
# ---------------------------------------------------------------------------


class TestExecuteRoll:
    async def test_posts_to_execute_url(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({"roll_id": ROLL_ID}))
        await api.execute_roll(CAMPAIGN_ID, TURN_ID, ROLL_ID)
        expected_url = f"/api/campaigns/{CAMPAIGN_ID}/turns/{TURN_ID}/rolls/{ROLL_ID}/execute"
        api._client.post.assert_called_once_with(expected_url, json={"pre_roll_options": []})

    async def test_passes_pre_roll_options(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({}))
        await api.execute_roll(CAMPAIGN_ID, TURN_ID, ROLL_ID, ["reckless_attack"])
        _, kwargs = api._client.post.call_args
        assert kwargs["json"]["pre_roll_options"] == ["reckless_attack"]

    async def test_empty_options_by_default(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({}))
        await api.execute_roll(CAMPAIGN_ID, TURN_ID, ROLL_ID)
        _, kwargs = api._client.post.call_args
        assert kwargs["json"]["pre_roll_options"] == []


class TestSubmitReaction:
    async def test_posts_to_react_url(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({}))
        await api.submit_reaction(CAMPAIGN_ID, TURN_ID, ROLL_ID, CHARACTER_ID, "shield_spell")
        expected_url = f"/api/campaigns/{CAMPAIGN_ID}/turns/{TURN_ID}/rolls/{ROLL_ID}/react"
        api._client.post.assert_called_once_with(
            expected_url,
            json={"character_id": CHARACTER_ID, "reaction_id": "shield_spell"},
        )


class TestSubmitPass:
    async def test_posts_to_pass_url(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({}))
        await api.submit_pass(CAMPAIGN_ID, TURN_ID, ROLL_ID, CHARACTER_ID)
        expected_url = f"/api/campaigns/{CAMPAIGN_ID}/turns/{TURN_ID}/rolls/{ROLL_ID}/pass"
        api._client.post.assert_called_once_with(expected_url, json={"character_id": CHARACTER_ID})


class TestStandaloneRoll:
    async def test_posts_expression(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({"result": 12}))
        await api.standalone_roll(CAMPAIGN_ID, "2d6+3")
        api._client.post.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/rolls/standalone",
            json={"expression": "2d6+3"},
        )


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


class TestGetCharacters:
    async def test_calls_correct_url(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok([]))
        await api.get_characters(CAMPAIGN_ID)
        api._client.get.assert_called_once_with(f"/api/campaigns/{CAMPAIGN_ID}/characters")


class TestCreateCharacter:
    async def test_posts_data(self, api: TavernAPI) -> None:
        char_data = {"name": "Kael", "class_name": "Fighter"}
        api._client.post = AsyncMock(return_value=ok({"id": CHARACTER_ID}))
        await api.create_character(CAMPAIGN_ID, char_data)
        api._client.post.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/characters", json=char_data
        )


class TestGetCharacter:
    async def test_calls_correct_url(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=ok({"id": CHARACTER_ID}))
        await api.get_character(CAMPAIGN_ID, CHARACTER_ID)
        api._client.get.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/characters/{CHARACTER_ID}"
        )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


class TestInvitePlayer:
    async def test_posts_user_id(self, api: TavernAPI) -> None:
        api._client.post = AsyncMock(return_value=ok({}))
        await api.invite_player(CAMPAIGN_ID, USER_ID)
        api._client.post.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/members",
            json={"user_id": USER_ID},
        )


class TestRemovePlayer:
    async def test_calls_delete(self, api: TavernAPI) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        api._client.delete = AsyncMock(return_value=mock_resp)
        await api.remove_player(CAMPAIGN_ID, USER_ID)
        api._client.delete.assert_called_once_with(
            f"/api/campaigns/{CAMPAIGN_ID}/members/{USER_ID}"
        )

    async def test_raises_on_403(self, api: TavernAPI) -> None:
        api._client.delete = AsyncMock(return_value=err(403, "Forbidden"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.remove_player(CAMPAIGN_ID, USER_ID)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_extracts_message_from_json(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=err(404, "Campaign not found"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.health_check()
        assert exc_info.value.message == "Campaign not found"

    async def test_falls_back_to_text_when_no_json(self, api: TavernAPI) -> None:
        r = MagicMock()
        r.status_code = 500
        r.json.side_effect = ValueError("not json")
        r.text = "Internal Server Error"
        api._client.get = AsyncMock(return_value=r)
        with pytest.raises(TavernAPIError) as exc_info:
            await api.health_check()
        assert "Internal Server Error" in exc_info.value.message

    async def test_error_str_includes_status_and_message(self, api: TavernAPI) -> None:
        api._client.get = AsyncMock(return_value=err(404, "Not found"))
        with pytest.raises(TavernAPIError) as exc_info:
            await api.health_check()
        assert "404" in str(exc_info.value)
        assert "Not found" in str(exc_info.value)
