import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character, CharacterCondition, InventoryItem
from tavern.models.session import Session
from tavern.models.turn import Turn


def make_campaign(name: str = "Test Campaign", status: str = "active") -> Campaign:
    return Campaign(id=uuid.uuid4(), name=name, status=status)


def make_campaign_state(campaign_id: uuid.UUID) -> CampaignState:
    return CampaignState(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        rolling_summary="The party has just arrived in Neverwinter.",
        scene_context="Standing at the city gates at dusk.",
        world_state={"weather": "overcast", "time_of_day": "dusk"},
        turn_count=0,
    )


def make_character(campaign_id: uuid.UUID, name: str = "Aria") -> Character:
    return Character(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        name=name,
        class_name="Ranger",
        level=3,
        hp=28,
        max_hp=28,
        ac=14,
        ability_scores={"str": 12, "dex": 16, "con": 14, "int": 10, "wis": 14, "cha": 10},
        spell_slots={},
        features={"favored_enemy": "undead"},
    )


def make_session(campaign_id: uuid.UUID) -> Session:
    return Session(id=uuid.uuid4(), campaign_id=campaign_id)


def make_turn(session_id: uuid.UUID, character_id: uuid.UUID, seq: int = 1) -> Turn:
    return Turn(
        id=uuid.uuid4(),
        session_id=session_id,
        character_id=character_id,
        sequence_number=seq,
        player_action="I examine the city gates for guards.",
    )


class TestModelInstantiation:
    def test_campaign_instantiation(self):
        c = make_campaign()
        assert c.name == "Test Campaign"
        assert c.status == "active"
        assert c.world_seed is None
        assert c.dm_persona is None

    def test_campaign_state_instantiation(self):
        cid = uuid.uuid4()
        cs = make_campaign_state(cid)
        assert cs.campaign_id == cid
        assert cs.turn_count == 0
        assert cs.world_state["weather"] == "overcast"

    def test_session_instantiation(self):
        cid = uuid.uuid4()
        s = make_session(cid)
        assert s.campaign_id == cid
        assert s.ended_at is None
        assert s.end_reason is None

    def test_character_instantiation(self):
        cid = uuid.uuid4()
        ch = make_character(cid)
        assert ch.name == "Aria"
        assert ch.level == 3
        assert ch.hp == 28
        assert ch.ability_scores["dex"] == 16

    def test_inventory_item_instantiation(self):
        char_id = uuid.uuid4()
        item = InventoryItem(
            id=uuid.uuid4(),
            character_id=char_id,
            name="Longbow",
            quantity=1,
            properties={"damage": "1d8", "range": "150/600"},
        )
        assert item.name == "Longbow"
        assert item.quantity == 1
        assert item.description is None

    def test_character_condition_instantiation(self):
        char_id = uuid.uuid4()
        cond = CharacterCondition(
            id=uuid.uuid4(),
            character_id=char_id,
            condition_name="poisoned",
            duration_rounds=3,
            source="Giant Spider",
        )
        assert cond.condition_name == "poisoned"
        assert cond.duration_rounds == 3

    def test_turn_instantiation(self):
        sid = uuid.uuid4()
        cid = uuid.uuid4()
        t = make_turn(sid, cid)
        assert t.sequence_number == 1
        assert t.rules_result is None
        assert t.narrative_response is None


class TestCampaignStatusValidation:
    @pytest.mark.parametrize("status", ["active", "paused", "concluded", "abandoned"])
    def test_valid_statuses_accepted(self, status: str):
        c = Campaign(id=uuid.uuid4(), name="Test", status=status)
        assert c.status == status

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid campaign status"):
            Campaign(id=uuid.uuid4(), name="Test", status="deleted")


class TestSessionEndReasonValidation:
    @pytest.mark.parametrize("reason", ["player_ended", "connection_lost", None])
    def test_valid_end_reasons_accepted(self, reason: str | None):
        s = Session(id=uuid.uuid4(), campaign_id=uuid.uuid4(), end_reason=reason)
        assert s.end_reason == reason

    def test_invalid_end_reason_raises(self):
        with pytest.raises(ValueError, match="Invalid end_reason"):
            Session(id=uuid.uuid4(), campaign_id=uuid.uuid4(), end_reason="crashed")


