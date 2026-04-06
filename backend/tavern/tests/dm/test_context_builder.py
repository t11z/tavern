"""Tests for dm/context_builder.py.

Each test operates against an in-memory SQLite database populated with
realistic fixture data. All async fixtures use the shared ``db_session``
fixture from ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.dm.context_builder import (
    _DEFAULT_DM_PERSONA,
    CharacterState,
    SceneContext,
    StateSnapshot,
    TurnContext,
    build_snapshot,
    build_system_prompt,
    estimate_tokens,
    serialize_snapshot,
)
from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character, CharacterCondition, InventoryItem
from tavern.models.npc import NPC

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _campaign(
    *,
    name: str = "The Lost Mine",
    dm_persona: str | None = None,
    world_seed: str | None = None,
) -> Campaign:
    return Campaign(
        id=uuid.uuid4(),
        name=name,
        status="active",
        dm_persona=dm_persona,
        world_seed=world_seed,
    )


def _campaign_state(
    campaign_id: uuid.UUID,
    *,
    rolling_summary: str = "The party has just arrived in Phandalin.",
    scene_context: str = "You stand in the dusty main street of Phandalin.",
    world_state: dict | None = None,
    current_scene_id: str = "phandalin",
    time_of_day: str = "midday",
) -> CampaignState:
    ws = world_state or {
        "location": "Phandalin",
        "environment": "sunny",
        "npcs": ["Gundren Rockseeker — friendly"],
        "threats": [],
    }
    return CampaignState(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        rolling_summary=rolling_summary,
        scene_context=scene_context,
        world_state=ws,
        current_scene_id=current_scene_id,
        time_of_day=time_of_day,
        turn_count=1,
    )


def _character(
    campaign_id: uuid.UUID,
    name: str = "Aldric",
    *,
    class_name: str = "Fighter",
    level: int = 3,
    hp: int = 28,
    max_hp: int = 34,
    ac: int = 16,
    spell_slots: dict | None = None,
) -> Character:
    return Character(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        name=name,
        class_name=class_name,
        level=level,
        hp=hp,
        max_hp=max_hp,
        ac=ac,
        ability_scores={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 11, "cha": 10},
        spell_slots=spell_slots or {},
        features={},
    )


def _npc(
    campaign_id: uuid.UUID,
    name: str = "Aldara",
    *,
    origin: str = "predefined",
    scene_location: str | None = None,
    last_seen_turn: int | None = None,
    status: str = "alive",
    plot_significant: bool = False,
) -> NPC:
    return NPC(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        name=name,
        origin=origin,
        status=status,
        disposition="neutral",
        plot_significant=plot_significant,
        scene_location=scene_location,
        last_seen_turn=last_seen_turn,
    )


async def _populate_basic(db: AsyncSession) -> tuple[Campaign, CampaignState, Character]:
    """Create one campaign + state + one character."""
    campaign = _campaign()
    db.add(campaign)
    await db.flush()

    state = _campaign_state(campaign.id)
    db.add(state)

    char = _character(campaign.id)
    db.add(char)

    await db.commit()
    return campaign, state, char


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_four_chars_is_one_token(self) -> None:
        assert estimate_tokens("abcd") == 1

    def test_longer_string(self) -> None:
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_within_20_percent_of_actual(self) -> None:
        """The estimate should be within 20% of a simple character-count baseline."""
        text = "The party descends into the dungeon, swords drawn." * 20
        estimated = estimate_tokens(text)
        # Rough baseline: one token ≈ 4 chars
        baseline = len(text) / 4
        assert abs(estimated - baseline) / baseline < 0.20

    def test_system_prompt_within_budget(self) -> None:
        """A system prompt should fit within the ~800-token budget."""
        prompt = build_system_prompt(dm_persona=None, campaign_tone=None, is_multiplayer=False)
        assert estimate_tokens(prompt) <= 800


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_contains_hard_constraint_no_mechanical_results(self) -> None:
        """ADR-0002: 'Never output mechanical results.'"""
        prompt = build_system_prompt(None, None, False)
        assert "Never output mechanical results" in prompt

    def test_contains_hard_constraint_no_contradict_rules_engine(self) -> None:
        """ADR-0002: 'Never contradict the Rules Engine results.'"""
        prompt = build_system_prompt(None, None, False)
        assert "Never contradict the Rules Engine" in prompt

    def test_contains_hard_constraint_no_unknown_info(self) -> None:
        """ADR-0002: 'Never reveal information the characters would not know.'"""
        prompt = build_system_prompt(None, None, False)
        assert "Never reveal information" in prompt

    def test_contains_plain_text_output_rule(self) -> None:
        """ADR-0002: 'Respond in plain text only. No Markdown, no HTML.'"""
        prompt = build_system_prompt(None, None, False)
        assert "plain text" in prompt.lower()
        assert "Markdown" in prompt or "markdown" in prompt.lower()

    def test_contains_response_length_guidance(self) -> None:
        """ADR-0002: '2-4 paragraphs for narrative, 1-2 sentences for acks.'"""
        prompt = build_system_prompt(None, None, False)
        assert "2-4 paragraphs" in prompt or "2–4 paragraphs" in prompt

    def test_no_dm_persona_uses_default(self) -> None:
        """When dm_persona is None, the default persona is used."""
        prompt = build_system_prompt(None, None, False)
        # The default persona should be present
        assert "Dungeon Master" in prompt

    def test_custom_dm_persona_replaces_default(self) -> None:
        custom = "You are a grim, battle-scarred veteran storyteller."
        prompt = build_system_prompt(custom, None, False)
        assert "grim, battle-scarred" in prompt
        assert _DEFAULT_DM_PERSONA not in prompt

    def test_campaign_tone_included(self) -> None:
        prompt = build_system_prompt(None, "dark and gritty", False)
        assert "dark and gritty" in prompt

    def test_multiplayer_instructions_present_when_multiplayer(self) -> None:
        """ADR-0002: Multiplayer instructions in system prompt when is_multiplayer=True."""
        prompt = build_system_prompt(None, None, True)
        assert "Address the acting player by their character name" in prompt

    def test_multiplayer_instructions_absent_when_solo(self) -> None:
        """ADR-0002: No multiplayer instructions for solo campaigns."""
        prompt = build_system_prompt(None, None, False)
        assert "Address the acting player" not in prompt

    def test_multiplayer_acknowledges_other_characters(self) -> None:
        """ADR-0002: 'Acknowledge other present characters naturally.'"""
        prompt = build_system_prompt(None, None, True)
        assert "other present characters" in prompt or "other characters" in prompt

    def test_multiplayer_combat_turn_restriction(self) -> None:
        """ADR-0002: 'In combat, narrate only the current turn's action.'"""
        prompt = build_system_prompt(None, None, True)
        assert "current turn" in prompt


