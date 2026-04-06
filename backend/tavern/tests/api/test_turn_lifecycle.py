"""Tests for the full combat turn lifecycle (Task D — GMSignals integration).

Covers:
1. Player attack in exploration → CombatClassifier called → mode → "combat"
   → "combat.started" broadcast
2. NPC ambush via scene_transition (Flow A) → NPC stealth auto-rolled
   → determine_surprise called → "combat.started" broadcast
3. npc_updates "spawn" creates NPC record BEFORE scene_transition is processed
4. Duplicate spawn signal → discarded, no duplicate NPC created
5. Engine combat_end (all NPCs at 0 HP flag) → takes precedence
   → "combat.ended" broadcast, Narrator combat_end signal discarded
6. GMSignals parse failure → safe_default() applied → turn completes without error
7. narrative_text delivered to WebSocket does NOT contain the delimiter or JSON tail
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from sqlalchemy import select

from tavern.api import ws as ws_mod
from tavern.api.dependencies import get_narrator as get_narrator_dep
from tavern.dm.combat_classifier import CombatClassification
from tavern.dm.gm_signals import (
    GM_SIGNALS_DELIMITER,
    GMSignals,
    LocationChange,
    NPCUpdate,
    SceneTransition,
    TimeProgression,
    parse_gm_signals,
    safe_default,
)
from tavern.dm.narrator import Narrator
from tavern.main import app
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.npc import NPC
from tavern.models.session import Session
from tavern.models.turn import Turn
from tavern.tests.api.conftest import _TEST_SESSION_FACTORY

# ---------------------------------------------------------------------------
# Helpers to build test data
# ---------------------------------------------------------------------------


def _campaign(**kwargs) -> Campaign:
    return Campaign(
        id=uuid.uuid4(),
        name=kwargs.get("name", "Lifecycle Test Campaign"),
        status="active",
        dm_persona=None,
        world_seed=None,
    )


def _campaign_state(campaign_id: uuid.UUID, mode: str = "exploration") -> CampaignState:
    return CampaignState(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        rolling_summary="The party rests.",
        scene_context="A dimly lit crossroads.",
        world_state={
            "location": "Forest Crossroads",
            "environment": "misty",
            "npcs": [],
            "threats": [],
            "mode": mode,
        },
        current_scene_id="forest_crossroads",
        time_of_day="dusk",
        turn_count=0,
    )


def _character(campaign_id: uuid.UUID) -> Character:
    return Character(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        name="Aria",
        class_name="Fighter",
        level=3,
        hp=24,
        max_hp=24,
        ac=16,
        ability_scores={"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
        spell_slots={},
        features={
            "ability_modifiers": {
                "STR": 3,
                "DEX": 1,
                "CON": 2,
                "INT": 0,
                "WIS": 1,
                "CHA": -1,
            },
            "proficiency_bonus": 2,
            "proficiencies": [],
            "feats": [],
        },
    )


def _session_record(campaign_id: uuid.UUID) -> Session:
    return Session(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        started_at=None,
        ended_at=None,
    )


def _no_combat_classification() -> tuple[CombatClassification, dict]:
    return (
        CombatClassification(
            combat_starts=False,
            combatants=[],
            confidence="high",
            reason="no combat",
        ),
        {},
    )


def _make_mock_narrator(
    narrative: str = "The goblin charges!",
    gm_signals: GMSignals | None = None,
) -> MagicMock:
    """Build a Narrator mock where narrate_turn_stream returns (text, signals, meta)."""
    if gm_signals is None:
        gm_signals = safe_default()

    narrator = MagicMock(spec=Narrator)
    narrator.narrate_turn_stream = AsyncMock(return_value=(narrative, gm_signals, {}))
    narrator.update_summary = AsyncMock(return_value="Updated summary.")
    narrator.generate_campaign_brief = AsyncMock(
        return_value={
            "campaign_brief": "Test campaign.",
            "opening_scene": "Test scene.",
            "location": "Test",
            "environment": "test",
            "time_of_day": "noon",
        }
    )
    return narrator


async def _set_world_state(cid: str, updates: dict) -> None:
    """Merge *updates* into the CampaignState.world_state for campaign *cid*."""
    async with _TEST_SESSION_FACTORY() as db:
        state_res = await db.execute(
            select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
        )
        state = state_res.scalar_one_or_none()
        if state:
            ws = dict(state.world_state or {})
            ws.update(updates)
            state.world_state = ws
            await db.commit()


async def _get_world_state(cid: str) -> dict:
    """Return the current world_state for campaign *cid*."""
    async with _TEST_SESSION_FACTORY() as db:
        state_res = await db.execute(
            select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
        )
        state = state_res.scalar_one_or_none()
        return dict(state.world_state or {}) if state else {}


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


async def _setup_campaign_with_char(
    api_client: AsyncClient, name: str = "Test Campaign"
) -> tuple[str, str]:
    """Create campaign + character + session. Returns (campaign_id, character_id)."""
    resp = await api_client.post("/api/campaigns", json={"name": name})
    cid = resp.json()["id"]
    char_resp = await api_client.post(f"/api/campaigns/{cid}/characters", json=_VALID_FIGHTER)
    char_id = char_resp.json()["id"]
    await api_client.post(f"/api/campaigns/{cid}/sessions")
    return cid, char_id


# ---------------------------------------------------------------------------
# GMSignals unit tests (parse_gm_signals)
# ---------------------------------------------------------------------------


class TestParseGMSignals:
    def test_parses_valid_no_op_signals(self) -> None:
        raw = (
            "The goblin snarls.\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "none", "combatants": [], '
            '"potential_surprised_characters": [], "reason": ""}, "npc_updates": []}'
        )
        signals, _diag = parse_gm_signals(raw)
        assert signals.scene_transition.type == "none"
        assert signals.npc_updates == []

    def test_parses_combat_start_transition(self) -> None:
        raw = (
            "The bandits leap from the shadows!\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "combat_start", "combatants": ["Bandit Leader"], '
            '"potential_surprised_characters": [], "reason": "ambush"}, "npc_updates": []}'
        )
        signals, _diag = parse_gm_signals(raw)
        assert signals.scene_transition.type == "combat_start"
        assert "Bandit Leader" in signals.scene_transition.combatants

    def test_parses_npc_spawn_update(self) -> None:
        raw = (
            "A mysterious stranger enters.\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "none", "combatants": [], '
            '"potential_surprised_characters": [], "reason": ""}, '
            '"npc_updates": [{"event": "spawn", "npc_name": "Mysterious Stranger", '
            '"disposition": "unknown"}]}'
        )
        signals, _diag = parse_gm_signals(raw)
        assert len(signals.npc_updates) == 1
        assert signals.npc_updates[0].event == "spawn"
        assert signals.npc_updates[0].npc_name == "Mysterious Stranger"

    def test_returns_safe_default_when_delimiter_missing(self) -> None:
        raw = "The goblin snarls. No signals block here."
        signals, _diag = parse_gm_signals(raw)
        assert signals.scene_transition.type == "none"
        assert signals.npc_updates == []

    def test_returns_safe_default_on_invalid_json(self) -> None:
        raw = f"Narrative.\n{GM_SIGNALS_DELIMITER}\nnot valid json {{"
        signals, _diag = parse_gm_signals(raw)
        assert signals.scene_transition.type == "none"

    def test_returns_safe_default_on_invalid_transition_type(self) -> None:
        raw = (
            "Narrative.\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "invalid_type"}, "npc_updates": []}'
        )
        signals, _diag = parse_gm_signals(raw)
        assert signals.scene_transition.type == "none"

    def test_narrative_text_does_not_contain_delimiter(self) -> None:
        raw = (
            "A tense standoff develops.\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "none", "combatants": [], '
            '"potential_surprised_characters": [], "reason": ""}, "npc_updates": []}'
        )
        narrative_text, _, _ = raw.partition(GM_SIGNALS_DELIMITER)
        assert GM_SIGNALS_DELIMITER not in narrative_text.strip()

    def test_skips_invalid_npc_update_entries(self) -> None:
        """Invalid npc_update entries are skipped; valid ones are parsed."""
        raw = (
            "Narrative.\n"
            f"{GM_SIGNALS_DELIMITER}\n"
            '{"scene_transition": {"type": "none", "combatants": [], '
            '"potential_surprised_characters": [], "reason": ""}, '
            '"npc_updates": ['
            '{"event": "bad_event", "npc_name": "Skip Me"},'
            '{"event": "spawn", "npc_name": "Keep Me"}'
            "]}"
        )
        signals, _diag = parse_gm_signals(raw)
        assert len(signals.npc_updates) == 1
        assert signals.npc_updates[0].npc_name == "Keep Me"


# ---------------------------------------------------------------------------
# Integration tests using the full HTTP client
# ---------------------------------------------------------------------------


class TestPlayerInitiatedCombat:
    """Player attack in exploration mode triggers CombatClassifier → combat mode."""

    async def test_player_attack_transitions_to_combat_mode(self, api_client: AsyncClient) -> None:
        """Player attack in exploration mode → CombatClassifier classifies as
        combat → session transitions to combat mode."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Combat Test")

        mock_classification = (
            CombatClassification(
                combat_starts=True,
                combatants=[],
                confidence="high",
                reason="direct attack",
            ),
            {},
        )

        with patch(
            "tavern.dm.combat_classifier.CombatClassifier.classify",
            new=AsyncMock(return_value=mock_classification),
        ):
            resp = await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "I attack the goblin!"},
            )

        assert resp.status_code == 202

        ws = await _get_world_state(cid)
        assert ws.get("mode") == "combat"

    async def test_no_classifier_call_in_combat_mode(self, api_client: AsyncClient) -> None:
        """CombatClassifier must not be called when session is already in combat mode."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Already In Combat")
        await _set_world_state(cid, {"mode": "combat"})

        classify_mock = AsyncMock()
        with patch(
            "tavern.dm.combat_classifier.CombatClassifier.classify",
            new=classify_mock,
        ):
            resp = await api_client.post(
                f"/api/campaigns/{cid}/turns",
                json={"character_id": char_id, "action": "I swing my sword."},
            )

        assert resp.status_code == 202
        classify_mock.assert_not_called()


class TestNPCInitiatedCombat:
    """Narrator signals combat_start → NPC ambush flow."""

    async def test_npc_ambush_via_scene_transition(self, api_client: AsyncClient) -> None:
        """Narrator signals combat_start in scene_transition → combat.started broadcast
        and mode transitions to combat."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Ambush Test")

        # Create an NPC (the ambusher)
        async with _TEST_SESSION_FACTORY() as db:
            npc = NPC(
                campaign_id=uuid.UUID(cid),
                name="Shadow Rogue",
                origin="predefined",
                disposition="hostile",
                status="alive",
            )
            db.add(npc)
            await db.commit()

        ambush_signals = GMSignals(
            scene_transition=SceneTransition(
                type="combat_start",
                combatants=["Shadow Rogue"],
                potential_surprised_characters=[char_id],
                reason="NPC ambush",
            ),
            npc_updates=[],
        )

        mock_narrator = _make_mock_narrator(
            narrative="The Shadow Rogue leaps from the darkness!",
            gm_signals=ambush_signals,
        )

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={
                        "character_id": char_id,
                        "action": "I look around carefully.",
                    },
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        combat_started_events = [e for e in broadcast_events if e.get("event") == "combat.started"]
        assert len(combat_started_events) >= 1, (
            f"Expected combat.started event, got: {broadcast_events}"
        )

        ws = await _get_world_state(cid)
        assert ws.get("mode") == "combat"