class TestCampaignCampaignStateRelationship:
    async def test_one_to_one_relationship(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        state = make_campaign_state(campaign.id)
        campaign.state = state
        db_session.add(state)
        await db_session.commit()

        result = await db_session.execute(select(Campaign).where(Campaign.id == campaign.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["state"])
        assert loaded.state is not None
        assert loaded.state.campaign_id == campaign.id
        assert loaded.state.turn_count == 0

    async def test_campaign_state_links_back_to_campaign(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        state = make_campaign_state(campaign.id)
        campaign.state = state
        db_session.add(state)
        await db_session.commit()

        result = await db_session.execute(
            select(CampaignState).where(CampaignState.campaign_id == campaign.id)
        )
        loaded_state = result.scalar_one()
        await db_session.refresh(loaded_state, ["campaign"])
        assert loaded_state.campaign.name == campaign.name


class TestCampaignSessionTurnChain:
    async def test_campaign_has_many_sessions(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        s1 = make_session(campaign.id)
        s2 = make_session(campaign.id)
        db_session.add_all([s1, s2])
        await db_session.commit()

        result = await db_session.execute(select(Campaign).where(Campaign.id == campaign.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["sessions"])
        assert len(loaded.sessions) == 2

    async def test_session_has_many_turns_ordered_by_sequence(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        character = make_character(campaign.id)
        db_session.add(character)
        await db_session.flush()

        session = make_session(campaign.id)
        db_session.add(session)
        await db_session.flush()

        t3 = make_turn(session.id, character.id, seq=3)
        t1 = make_turn(session.id, character.id, seq=1)
        t2 = make_turn(session.id, character.id, seq=2)
        db_session.add_all([t3, t1, t2])
        await db_session.commit()

        result = await db_session.execute(select(Session).where(Session.id == session.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["turns"])
        sequences = [t.sequence_number for t in loaded.turns]
        assert sequences == [1, 2, 3]

    async def test_turn_references_character(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        character = make_character(campaign.id)
        db_session.add(character)
        await db_session.flush()

        session = make_session(campaign.id)
        db_session.add(session)
        await db_session.flush()

        turn = make_turn(session.id, character.id)
        db_session.add(turn)
        await db_session.commit()

        result = await db_session.execute(select(Turn).where(Turn.id == turn.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["character"])
        assert loaded.character.name == character.name


class TestCharacterRelationships:
    async def test_character_has_many_inventory_items(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        character = make_character(campaign.id)
        db_session.add(character)
        await db_session.flush()

        sword = InventoryItem(
            id=uuid.uuid4(),
            character_id=character.id,
            name="Longsword",
            quantity=1,
        )
        arrows = InventoryItem(
            id=uuid.uuid4(),
            character_id=character.id,
            name="Arrows",
            quantity=20,
        )
        db_session.add_all([sword, arrows])
        await db_session.commit()

        result = await db_session.execute(select(Character).where(Character.id == character.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["inventory"])
        assert len(loaded.inventory) == 2
        names = {item.name for item in loaded.inventory}
        assert names == {"Longsword", "Arrows"}

    async def test_character_has_many_conditions(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        character = make_character(campaign.id)
        db_session.add(character)
        await db_session.flush()

        poisoned = CharacterCondition(
            id=uuid.uuid4(),
            character_id=character.id,
            condition_name="poisoned",
            duration_rounds=2,
            source="Giant Spider",
        )
        blinded = CharacterCondition(
            id=uuid.uuid4(),
            character_id=character.id,
            condition_name="blinded",
            duration_rounds=None,
            source="Darkness spell",
        )
        db_session.add_all([poisoned, blinded])
        await db_session.commit()

        result = await db_session.execute(select(Character).where(Character.id == character.id))
        loaded = result.scalar_one()
        await db_session.refresh(loaded, ["conditions"])
        assert len(loaded.conditions) == 2
        condition_names = {c.condition_name for c in loaded.conditions}
        assert condition_names == {"poisoned", "blinded"}

    async def test_inventory_item_nullable_fields(self, db_session: AsyncSession):
        campaign = make_campaign()
        db_session.add(campaign)
        await db_session.flush()

        character = make_character(campaign.id)
        db_session.add(character)
        await db_session.flush()

        item = InventoryItem(
            id=uuid.uuid4(),
            character_id=character.id,
            name="Mysterious Gem",
        )
        db_session.add(item)
        await db_session.commit()

        result = await db_session.execute(select(InventoryItem).where(InventoryItem.id == item.id))
        loaded = result.scalar_one()
        assert loaded.description is None
        assert loaded.properties is None
        assert loaded.quantity == 1