# ---------------------------------------------------------------------------
# build_snapshot — database integration
# ---------------------------------------------------------------------------


class TestBuildSnapshot:
    async def test_snapshot_loads_rolling_summary(self, db_session: AsyncSession) -> None:
        """build_snapshot reads the rolling_summary from CampaignState."""
        campaign, state, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="I look around.", rules_result=None)

        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.rolling_summary == state.rolling_summary

    async def test_snapshot_loads_scene_description(self, db_session: AsyncSession) -> None:
        """scene.description comes from CampaignState.scene_context."""
        campaign, state, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="I look around.", rules_result=None)

        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.scene.description == state.scene_context.strip()

    async def test_snapshot_loads_scene_world_state_fields(self, db_session: AsyncSession) -> None:
        """Scene location from current_scene_id column (ADR-0019)."""
        campaign, state, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="I look around.", rules_result=None)

        snapshot = await build_snapshot(campaign.id, turn, db_session)

        # location now reads from current_scene_id column (ADR-0019)
        assert snapshot.scene.location == "phandalin"
        # time_of_day now reads from time_of_day column (ADR-0019)
        assert snapshot.scene.time_of_day == "midday"
        assert snapshot.scene.environment == "sunny"
        assert "Gundren Rockseeker — friendly" in snapshot.scene.npcs

    async def test_snapshot_loads_character_state(self, db_session: AsyncSession) -> None:
        """Each party member appears in snapshot.characters."""
        campaign, _, char = await _populate_basic(db_session)
        turn = TurnContext(player_action="I move forward.", rules_result=None)

        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert len(snapshot.characters) == 1
        cs = snapshot.characters[0]
        assert cs.name == char.name
        assert cs.class_name == char.class_name
        assert cs.level == char.level
        assert cs.hp == char.hp
        assert cs.max_hp == char.max_hp
        assert cs.ac == char.ac

    async def test_snapshot_includes_current_turn(self, db_session: AsyncSession) -> None:
        """current_turn is the TurnContext passed in, not loaded from DB."""
        campaign, _, _ = await _populate_basic(db_session)
        turn = TurnContext(
            player_action="I attack the goblin.",
            rules_result="Attack hits. 14 slashing damage. Goblin is dead.",
        )

        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.current_turn.player_action == turn.player_action
        assert snapshot.current_turn.rules_result == turn.rules_result

    async def test_snapshot_no_dm_persona_uses_default(self, db_session: AsyncSession) -> None:
        """Campaign with dm_persona=None uses the default DM persona."""
        campaign = _campaign(dm_persona=None)
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        await db_session.commit()

        turn = TurnContext(player_action="Hello.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "Dungeon Master" in snapshot.system_prompt

    async def test_snapshot_custom_dm_persona_used(self, db_session: AsyncSession) -> None:
        """Campaign dm_persona is injected into the system prompt."""
        persona = "You are a mysterious elven oracle who speaks in riddles."
        campaign = _campaign(dm_persona=persona)
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        await db_session.commit()

        turn = TurnContext(player_action="What do you see?", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "mysterious elven oracle" in snapshot.system_prompt

    async def test_snapshot_campaign_tone_from_world_state(self, db_session: AsyncSession) -> None:
        """Campaign tone is read from world_state['tone'] and added to system prompt."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        state = _campaign_state(
            campaign.id,
            world_state={
                "location": "Shadow Keep",
                "time_of_day": "midnight",
                "environment": "stormy",
                "npcs": [],
                "threats": [],
                "tone": "dark and foreboding",
            },
        )
        db_session.add(state)
        await db_session.commit()

        turn = TurnContext(player_action="Enter the keep.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "dark and foreboding" in snapshot.system_prompt

    async def test_snapshot_multiplayer_when_multiple_characters(
        self, db_session: AsyncSession
    ) -> None:
        """Two characters → system prompt contains multiplayer instructions."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        db_session.add(_character(campaign.id, "Aldric"))
        db_session.add(_character(campaign.id, "Kira", class_name="Wizard"))
        await db_session.commit()

        turn = TurnContext(player_action="We explore together.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "Address the acting player" in snapshot.system_prompt

    async def test_snapshot_solo_no_multiplayer_instructions(
        self, db_session: AsyncSession
    ) -> None:
        """One character → no multiplayer instructions in system prompt."""
        campaign, _, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="I sneak past the guards.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "Address the acting player" not in snapshot.system_prompt

    async def test_snapshot_invalid_campaign_raises(self, db_session: AsyncSession) -> None:
        """Non-existent campaign_id raises ValueError."""
        turn = TurnContext(player_action="Nope.", rules_result=None)
        with pytest.raises(ValueError, match="not found"):
            await build_snapshot(uuid.uuid4(), turn, db_session)

    async def test_snapshot_missing_campaign_state_raises(self, db_session: AsyncSession) -> None:
        """Campaign without a CampaignState raises ValueError."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.commit()

        turn = TurnContext(player_action="Go.", rules_result=None)
        with pytest.raises(ValueError, match="no CampaignState"):
            await build_snapshot(campaign.id, turn, db_session)

    async def test_snapshot_loads_character_conditions(self, db_session: AsyncSession) -> None:
        """Active conditions on a character appear in the snapshot."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        char = _character(campaign.id)
        db_session.add(char)
        await db_session.flush()
        db_session.add(
            CharacterCondition(
                id=uuid.uuid4(),
                character_id=char.id,
                condition_name="poisoned",
                duration_rounds=2,
                source="Giant Spider",
            )
        )
        await db_session.commit()

        turn = TurnContext(player_action="I endure.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert "poisoned" in snapshot.characters[0].conditions

    async def test_snapshot_loads_character_spell_slots(self, db_session: AsyncSession) -> None:
        """Non-zero spell slots appear in the character snapshot."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        char = _character(
            campaign.id, "Kira", class_name="Wizard", spell_slots={"1": 3, "2": 2, "3": 0}
        )
        db_session.add(char)
        await db_session.commit()

        turn = TurnContext(player_action="I prepare a spell.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        cs = snapshot.characters[0]
        assert cs.spell_slots == {1: 3, 2: 2}  # level 3 omitted (0 remaining)

    async def test_snapshot_inventory_truncated_to_10(self, db_session: AsyncSession) -> None:
        """Inventory is capped at 10 items regardless of how many the character carries."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        db_session.add(_campaign_state(campaign.id))
        char = _character(campaign.id)
        db_session.add(char)
        await db_session.flush()

        for i in range(15):
            db_session.add(
                InventoryItem(
                    id=uuid.uuid4(),
                    character_id=char.id,
                    name=f"Item {i}",
                    quantity=1,
                )
            )
        await db_session.commit()

        turn = TurnContext(player_action="I check my pack.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert len(snapshot.characters[0].key_inventory) == 10

    async def test_snapshot_empty_inventory(self, db_session: AsyncSession) -> None:
        """Character with no inventory items has an empty key_inventory list."""
        campaign, _, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="I pat my empty pockets.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.characters[0].key_inventory == []

    # -----------------------------------------------------------------------
    # NPC inclusion / exclusion (ADR-0013 §2)
    # -----------------------------------------------------------------------

    async def test_snapshot_includes_predefined_npc_with_no_scene_location(
        self, db_session: AsyncSession
    ) -> None:
        """ADR-0013 §2: predefined NPC with scene_location=None is always included."""
        campaign, _, _ = await _populate_basic(db_session)
        npc = _npc(campaign.id, "Aldara", origin="predefined", scene_location=None)
        db_session.add(npc)
        await db_session.commit()

        turn = TurnContext(player_action="I look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Aldara" in npc_names

    async def test_snapshot_excludes_narrator_spawned_npc_with_no_scene_location(
        self, db_session: AsyncSession
    ) -> None:
        """Only predefined NPCs get the scene_location=None fallback; narrator-spawned do not."""
        campaign, _, _ = await _populate_basic(db_session)
        npc = _npc(
            campaign.id,
            "Spawned Bandit",
            origin="narrator_spawned",
            scene_location=None,
            last_seen_turn=None,
        )
        db_session.add(npc)
        await db_session.commit()

        turn = TurnContext(player_action="I look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Spawned Bandit" not in npc_names

    async def test_snapshot_excludes_predefined_npc_in_other_scene(
        self, db_session: AsyncSession
    ) -> None:
        """Predefined NPC assigned to a different scene is not included (scene-scoped)."""
        campaign, _, _ = await _populate_basic(db_session)
        # The campaign state location is "Phandalin"; assign NPC to a different scene
        npc = _npc(
            campaign.id,
            "Distant Guard",
            origin="predefined",
            scene_location="Castle Neverwinter",
            last_seen_turn=None,
        )
        db_session.add(npc)
        await db_session.commit()

        turn = TurnContext(player_action="I look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Distant Guard" not in npc_names

    async def test_snapshot_includes_npc_in_current_scene(self, db_session: AsyncSession) -> None:
        """NPC whose scene_location matches current_scene_id is included (ADR-0019)."""
        campaign, _, _ = await _populate_basic(db_session)
        # _populate_basic sets current_scene_id to "phandalin" (normalised)
        npc = _npc(
            campaign.id,
            "Local Merchant",
            origin="narrator_spawned",
            scene_location="phandalin",
        )
        db_session.add(npc)
        await db_session.commit()

        turn = TurnContext(player_action="I look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Local Merchant" in npc_names


# ---------------------------------------------------------------------------
# serialize_snapshot
# ---------------------------------------------------------------------------


class TestSerializeSnapshot:
    def _minimal_snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            system_prompt="You are a DM.",
            characters=[
                CharacterState(
                    name="Aldric",
                    class_name="Fighter",
                    level=3,
                    hp=28,
                    max_hp=34,
                    ac=16,
                    conditions=[],
                    spell_slots={},
                    key_inventory=["Longsword", "Shield"],
                )
            ],
            scene=SceneContext(
                location="Phandalin",
                description="The dusty street is quiet.",
                npcs=["Sildar Hallwinter — neutral"],
                environment="sunny",
                threats=[],
                time_of_day="noon",
            ),
            rolling_summary="Turn 1: The party arrived in Phandalin.",
            current_turn=TurnContext(
                player_action="I look around the town.",
                rules_result=None,
            ),
        )

    def test_returns_dict_with_system_and_messages(self) -> None:
        """Anthropic API expects {'system': str, 'messages': list}."""
        result = serialize_snapshot(self._minimal_snapshot())
        assert "system" in result
        assert "messages" in result

    def test_system_is_string(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        assert isinstance(result["system"], str)

    def test_messages_is_list(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        assert isinstance(result["messages"], list)

    def test_single_user_message(self) -> None:
        """Snapshot serialises to exactly one user message."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_message_content_is_string(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        assert isinstance(messages[0]["content"], str)

    def test_system_prompt_is_snapshot_system_prompt(self) -> None:
        snapshot = self._minimal_snapshot()
        result = serialize_snapshot(snapshot)
        assert result["system"] == snapshot.system_prompt

    def test_user_message_contains_character_name(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Aldric" in content

    def test_user_message_contains_scene_identifier(self) -> None:
        """Scene field uses 'Scene:' label (ADR-0019 §5)."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Scene: Phandalin" in content

    def test_user_message_contains_time_field(self) -> None:
        """Time field is always present in the scene block (ADR-0019 §5)."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Time: noon" in content

    def test_user_message_contains_rolling_summary(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "The party arrived in Phandalin" in content

    def test_user_message_contains_player_action(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "I look around the town" in content

    def test_user_message_contains_rules_result_when_present(self) -> None:
        snapshot = self._minimal_snapshot()
        snapshot.current_turn = TurnContext(
            player_action="I attack the goblin.",
            rules_result="Attack hits. 14 slashing damage.",
        )
        result = serialize_snapshot(snapshot)
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "14 slashing damage" in content

    def test_user_message_component_order(self) -> None:
        """ADR-0002: Characters → Scene → Rolling summary → Current turn."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        char_pos = content.index("Aldric")
        scene_pos = content.index("Scene: Phandalin")
        summary_pos = content.index("The party arrived")
        action_pos = content.index("I look around the town")
        assert char_pos < scene_pos < summary_pos < action_pos

    def test_no_markdown_in_user_message(self) -> None:
        """ADR-0002: Plain text output — no Markdown formatting in the prompt."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        # No Markdown headers, bold, or code blocks
        assert "##" not in content
        assert "**" not in content
        assert "```" not in content

    def test_character_conditions_appear_in_message(self) -> None:
        snapshot = self._minimal_snapshot()
        snapshot.characters[0].conditions = ["poisoned", "blinded"]
        result = serialize_snapshot(snapshot)
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "poisoned" in content
        assert "blinded" in content

    def test_character_spell_slots_appear_in_message(self) -> None:
        snapshot = self._minimal_snapshot()
        snapshot.characters[0].spell_slots = {1: 3, 2: 1}
        result = serialize_snapshot(snapshot)
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Level 1" in content or "level 1" in content.lower()

    def test_npc_list_appears_in_message(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Sildar Hallwinter" in content

    def test_no_rules_result_when_none(self) -> None:
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Rules Engine result" not in content

    def test_scene_label_not_location_label(self) -> None:
        """ADR-0019 §5: serialised scene block uses 'Scene:' not 'Location:'."""
        result = serialize_snapshot(self._minimal_snapshot())
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Scene:" in content
        assert "Location:" not in content

    def test_time_always_present_even_empty(self) -> None:
        """ADR-0019 §5: Time field is always included, defaulting to 'morning'."""
        snapshot = self._minimal_snapshot()
        snapshot.scene.time_of_day = ""
        result = serialize_snapshot(snapshot)
        messages = result["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "Time: morning" in content


# ---------------------------------------------------------------------------
# ADR-0019: current_scene_id and time_of_day columns in build_snapshot
# ---------------------------------------------------------------------------


class TestBuildSnapshotADR0019:
    async def test_snapshot_location_reads_current_scene_id_column(
        self, db_session: AsyncSession
    ) -> None:
        """scene.location comes from CampaignState.current_scene_id column (ADR-0019)."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        state = _campaign_state(
            campaign.id,
            current_scene_id="harborside_supply",
            world_state={"location": "Old Tavern", "environment": ""},
        )
        db_session.add(state)
        db_session.add(_character(campaign.id))
        await db_session.commit()

        turn = TurnContext(player_action="Look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.scene.location == "harborside_supply"

    async def test_snapshot_time_reads_time_of_day_column(self, db_session: AsyncSession) -> None:
        """scene.time_of_day comes from CampaignState.time_of_day column (ADR-0019)."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        state = _campaign_state(
            campaign.id,
            time_of_day="dusk",
            world_state={"location": "Town", "environment": ""},
        )
        db_session.add(state)
        db_session.add(_character(campaign.id))
        await db_session.commit()

        turn = TurnContext(player_action="Look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        assert snapshot.scene.time_of_day == "dusk"

    async def test_npc_query_uses_current_scene_id(self, db_session: AsyncSession) -> None:
        """NPCs are scoped to current_scene_id, not world_state['location'] (ADR-0019)."""
        campaign = _campaign()
        db_session.add(campaign)
        await db_session.flush()
        state = _campaign_state(
            campaign.id,
            current_scene_id="harborside_supply",
            world_state={"location": "Old Tavern", "environment": ""},
        )
        db_session.add(state)
        db_session.add(_character(campaign.id))

        # NPC at the new location
        npc_at_shop = _npc(
            campaign.id,
            "Shopkeeper Vara",
            origin="narrator_spawned",
            scene_location="harborside_supply",
        )
        # NPC at the old location (world_state["location"])
        npc_at_tavern = _npc(
            campaign.id,
            "Barkeep Korven",
            origin="narrator_spawned",
            scene_location="old_tavern",
        )
        db_session.add(npc_at_shop)
        db_session.add(npc_at_tavern)
        await db_session.commit()

        turn = TurnContext(player_action="Look around.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)

        npc_names = [n["name"] for n in snapshot.npcs]
        assert "Shopkeeper Vara" in npc_names
        assert "Barkeep Korven" not in npc_names

    async def test_serialised_scene_block_has_scene_label(self, db_session: AsyncSession) -> None:
        """Serialised scene block uses 'Scene:' label (ADR-0019 §5)."""
        campaign, _, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="Look.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)
        serialized = serialize_snapshot(snapshot)
        content = serialized["messages"][0]["content"]  # type: ignore[index]
        assert "Scene:" in content
        assert "Location:" not in content

    async def test_serialised_scene_block_has_time_field(self, db_session: AsyncSession) -> None:
        """Serialised scene block always has 'Time:' field (ADR-0019 §5)."""
        campaign, _, _ = await _populate_basic(db_session)
        turn = TurnContext(player_action="Look.", rules_result=None)
        snapshot = await build_snapshot(campaign.id, turn, db_session)
        serialized = serialize_snapshot(snapshot)
        content = serialized["messages"][0]["content"]  # type: ignore[index]
        assert "Time:" in content