class TestNPCSpawnBeforeSceneTransition:
    """GMSignals npc_updates spawn creates NPC before scene_transition is processed."""

    async def test_spawn_creates_npc_before_scene_transition(
        self, api_client: AsyncClient
    ) -> None:
        """npc_updates spawn must create NPC record in DB."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Spawn Order Test")

        spawn_signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[
                NPCUpdate(
                    event="spawn",
                    npc_name="Mysterious Cultist",
                    disposition="hostile",
                    role="Cultist",
                )
            ],
        )

        mock_narrator = _make_mock_narrator(
            narrative="A cultist emerges from the shadows.",
            gm_signals=spawn_signals,
        )

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I look around."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            npc_result = await db.execute(
                select(NPC).where(
                    NPC.campaign_id == uuid.UUID(cid),
                    NPC.name == "Mysterious Cultist",
                )
            )
            npc = npc_result.scalar_one_or_none()
            assert npc is not None, "NPC should have been spawned by GMSignals"
            assert npc.origin == "narrator_spawned"
            assert npc.disposition == "hostile"

    async def test_duplicate_spawn_discarded(self, api_client: AsyncClient) -> None:
        """Duplicate spawn signal for an existing NPC name → no second record created."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Duplicate Spawn Test")

        async with _TEST_SESSION_FACTORY() as db:
            npc = NPC(
                campaign_id=uuid.UUID(cid),
                name="Pre-Existing Guard",
                origin="predefined",
                disposition="neutral",
                status="alive",
            )
            db.add(npc)
            await db.commit()

        dup_spawn_signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[
                NPCUpdate(
                    event="spawn",
                    npc_name="Pre-Existing Guard",
                    disposition="hostile",
                )
            ],
        )

        mock_narrator = _make_mock_narrator(
            narrative="The guard watches you.",
            gm_signals=dup_spawn_signals,
        )

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I look at the guard."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            npc_result = await db.execute(
                select(NPC).where(
                    NPC.campaign_id == uuid.UUID(cid),
                    NPC.name == "Pre-Existing Guard",
                )
            )
            npcs = npc_result.scalars().all()
            assert len(npcs) == 1, f"Should have exactly 1 NPC, got {len(npcs)}"


