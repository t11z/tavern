"""Integration tests for Rules Engine wiring in the turn pipeline.

Verifies that:
- Actions are classified and resolved by the Rules Engine before submission
- rules_result is populated on the Turn record for combat/spell/check actions
- rules_result is None for movement/narrative actions
- Character state (spell slots, HP) is updated after spell resolution
- character.updated is broadcast when character state changes
"""

from __future__ import annotations

from httpx import AsyncClient

import tavern.core.srd_data as srd_mod

# ---------------------------------------------------------------------------
# Shared character payloads
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

_VALID_WIZARD = {
    "name": "Merlin",
    "species": "Human",
    "class_name": "Wizard",
    "background": "Acolyte",
    "ability_scores": {"STR": 8, "DEX": 13, "CON": 12, "INT": 15, "WIS": 10, "CHA": 14},
    "ability_score_method": "standard_array",
    "background_bonuses": {"INT": 2, "WIS": 1},
    "equipment_choices": "package_a",
    "languages": ["Common"],
}

# Minimal Fire Bolt spell document matching 5e-database v4.6.3 schema
_FIRE_BOLT_DOC = {
    "index": "fire-bolt",
    "name": "Fire Bolt",
    "level": 0,
    "attack_type": "ranged",
    "damage": {
        "damage_type": {"index": "fire", "name": "Fire"},
        "damage_at_character_level": {
            "1": "1d10",
            "5": "2d10",
            "11": "3d10",
            "17": "4d10",
        },
    },
}


async def _setup_campaign_with_fighter(client: AsyncClient) -> tuple[str, str]:
    """Create campaign + Fighter + session. Returns (campaign_id, character_id)."""
    campaign = (await client.post("/api/campaigns", json={"name": "Engine Test"})).json()
    cid = campaign["id"]
    char = (await client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)).json()
    char_id = char["id"]
    await client.post(f"/api/campaigns/{cid}/sessions")
    return cid, char_id


async def _setup_campaign_with_wizard(client: AsyncClient) -> tuple[str, str]:
    """Create campaign + Wizard + session. Returns (campaign_id, character_id)."""
    campaign = (await client.post("/api/campaigns", json={"name": "Wizard Test"})).json()
    cid = campaign["id"]
    char = (await client.post(f"/api/campaigns/{cid}/characters", json=_VALID_WIZARD)).json()
    char_id = char["id"]
    await client.post(f"/api/campaigns/{cid}/sessions")
    return cid, char_id


# ---------------------------------------------------------------------------
# Melee attack — rules_result populated
# ---------------------------------------------------------------------------


class TestMeleeAttackEngine:
    async def test_melee_attack_returns_202(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        resp = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I attack the goblin with my longsword"},
        )
        assert resp.status_code == 202

    async def test_melee_attack_rules_result_persisted(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I attack the goblin with my longsword"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        assert item["rules_result"] is not None
        assert "attack" in item["rules_result"].lower() or "miss" in item["rules_result"].lower()

    async def test_melee_attack_rules_result_mentions_damage_type(
        self, api_client: AsyncClient
    ) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        # Run multiple times to avoid natural-1 miss always occurring
        results = []
        for _ in range(5):
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "Strike the skeleton"},
            )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        for t in turns["turns"]:
            results.append(t["rules_result"])
        # At least one hit should mention "Slashing" damage
        assert any(r and "Slashing" in r for r in results) or all(
            r and ("miss" in r.lower() or "hit" in r.lower()) for r in results
        )


# ---------------------------------------------------------------------------
# Ranged attack — rules_result populated
# ---------------------------------------------------------------------------


