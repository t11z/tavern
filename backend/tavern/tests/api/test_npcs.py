"""Tests for NPC persistence layer (ADR-0013).

Covers:
- NPC model creation (predefined, narrator_spawned)
- validate_immutable_update classmethod
- PATCH endpoint immutability enforcement (422 for immutable fields)
- PATCH endpoint success for mutable fields
- resolve_npc_stat_block (mocked get_monster)
- StateSnapshot NPC serialization — exploration and combat modes
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import tavern.core.srd_data as srd_mod
from tavern.dm.context_builder import (
    CharacterState,
    SceneContext,
    StateSnapshot,
    TurnContext,
    _serialize_npc_compact,
    _serialize_npcs,
    build_snapshot,
    serialize_snapshot,
)
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.npc import NPC

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _campaign(**kwargs) -> Campaign:
    return Campaign(
        id=uuid.uuid4(),
        name=kwargs.get("name", "Test Campaign"),
        status="active",
        dm_persona=None,
        world_seed=None,
    )


def _campaign_state(campaign_id: uuid.UUID, **kwargs) -> CampaignState:
    return CampaignState(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        rolling_summary="The party rests.",
        scene_context="A dimly lit tavern.",
        world_state={
            "location": "The Rusty Flagon",
            "time_of_day": "night",
            "environment": "dim",
            "npcs": [],
            "threats": [],
            **kwargs,
        },
        turn_count=5,
    )


async def _create_campaign(client: AsyncClient, name: str = "NPC Test Campaign") -> str:
    resp = await client.post("/api/campaigns", json={"name": name})
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# 1. NPC Model — creation with origin="predefined"
# ---------------------------------------------------------------------------


class TestNPCModelPredefined:
    def test_create_predefined_npc(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Barkeep Harold",
            origin="predefined",
            status="alive",
            disposition="unknown",
            plot_significant=False,
        )
        assert npc.name == "Barkeep Harold"
        assert npc.origin == "predefined"
        assert npc.status == "alive"
        assert npc.disposition == "unknown"
        assert npc.plot_significant is False

    def test_predefined_npc_optional_fields(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Guard Captain",
            origin="predefined",
            species="Human",
            appearance="Tall, scarred face",
            role="City Guard",
            disposition="neutral",
            hp_current=30,
            hp_max=30,
            ac=16,
        )
        assert npc.species == "Human"
        assert npc.role == "City Guard"
        assert npc.hp_current == 30
        assert npc.ac == 16


# ---------------------------------------------------------------------------
# 2. NPC Model — creation with origin="narrator_spawned"
# ---------------------------------------------------------------------------


class TestNPCModelNarratorSpawned:
    def test_create_narrator_spawned_npc(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Mysterious Stranger",
            origin="narrator_spawned",
            disposition="unknown",
        )
        assert npc.origin == "narrator_spawned"
        assert npc.name == "Mysterious Stranger"

    def test_narrator_spawned_with_stat_block_ref(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Goblin Scout",
            origin="narrator_spawned",
            stat_block_ref="goblin",
            creature_type="humanoid",
        )
        assert npc.stat_block_ref == "goblin"
        assert npc.creature_type == "humanoid"


# ---------------------------------------------------------------------------
# 3. validate_immutable_update — immutable field detection
# ---------------------------------------------------------------------------


class TestValidateImmutableUpdate:
    def test_raises_when_name_in_updates(self) -> None:
        with pytest.raises(ValueError, match="name"):
            NPC.validate_immutable_update({"name": "New Name"})

    def test_raises_when_species_in_updates(self) -> None:
        with pytest.raises(ValueError, match="species"):
            NPC.validate_immutable_update({"species": "Elf"})

    def test_raises_when_appearance_in_updates(self) -> None:
        with pytest.raises(ValueError, match="appearance"):
            NPC.validate_immutable_update({"appearance": "Changed look"})

    def test_does_not_raise_for_motivation(self) -> None:
        NPC.validate_immutable_update({"motivation": "Protect the town"})

    def test_does_not_raise_for_disposition(self) -> None:
        NPC.validate_immutable_update({"disposition": "friendly"})

    def test_does_not_raise_for_status(self) -> None:
        NPC.validate_immutable_update({"status": "dead"})

    def test_does_not_raise_for_empty_dict(self) -> None:
        NPC.validate_immutable_update({})

    def test_does_not_raise_for_multiple_mutable_fields(self) -> None:
        NPC.validate_immutable_update(
            {"motivation": "Gold", "disposition": "hostile", "hp_current": 10}
        )

    def test_raises_mentions_all_forbidden_fields(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            NPC.validate_immutable_update({"name": "X", "species": "Y"})
        msg = str(exc_info.value)
        assert "name" in msg
        assert "species" in msg


# ---------------------------------------------------------------------------
# 4. PATCH endpoint — 422 for immutable fields
# ---------------------------------------------------------------------------


class TestPatchNPCImmutableFields:
    async def test_patch_with_name_returns_422(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        # Create NPC
        npc_resp = await api_client.post(
            f"/api/campaigns/{cid}/npcs",
            json={"name": "Original Name"},
        )
        assert npc_resp.status_code == 201
        npc_id = npc_resp.json()["id"]

        response = await api_client.patch(
            f"/api/campaigns/{cid}/npcs/{npc_id}",
            json={"name": "Renamed"},
        )
        assert response.status_code == 422

    async def test_patch_with_species_returns_422(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        npc_resp = await api_client.post(
            f"/api/campaigns/{cid}/npcs",
            json={"name": "An NPC", "species": "Dwarf"},
        )
        npc_id = npc_resp.json()["id"]

        response = await api_client.patch(
            f"/api/campaigns/{cid}/npcs/{npc_id}",
            json={"species": "Elf"},
        )
        assert response.status_code == 422

    async def test_patch_with_mutable_fields_returns_200(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        npc_resp = await api_client.post(
            f"/api/campaigns/{cid}/npcs",
            json={"name": "The Innkeeper"},
        )
        npc_id = npc_resp.json()["id"]

        response = await api_client.patch(
            f"/api/campaigns/{cid}/npcs/{npc_id}",
            json={"disposition": "friendly", "motivation": "Wants peace"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["disposition"] == "friendly"
        assert body["motivation"] == "Wants peace"
        # Immutable fields unchanged
        assert body["name"] == "The Innkeeper"


# ---------------------------------------------------------------------------
# 5. GET /api/campaigns/{id}/npcs — returns 200
# ---------------------------------------------------------------------------


class TestListNPCs:
    async def test_list_npcs_returns_200_for_valid_campaign(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        response = await api_client.get(f"/api/campaigns/{cid}/npcs")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_npcs_returns_created_npc(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        await api_client.post(
            f"/api/campaigns/{cid}/npcs",
            json={"name": "Village Elder"},
        )
        response = await api_client.get(f"/api/campaigns/{cid}/npcs")
        assert response.status_code == 200
        names = [n["name"] for n in response.json()]
        assert "Village Elder" in names

    async def test_list_npcs_status_filter(self, api_client: AsyncClient) -> None:
        cid = await _create_campaign(api_client)
        await api_client.post(f"/api/campaigns/{cid}/npcs", json={"name": "Alive NPC"})
        await api_client.post(
            f"/api/campaigns/{cid}/npcs", json={"name": "Dead NPC", "status": "alive"}
        )
        # Patch second NPC to dead
        all_npcs = (await api_client.get(f"/api/campaigns/{cid}/npcs")).json()
        dead_id = next(n["id"] for n in all_npcs if n["name"] == "Dead NPC")
        await api_client.patch(f"/api/campaigns/{cid}/npcs/{dead_id}", json={"status": "dead"})

        alive_resp = await api_client.get(f"/api/campaigns/{cid}/npcs", params={"status": "alive"})
        assert alive_resp.status_code == 200
        alive_names = [n["name"] for n in alive_resp.json()]
        assert "Alive NPC" in alive_names
        assert "Dead NPC" not in alive_names

    async def test_list_npcs_404_for_unknown_campaign(self, api_client: AsyncClient) -> None:
        response = await api_client.get("/api/campaigns/00000000-0000-0000-0000-000000000000/npcs")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6. resolve_npc_stat_block
# ---------------------------------------------------------------------------


class TestResolveNPCStatBlock:
    async def test_returns_dict_when_stat_block_found(self) -> None:
        mock_stat_block = {"index": "goblin", "name": "Goblin", "hit_points": 7}
        with patch.object(srd_mod, "get_monster", new=AsyncMock(return_value=mock_stat_block)):
            result = await srd_mod.resolve_npc_stat_block("goblin", uuid.uuid4())
        assert result == mock_stat_block

    async def test_returns_none_when_not_found(self) -> None:
        with patch.object(srd_mod, "get_monster", new=AsyncMock(return_value=None)):
            result = await srd_mod.resolve_npc_stat_block("nonexistent", uuid.uuid4())
        assert result is None

    async def test_logs_warning_when_not_found(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with patch.object(srd_mod, "get_monster", new=AsyncMock(return_value=None)):
            with caplog.at_level(logging.WARNING, logger="tavern.core.srd_data"):
                await srd_mod.resolve_npc_stat_block("unknown-monster", uuid.uuid4())
        assert any("not found" in record.message.lower() for record in caplog.records)

    async def test_calls_get_monster_with_str_campaign_id(self) -> None:
        campaign_id = uuid.uuid4()
        with patch.object(
            srd_mod, "get_monster", new=AsyncMock(return_value={"index": "bandit"})
        ) as mock_get:
            await srd_mod.resolve_npc_stat_block("bandit", campaign_id)
        mock_get.assert_called_once_with("bandit", str(campaign_id))


# ---------------------------------------------------------------------------
# 7. Snapshot NPC serialization — exploration mode (no hp/ac)
# ---------------------------------------------------------------------------


class TestSnapshotNPCSerializationExploration:
    def _make_snapshot_with_npcs(self, npcs: list[dict]) -> StateSnapshot:
        return StateSnapshot(
            system_prompt="You are a DM.",
            characters=[
                CharacterState(
                    name="Hero",
                    class_name="Fighter",
                    level=1,
                    hp=10,
                    max_hp=10,
                    ac=12,
                    conditions=[],
                    spell_slots={},
                    key_inventory=[],
                )
            ],
            scene=SceneContext(
                location="Town Square",
                description="Busy market.",
                npcs=[],
                environment="sunny",
                threats=[],
                time_of_day="noon",
            ),
            rolling_summary="",
            current_turn=TurnContext(player_action="Look around.", rules_result=None),
            npcs=npcs,
        )

    def test_exploration_mode_no_hp_ac(self) -> None:
        npc_dict = _serialize_npc_compact(
            NPC(
                campaign_id=uuid.uuid4(),
                name="Merchant",
                origin="predefined",
                role="Trader",
                disposition="friendly",
                status="alive",
                appearance="Stout man",
                hp_current=20,
                hp_max=20,
                ac=10,
            ),
            combat_mode=False,
        )
        assert "hp_current" not in npc_dict
        assert "hp_max" not in npc_dict
        assert "ac" not in npc_dict
        assert npc_dict["name"] == "Merchant"
        assert npc_dict["role"] == "Trader"
        assert npc_dict["disposition"] == "friendly"

    def test_exploration_mode_npc_appears_in_serialized_snapshot(self) -> None:
        npc_dict = {
            "name": "Innkeeper",
            "role": "Host",
            "disposition": "friendly",
            "status": "alive",
            "appearance": "Round belly",
        }
        snapshot = self._make_snapshot_with_npcs([npc_dict])
        result = serialize_snapshot(snapshot)
        content = result["messages"][0]["content"]
        assert "Innkeeper" in content

    def test_exploration_mode_no_combat_stats_in_output(self) -> None:
        npc_dict = {
            "name": "Farmer",
            "role": None,
            "disposition": "neutral",
            "status": "alive",
            "appearance": None,
        }
        snapshot = self._make_snapshot_with_npcs([npc_dict])
        result = serialize_snapshot(snapshot)
        content = result["messages"][0]["content"]
        assert "HP:" not in content
        assert "AC:" not in content


# ---------------------------------------------------------------------------
# 8. Snapshot NPC serialization — combat mode (includes hp/ac for alive NPCs)
# ---------------------------------------------------------------------------


class TestSnapshotNPCSerializationCombat:
    def test_combat_mode_includes_hp_ac_for_alive_npc(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Goblin Warrior",
            origin="narrator_spawned",
            disposition="hostile",
            status="alive",
            hp_current=7,
            hp_max=7,
            ac=15,
        )
        npc_dict = _serialize_npc_compact(npc, combat_mode=True)
        assert npc_dict["hp_current"] == 7
        assert npc_dict["hp_max"] == 7
        assert npc_dict["ac"] == 15

    def test_combat_mode_excludes_hp_ac_for_dead_npc(self) -> None:
        npc = NPC(
            campaign_id=uuid.uuid4(),
            name="Dead Goblin",
            origin="narrator_spawned",
            disposition="hostile",
            status="dead",
            hp_current=0,
            hp_max=7,
            ac=15,
        )
        npc_dict = _serialize_npc_compact(npc, combat_mode=True)
        assert "hp_current" not in npc_dict
        assert "ac" not in npc_dict

    def test_combat_mode_npc_stats_appear_in_serialized_output(self) -> None:
        npc_dict = {
            "name": "Orc Brute",
            "role": "Warrior",
            "disposition": "hostile",
            "status": "alive",
            "appearance": None,
            "hp_current": 15,
            "hp_max": 15,
            "ac": 13,
        }
        snapshot = StateSnapshot(
            system_prompt="DM.",
            characters=[],
            scene=SceneContext(
                location="Dungeon",
                description="Dark cave.",
                npcs=[],
                environment="dark",
                threats=["Orc Brute"],
                time_of_day="unknown",
            ),
            rolling_summary="",
            current_turn=TurnContext(player_action="Attack!", rules_result=None),
            npcs=[npc_dict],
        )
        result = serialize_snapshot(snapshot)
        content = result["messages"][0]["content"]
        assert "Orc Brute" in content
        assert "HP:" in content
        assert "AC:" in content

    def test_serialize_npcs_empty_list_returns_empty_string(self) -> None:
        result = _serialize_npcs([])
        assert result == ""

    def test_serialize_npcs_with_multiple_npcs(self) -> None:
        npcs = [
            {
                "name": "Guard A",
                "role": "Guard",
                "disposition": "hostile",
                "status": "alive",
                "appearance": None,
            },
            {
                "name": "Guard B",
                "role": "Guard",
                "disposition": "hostile",
                "status": "alive",
                "appearance": None,
            },
        ]
        result = _serialize_npcs(npcs)
        assert "Guard A" in result
        assert "Guard B" in result


# ---------------------------------------------------------------------------
# 9. build_snapshot integration — NPCs populated from DB
# ---------------------------------------------------------------------------


class TestBuildSnapshotNPCs:
    async def test_build_snapshot_includes_npcs_in_scene(self, db_session: AsyncSession) -> None:
        """NPCs matching scene_location appear in the snapshot."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()

        state = _campaign_state(campaign.id)
        db_session.add(state)

        npc = NPC(
            campaign_id=campaign.id,
            name="Tavernkeeper",
            origin="predefined",
            disposition="friendly",
            status="alive",
            scene_location="The Rusty Flagon",
        )
        db_session.add(npc)
        await db_session.commit()

        turn = TurnContext(player_action="Look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Tavernkeeper" in npc_names

    async def test_build_snapshot_excludes_dead_non_plot_npcs(
        self, db_session: AsyncSession
    ) -> None:
        """Dead, non-plot-significant NPCs outside the recent window are excluded."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()

        state = _campaign_state(campaign.id)
        db_session.add(state)

        # Dead NPC at a different location, seen 20 turns ago (outside recency window)
        dead_npc = NPC(
            campaign_id=campaign.id,
            name="Dead Bandit",
            origin="narrator_spawned",
            status="dead",
            plot_significant=False,
            scene_location="Forest Road",
            last_seen_turn=0,
        )
        db_session.add(dead_npc)
        await db_session.commit()

        turn = TurnContext(player_action="Move forward.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Dead Bandit" not in npc_names

    async def test_build_snapshot_includes_plot_significant_dead_npc(
        self, db_session: AsyncSession
    ) -> None:
        """Plot-significant NPCs appear even when dead."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()

        state = _campaign_state(campaign.id)
        db_session.add(state)

        # Dead but plot-significant NPC in the current scene
        dead_plot_npc = NPC(
            campaign_id=campaign.id,
            name="Slain King",
            origin="predefined",
            status="dead",
            plot_significant=True,
            scene_location="The Rusty Flagon",
        )
        db_session.add(dead_plot_npc)
        await db_session.commit()

        turn = TurnContext(player_action="Inspect the body.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Slain King" in npc_names