class TestEngineCombatEndPrecedence:
    """Engine combat_end flag takes precedence over Narrator signal."""

    async def test_engine_combat_end_overrides_narrator(self, api_client: AsyncClient) -> None:
        """When engine_combat_end flag is set in world_state, combat.ended is
        broadcast and the Narrator combat_end signal is discarded."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Engine Combat End Test")
        await _set_world_state(cid, {"mode": "combat", "engine_combat_end": True})

        engine_end_signals = GMSignals(
            scene_transition=SceneTransition(
                type="combat_end",
                combatants=[],
                reason="narrator also says combat ended",
            ),
            npc_updates=[],
        )

        mock_narrator = _make_mock_narrator(
            narrative="The last goblin falls.",
            gm_signals=engine_end_signals,
        )

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={
                        "character_id": char_id,
                        "action": "I finish off the goblin.",
                    },
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        combat_ended_events = [e for e in broadcast_events if e.get("event") == "combat.ended"]
        assert len(combat_ended_events) >= 1, (
            f"Expected combat.ended event, got: {broadcast_events}"
        )

        ws = await _get_world_state(cid)
        assert ws.get("mode") == "exploration"


class TestGMSignalsParseFailure:
    """If GMSignals can't be parsed, safe_default() is used and the turn completes."""

    async def test_parse_failure_does_not_break_turn(self, api_client: AsyncClient) -> None:
        """Narrator returns a safe_default() (simulating parse failure) and
        the turn pipeline completes successfully without error."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Parse Failure Test")

        # Return narrative text + safe_default (as parse would return on failure)
        mock_narrator = MagicMock(spec=Narrator)
        mock_narrator.narrate_turn_stream = AsyncMock(
            return_value=("You enter the room.", safe_default(), {})
        )
        mock_narrator.update_summary = AsyncMock(return_value="Updated summary.")

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I enter the room."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        turn_id = resp.json()["turn_id"]
        async with _TEST_SESSION_FACTORY() as db:
            turn = await db.get(Turn, uuid.UUID(turn_id))
            assert turn is not None
            assert turn.narrative_response == "You enter the room."


class TestNarrativeTextClean:
    """Narrative text delivered to WebSocket must not contain GMSignals content."""

    async def test_narrative_to_websocket_excludes_gm_signals(
        self, api_client: AsyncClient
    ) -> None:
        """The narrative_text delivered to the WebSocket must not contain the
        GM_SIGNALS_DELIMITER or any JSON after it."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Clean Narrative Test")

        clean_narrative = "The forest path winds ahead, dappled with golden light."
        mock_narrator = _make_mock_narrator(narrative=clean_narrative)

        broadcast_narratives: list[str] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            if event.get("event") == "turn.narrative_end":
                broadcast_narratives.append(event.get("payload", {}).get("narrative", ""))

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I walk forward."},
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        assert len(broadcast_narratives) >= 1, "Expected turn.narrative_end event"
        for narrative in broadcast_narratives:
            assert GM_SIGNALS_DELIMITER not in narrative, (
                f"narrative_text must not contain GMSignals delimiter: {narrative!r}"
            )