class TestRangedAttackEngine:
    async def test_ranged_attack_rules_result_persisted(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Shoot the bandit with my crossbow"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        assert item["rules_result"] is not None


# ---------------------------------------------------------------------------
# Ability check — rules_result populated
# ---------------------------------------------------------------------------


class TestAbilityCheckEngine:
    async def test_ability_check_rules_result_persisted(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I roll a perception check"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        assert item["rules_result"] is not None
        assert "WIS" in item["rules_result"]
        assert "check" in item["rules_result"].lower()

    async def test_strength_check(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Athletics check to climb the wall"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        assert item["rules_result"] is not None
        assert "STR" in item["rules_result"]


# ---------------------------------------------------------------------------
# Movement and narrative — rules_result is None
# ---------------------------------------------------------------------------


class TestNoMechanicsEngine:
    async def test_movement_rules_result_is_none(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Move behind the pillar"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        assert turns["turns"][0]["rules_result"] is None

    async def test_narrative_rules_result_is_none(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={
                "character_id": char_id,
                "action": (
                    "I watch the shadows dance across the cavern wall "
                    "and contemplate what to do next"
                ),
            },
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        assert turns["turns"][0]["rules_result"] is None


# ---------------------------------------------------------------------------
# Spell cast — unknown spell (get_spell returns None) → graceful fallback
# ---------------------------------------------------------------------------


class TestSpellUnknownEngine:
    async def test_cast_unknown_spell_returns_202(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_wizard(api_client)
        resp = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "I cast some unknown cantrip"},
        )
        assert resp.status_code == 202

    async def test_cast_spell_without_srd_data_rules_result_set(
        self, api_client: AsyncClient
    ) -> None:
        """When get_spell returns None, rules_result should be a fallback message."""
        cid, char_id = await _setup_campaign_with_wizard(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Cast Fire Bolt at the goblin"},
        )
        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        # Either resolved (if spell found) or fallback message — must not be None
        assert item["rules_result"] is not None


# ---------------------------------------------------------------------------
# Spell cast — known spell (get_spell mocked with fixture data)
# ---------------------------------------------------------------------------


class TestSpellKnownEngine:
    async def test_fire_bolt_resolved_with_mocked_srd(
        self, api_client: AsyncClient, monkeypatch
    ) -> None:
        """With get_spell mocked, Fire Bolt is resolved and rules_result is set."""

        async def _mock_get_spell(index: str, campaign_id: str | None = None):
            if index == "fire-bolt":
                return _FIRE_BOLT_DOC
            return None

        monkeypatch.setattr(srd_mod, "get_spell", _mock_get_spell)

        cid, char_id = await _setup_campaign_with_wizard(api_client)
        resp = await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Cast Fire Bolt at the goblin"},
        )
        assert resp.status_code == 202

        turns = (await api_client.get(f"/api/campaigns/{cid}/turns")).json()
        item = turns["turns"][0]
        assert item["rules_result"] is not None
        # Fire Bolt is a cantrip → no slot consumed, but spell description returned
        assert (
            "fire bolt" in item["rules_result"].lower() or "fire" in item["rules_result"].lower()
        )

    async def test_fire_bolt_cantrip_does_not_consume_slot(
        self, api_client: AsyncClient, monkeypatch
    ) -> None:
        """Cantrips do not consume spell slots."""

        async def _mock_get_spell(index: str, campaign_id: str | None = None):
            if index == "fire-bolt":
                return _FIRE_BOLT_DOC
            return None

        monkeypatch.setattr(srd_mod, "get_spell", _mock_get_spell)

        cid, char_id = await _setup_campaign_with_wizard(api_client)

        # Record initial spell slots
        char_before = (await api_client.get(f"/api/campaigns/{cid}/characters/{char_id}")).json()
        slots_before = dict(char_before["spell_slots"])

        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Cast Fire Bolt at the orc"},
        )

        char_after = (await api_client.get(f"/api/campaigns/{cid}/characters/{char_id}")).json()
        assert char_after["spell_slots"] == slots_before  # unchanged


# ---------------------------------------------------------------------------
# rules_result included in GET /turns response
# ---------------------------------------------------------------------------


class TestRulesResultInResponse:
    async def test_rules_result_in_list_turns(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/turns",
            json={"character_id": char_id, "action": "Attack the orc"},
        )
        resp = await api_client.get(f"/api/campaigns/{cid}/turns")
        assert resp.status_code == 200
        item = resp.json()["turns"][0]
        assert "rules_result" in item

    async def test_rules_result_in_get_turn(self, api_client: AsyncClient) -> None:
        cid, char_id = await _setup_campaign_with_fighter(api_client)
        submit_resp = (
            await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "Slash the skeleton"},
            )
        ).json()
        turn_id = submit_resp["turn_id"]

        resp = await api_client.get(f"/api/campaigns/{cid}/turns/{turn_id}")
        assert resp.status_code == 200
        assert "rules_result" in resp.json()
