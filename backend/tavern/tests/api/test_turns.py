"""Tests for turn submission and retrieval endpoints."""

from __future__ import annotations

from httpx import AsyncClient

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


async def _setup_active_campaign(client: AsyncClient) -> tuple[str, str]:
    """Create a campaign + character + session. Returns (campaign_id, character_id)."""
    campaign = (await client.post("/api/campaigns", json={"name": "Test"})).json()
    cid = campaign["id"]

    char = (await client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)).json()
    char_id = char["id"]

    await client.post(f"/api/campaigns/{cid}/sessions")
    return cid, char_id


# ---------------------------------------------------------------------------
# Submit turn
# ---------------------------------------------------------------------------


class TestSubmitTurn:
    async def test_submit_turn_returns_202(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        response = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I attack the goblin"},
        )
        assert response.status_code == 202

    async def test_submit_turn_returns_sequence_number(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        body = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "I look around"},
            )
        ).json()
        assert body["sequence_number"] == 1

    async def test_sequence_numbers_increment(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        first = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "First action"},
            )
        ).json()
        second = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "Second action"},
            )
        ).json()
        assert first["sequence_number"] == 1
        assert second["sequence_number"] == 2

    async def test_submit_turn_has_turn_id(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        body = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "I look around"},
            )
        ).json()
        assert "turn_id" in body

    async def test_submit_turn_on_paused_campaign_returns_409(
        self, api_client: AsyncClient
    ) -> None:
        """Campaign must be active to accept turns."""
        cid, char_id = await _setup_active_campaign(api_client)
        await api_client.post(f"/api/campaigns/{cid}/sessions/end")

        response = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I attack"},
        )
        assert response.status_code == 409

    async def test_submit_turn_with_character_from_wrong_campaign_returns_400(
        self, api_client: AsyncClient
    ) -> None:
        """Character must belong to the campaign in the URL."""
        cid_a, char_id_a = await _setup_active_campaign(api_client)
        cid_b, _ = await _setup_active_campaign(api_client)

        response = await api_client.post(
            f"/api/campaigns/{cid_b}/turns",
            json={"character_id": char_id_a, "action": "I attack"},
        )
        assert response.status_code == 400

    async def test_turn_persisted_in_database(self, api_client: AsyncClient) -> None:
        """Submitted turn must be retrievable via GET /turns."""
        cid, char_id = await _setup_active_campaign(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I search the room"},
        )

        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        assert turns["total"] == 1
        assert turns["turns"][0]["player_action"] == "I search the room"

    async def test_narrator_stream_called_with_action(
        self, api_client: AsyncClient, mock_narrator
    ) -> None:
        """narrate_turn_stream must be invoked (background task uses it, not narrate_turn)."""

        called_with: list = []
        original_stream = mock_narrator.narrate_turn_stream

        async def tracking_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
            called_with.append((args, kwargs))
            async for chunk in original_stream(*args, **kwargs):
                yield chunk

        mock_narrator.narrate_turn_stream = tracking_stream

        cid, char_id = await _setup_active_campaign(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I open the door"},
        )
        assert len(called_with) == 1

    async def test_campaign_not_found_returns_404(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/turns",
            json={"character_id": "00000000-0000-0000-0000-000000000001", "action": "go"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# List and get turns
# ---------------------------------------------------------------------------


class TestListTurns:
    async def test_list_turns_returns_paginated_results(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        for i in range(3):
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": f"Action {i + 1}"},
            )

        response = await api_client.get(f"/api/campaigns/{cid}/turns")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["turns"]) == 3

    async def test_list_turns_ordered_by_sequence(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        for action in ["First", "Second", "Third"]:
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": action},
            )

        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()["turns"]
        seq_numbers = [t["sequence_number"] for t in turns]
        assert seq_numbers == sorted(seq_numbers)

    async def test_list_turns_empty_for_new_campaign(self, api_client: AsyncClient) -> None:
        cid, _ = await _setup_active_campaign(api_client)
        response = await api_client.get(f"/api/campaigns/{cid}/turns")
        body = response.json()
        assert body["total"] == 0
        assert body["turns"] == []

    async def test_list_turns_pagination(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        for i in range(5):
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": f"Action {i + 1}"},
            )

        page_1 = (await api_client.get(f"/api/campaigns/{cid}/turns?page=1&page_size=3")).json()
        page_2 = (await api_client.get(f"/api/campaigns/{cid}/turns?page=2&page_size=3")).json()

        assert len(page_1["turns"]) == 3
        assert len(page_2["turns"]) == 2
        assert page_1["total"] == 5

    async def test_get_single_turn(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_active_campaign(api_client)
        created = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "I search"},
            )
        ).json()

        response = await api_client.get(f"/api/campaigns/{cid}/turns/{created['turn_id']}")
        assert response.status_code == 200
        assert response.json()["player_action"] == "I search"