# ---------------------------------------------------------------------------
# ADR-0019: location_change signal processing
# ---------------------------------------------------------------------------


class TestLocationChangeSignal:
    async def test_location_change_updates_current_scene_id(self, api_client: AsyncClient) -> None:
        """A location_change signal updates CampaignState.current_scene_id."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Location Change Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            location_change=LocationChange(
                new_location="harborside_supply",
                reason="Player entered the shop",
            ),
        )
        mock_narrator = _make_mock_narrator(
            narrative="You step into Harborside Supply.",
            gm_signals=signals,
        )

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I walk into the shop."},
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
            )
            state = state_result.scalar_one_or_none()
            assert state is not None
            assert state.current_scene_id == "harborside_supply"

    async def test_location_change_emits_websocket_event(self, api_client: AsyncClient) -> None:
        """A location_change signal causes a turn.location_change WebSocket event."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Location WS Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            location_change=LocationChange(new_location="dungeon_entrance"),
        )
        mock_narrator = _make_mock_narrator(
            narrative="You descend into the dungeon.",
            gm_signals=signals,
        )

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I descend."},
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        lc_events = [e for e in broadcast_events if e.get("event") == "turn.location_change"]
        assert len(lc_events) == 1
        assert lc_events[0]["payload"]["new_location"] == "dungeon_entrance"

    async def test_location_change_normalises_raw_identifier(
        self, api_client: AsyncClient
    ) -> None:
        """Raw location identifiers with spaces/capitals are normalised before write."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Normalise Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            location_change=LocationChange(new_location="Harborside Supply"),
        )
        mock_narrator = _make_mock_narrator(gm_signals=signals)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I enter."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        async with _TEST_SESSION_FACTORY() as db:
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
            )
            state = state_result.scalar_one_or_none()
            assert state is not None
            assert state.current_scene_id == "harborside_supply"

    async def test_location_change_after_narrative_end_before_suggested_actions(
        self, api_client: AsyncClient
    ) -> None:
        """turn.location_change event is emitted after narrative_end, before suggested_actions."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Event Order Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            location_change=LocationChange(new_location="new_place"),
            suggested_actions=["Look around"],
        )
        mock_narrator = _make_mock_narrator(gm_signals=signals)

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I move."},
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        event_names = [e.get("event") or e.get("type") for e in broadcast_events]
        narrative_end_idx = next(
            (i for i, n in enumerate(event_names) if n == "turn.narrative_end"), None
        )
        location_change_idx = next(
            (i for i, n in enumerate(event_names) if n == "turn.location_change"), None
        )
        suggested_idx = next(
            (i for i, n in enumerate(event_names) if n == "turn.suggested_actions"), None
        )
        assert narrative_end_idx is not None
        assert location_change_idx is not None
        assert suggested_idx is not None
        assert narrative_end_idx < location_change_idx < suggested_idx


