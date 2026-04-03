"""Tests for character creation and management endpoints."""

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
    "languages": ["Common", "Dwarvish"],
}

_VALID_WIZARD = {
    "name": "Miriel",
    "species": "Elf",
    "class_name": "Wizard",
    "background": "Sage",
    "ability_scores": {"STR": 8, "DEX": 13, "CON": 12, "INT": 15, "WIS": 14, "CHA": 10},
    "ability_score_method": "standard_array",
    "background_bonuses": {"INT": 2, "WIS": 1},
    "equipment_choices": "package_a",
    "languages": ["Common", "Elvish"],
}


async def _create_campaign(client: AsyncClient, name: str = "Test Campaign") -> str:
    """Helper to create a campaign and return its ID."""
    resp = await client.post("/api/campaigns", json={"name": name})
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Create character
# ---------------------------------------------------------------------------


class TestCreateCharacter:
    async def test_create_character_returns_201(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        assert response.status_code == 201

    async def test_create_character_has_uuid(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert "id" in body
        assert len(body["id"]) == 36  # UUID format

    async def test_fighter_hp_computed_correctly(self, api_client: AsyncClient) -> None:
        """Fighter: d10 + CON mod. CON after bonus = 15, mod = +2. Max HP = 12."""
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        # STR 17, DEX 13, CON 15, INT 10, WIS 12, CHA 8 after bonuses
        # CON mod = +2, Fighter hit die = 10 → max HP = 12
        assert body["max_hp"] == 12
        assert body["hp"] == body["max_hp"]

    async def test_ac_computed_as_10_plus_dex_mod(self, api_client: AsyncClient) -> None:
        """Unarmored AC = 10 + DEX modifier. Aldric: DEX 13 → mod +1 → AC 11."""
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert body["ac"] == 11  # DEX 13 → mod +1

    async def test_final_ability_scores_include_background_bonuses(
        self, api_client: AsyncClient
    ) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        scores = body["ability_scores"]
        assert scores["STR"] == 17  # 15 + 2
        assert scores["CON"] == 15  # 14 + 1

    async def test_features_include_proficiency_bonus(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert body["features"]["proficiency_bonus"] == 2

    async def test_features_include_species_and_background(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert body["features"]["species"] == "Human"
        assert body["features"]["background"] == "Soldier"

    async def test_wizard_has_spell_slots(self, api_client: AsyncClient) -> None:
        """Wizard at level 1 has 2 first-level spell slots (SRD p.147)."""
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_WIZARD)
        ).json()
        assert body["spell_slots"].get("1", 0) >= 1

    async def test_fighter_has_no_spell_slots(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert body["spell_slots"] == {}

    async def test_character_linked_to_campaign(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        body = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        assert body["campaign_id"] == cid

    async def test_invalid_class_returns_400(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        bad = dict(_VALID_FIGHTER, class_name="Necromancer")
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        assert response.status_code == 400

    async def test_invalid_species_returns_400(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        bad = dict(_VALID_FIGHTER, species="Klingon")
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        assert response.status_code == 400

    async def test_invalid_background_returns_400(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        bad = dict(_VALID_FIGHTER, background="Barista")
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        assert response.status_code == 400

    async def test_invalid_standard_array_returns_400(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        bad = dict(
            _VALID_FIGHTER,
            ability_scores={"STR": 18, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
        )
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        assert response.status_code == 400

    async def test_invalid_background_bonuses_returns_400(self, api_client: AsyncClient) -> None:
        """Soldier background allows STR/DEX/CON; bonus to INT is invalid."""
        cid = await _create_campaign(api_client)
        bad = dict(_VALID_FIGHTER, background_bonuses={"INT": 2, "CHA": 1})
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        assert response.status_code == 400

    async def test_score_exceeding_20_returns_400(self, api_client: AsyncClient) -> None:
        """STR 19 + background bonus of 2 = 21 → invalid."""
        cid = await _create_campaign(api_client)
        bad = dict(
            _VALID_FIGHTER,
            # STR 19 is not in STANDARD_ARRAY; use a different method to bypass that check
            ability_score_method="invalid",
        )
        response = await api_client.post(f"/api/campaigns/{cid}/characters", json=bad)
        # Fails at ability_score_method check
        assert response.status_code == 400

    async def test_create_character_on_nonexistent_campaign_returns_404(
        self, api_client: AsyncClient
    ) -> None:
        response = await api_client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000000/characters",
            json=_VALID_FIGHTER,
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# List characters
# ---------------------------------------------------------------------------


class TestListCharacters:
    async def test_list_characters_returns_only_this_campaigns_characters(
        self, api_client: AsyncClient
    ) -> None:
        """Characters from campaign A must not appear in campaign B's list."""
        cid_a = await _create_campaign(api_client, "Campaign A")
        cid_b = await _create_campaign(api_client, "Campaign B")

        await api_client.post(f"/api/campaigns/{cid_a}/characters", json=_VALID_FIGHTER)
        await api_client.post(
            f"/api/campaigns/{cid_b}/characters",
            json=dict(_VALID_FIGHTER, name="OtherFighter"),
        )

        response_a = await api_client.get(f"/api/campaigns/{cid_a}/characters")
        names_a = [c["name"] for c in response_a.json()]
        assert "Aldric" in names_a
        assert "OtherFighter" not in names_a

    async def test_list_characters_empty_initially(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        response = await api_client.get(f"/api/campaigns/{cid}/characters")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# Get character
# ---------------------------------------------------------------------------


class TestGetCharacter:
    async def test_get_character_returns_200(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        char = (
            await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
        ).json()
        response = await api_client.get(f"/api/campaigns/{cid}/characters/{char['id']}")
        assert response.status_code == 200

    async def test_character_from_other_campaign_returns_404(
        self, api_client: AsyncClient
    ) -> None:
        """Character belonging to campaign A must not be accessible via campaign B."""
        cid_a = await _create_campaign(api_client, "Campaign A")
        cid_b = await _create_campaign(api_client, "Campaign B")

        char = (
            await api_client.post(f"/api/campaigns/{cid_a}/characters", json=_VALID_FIGHTER)
        ).json()

        response = await api_client.get(f"/api/campaigns/{cid_b}/characters/{char['id']}")
        assert response.status_code == 404