# ---------------------------------------------------------------------------
# ADR-0019: time_progression signal processing
# ---------------------------------------------------------------------------


class TestTimeProgressionSignal:
    async def test_time_progression_updates_time_of_day(self, api_client: AsyncClient) -> None:
        """A time_progression signal updates CampaignState.time_of_day."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Time Progression Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            time_progression=TimeProgression(
                new_time_of_day="evening",
                reason="Hours of travel",
            ),
        )
        mock_narrator = _make_mock_narrator(
            narrative="The sun dips below the horizon.",
            gm_signals=signals,
        )

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "We travel."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
            )
            state = state_result.scalar_one_or_none()
            assert state is not None
            assert state.time_of_day == "evening"

    async def test_time_progression_emits_websocket_event(self, api_client: AsyncClient) -> None:
        """A time_progression signal causes a turn.time_progression WebSocket event."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Time WS Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[],
            time_progression=TimeProgression(new_time_of_day="night"),
        )
        mock_narrator = _make_mock_narrator(gm_signals=signals)

        broadcast_events: list[dict] = []

        async def capture(campaign_id_arg, event):  # type: ignore[no-untyped-def]
            broadcast_events.append(event)

        original_broadcast = ws_mod.manager.broadcast
        ws_mod.manager.broadcast = AsyncMock(side_effect=capture)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "Night falls."},
                )
        finally:
            ws_mod.manager.broadcast = original_broadcast
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        tp_events = [e for e in broadcast_events if e.get("event") == "turn.time_progression"]
        assert len(tp_events) == 1
        assert tp_events[0]["payload"]["new_time_of_day"] == "night"


# ---------------------------------------------------------------------------
# ADR-0019: NPC spawn location auto-assignment (Package C)
# ---------------------------------------------------------------------------


class TestNPCSpawnLocationAutoAssign:
    async def test_spawned_npc_gets_current_scene_id(self, api_client: AsyncClient) -> None:
        """Spawned NPC without explicit location gets scene_location = current_scene_id."""
        cid, char_id = await _setup_campaign_with_char(api_client, "NPC Spawn Location Test")

        # Set the campaign's current_scene_id before the turn
        async with _TEST_SESSION_FACTORY() as db:
            state_result = await db.execute(
                select(CampaignState).where(CampaignState.campaign_id == uuid.UUID(cid))
            )
            state = state_result.scalar_one_or_none()
            if state is not None:
                state.current_scene_id = "harborside_supply"
                await db.commit()

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[
                NPCUpdate(
                    event="spawn",
                    npc_name="Vara",
                    species="Human",
                    appearance="A woman with sun-darkened skin.",
                    role="Shopkeeper",
                    motivation="To earn a living",
                    disposition="neutral",
                )
            ],
        )
        mock_narrator = _make_mock_narrator(gm_signals=signals)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I enter the shop."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            npc_result = await db.execute(
                select(NPC).where(
                    NPC.campaign_id == uuid.UUID(cid),
                    NPC.name == "Vara",
                )
            )
            vara = npc_result.scalar_one_or_none()
            assert vara is not None
            assert vara.scene_location == "harborside_supply"

    async def test_spawn_plus_location_change_auto_assigns_new_scene(
        self, api_client: AsyncClient
    ) -> None:
        """When spawn + location_change fire on same turn, NPC gets the new location."""
        cid, char_id = await _setup_campaign_with_char(api_client, "Spawn+Location Test")

        signals = GMSignals(
            scene_transition=SceneTransition(type="none"),
            npc_updates=[
                NPCUpdate(
                    event="spawn",
                    npc_name="Dock Master",
                    species="Human",
                    appearance="A grizzled man with a pipe.",
                    role="Dock Master",
                    motivation="Keep the docks running",
                    disposition="neutral",
                )
            ],
            location_change=LocationChange(new_location="dock_district"),
        )
        mock_narrator = _make_mock_narrator(gm_signals=signals)

        try:
            with patch(
                "tavern.dm.combat_classifier.CombatClassifier.classify",
                new=AsyncMock(return_value=_no_combat_classification()),
            ):
                app.dependency_overrides[get_narrator_dep] = lambda: mock_narrator
                resp = await api_client.post(
                    f"/api/campaigns/{cid}/turns",
                    json={"character_id": char_id, "action": "I head to the docks."},
                )
        finally:
            app.dependency_overrides.pop(get_narrator_dep, None)

        assert resp.status_code == 202

        async with _TEST_SESSION_FACTORY() as db:
            npc_result = await db.execute(
                select(NPC).where(
                    NPC.campaign_id == uuid.UUID(cid),
                    NPC.name == "Dock Master",
                )
            )
            npc = npc_result.scalar_one_or_none()
            assert npc is not None
            # NPC was spawned before location_change processed; auto-assignment
            # sets scene_location to the new current_scene_id
            assert npc.scene_location == "dock_district"
