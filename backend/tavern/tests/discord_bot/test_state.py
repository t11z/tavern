"""Tests for BotState and associated dataclasses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tavern.discord_bot.models.state import (
    BotState,
    ChannelBinding,
    PendingRoll,
    ReactionWindow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CHANNEL_ID = 111111111111111111
GUILD_ID = 222222222222222222
CAMPAIGN_ID = uuid.uuid4()
CHARACTER_ID = uuid.uuid4()
TURN_ID = uuid.uuid4()
ROLL_ID = uuid.uuid4()


@pytest.fixture
def state() -> BotState:
    return BotState()


@pytest.fixture
def binding() -> ChannelBinding:
    return ChannelBinding(
        channel_id=CHANNEL_ID,
        campaign_id=CAMPAIGN_ID,
        guild_id=GUILD_ID,
    )


@pytest.fixture
def pending_roll() -> PendingRoll:
    return PendingRoll(
        channel_id=CHANNEL_ID,
        turn_id=TURN_ID,
        roll_id=ROLL_ID,
        character_id=CHARACTER_ID,
        expires_at=datetime.now(UTC) + timedelta(seconds=120),
    )


@pytest.fixture
def reaction_window() -> ReactionWindow:
    char_a = uuid.uuid4()
    char_b = uuid.uuid4()
    return ReactionWindow(
        roll_id=ROLL_ID,
        eligible_reactors={char_a, char_b},
        expires_at=datetime.now(UTC) + timedelta(seconds=15),
    )


# ---------------------------------------------------------------------------
# ChannelBinding
# ---------------------------------------------------------------------------


class TestChannelBinding:
    def test_stores_fields(self, binding: ChannelBinding) -> None:
        assert binding.channel_id == CHANNEL_ID
        assert binding.campaign_id == CAMPAIGN_ID
        assert binding.guild_id == GUILD_ID


# ---------------------------------------------------------------------------
# PendingRoll
# ---------------------------------------------------------------------------


class TestPendingRoll:
    def test_stores_all_fields(self, pending_roll: PendingRoll) -> None:
        assert pending_roll.channel_id == CHANNEL_ID
        assert pending_roll.turn_id == TURN_ID
        assert pending_roll.roll_id == ROLL_ID
        assert pending_roll.character_id == CHARACTER_ID
        assert isinstance(pending_roll.expires_at, datetime)


# ---------------------------------------------------------------------------
# ReactionWindow
# ---------------------------------------------------------------------------


class TestReactionWindow:
    def test_all_responded_false_when_none_responded(
        self, reaction_window: ReactionWindow
    ) -> None:
        assert not reaction_window.all_responded

    def test_all_responded_true_when_all_marked(self, reaction_window: ReactionWindow) -> None:
        for char_id in list(reaction_window.eligible_reactors):
            reaction_window.mark_responded(char_id)
        assert reaction_window.all_responded

    def test_mark_responded_adds_to_set(self, reaction_window: ReactionWindow) -> None:
        char_id = next(iter(reaction_window.eligible_reactors))
        reaction_window.mark_responded(char_id)
        assert char_id in reaction_window.responded

    def test_all_responded_false_when_only_partial(self, reaction_window: ReactionWindow) -> None:
        assert len(reaction_window.eligible_reactors) >= 2
        char_id = next(iter(reaction_window.eligible_reactors))
        reaction_window.mark_responded(char_id)
        assert not reaction_window.all_responded

    def test_default_responded_is_empty(self) -> None:
        window = ReactionWindow(roll_id=uuid.uuid4())
        assert window.responded == set()


# ---------------------------------------------------------------------------
# BotState — channel bindings
# ---------------------------------------------------------------------------


class TestChannelBindings:
    def test_bind_channel_stores_binding(self, state: BotState, binding: ChannelBinding) -> None:
        state.bind_channel(binding)
        assert state.get_binding(CHANNEL_ID) == binding

    def test_get_binding_returns_none_when_absent(self, state: BotState) -> None:
        assert state.get_binding(CHANNEL_ID) is None

    def test_unbind_channel_removes_binding(
        self, state: BotState, binding: ChannelBinding
    ) -> None:
        state.bind_channel(binding)
        state.unbind_channel(CHANNEL_ID)
        assert state.get_binding(CHANNEL_ID) is None

    def test_unbind_channel_is_idempotent(self, state: BotState) -> None:
        state.unbind_channel(CHANNEL_ID)  # should not raise

    def test_bind_second_channel(self, state: BotState, binding: ChannelBinding) -> None:
        other_channel = 999999999
        other = ChannelBinding(
            channel_id=other_channel, campaign_id=uuid.uuid4(), guild_id=GUILD_ID
        )
        state.bind_channel(binding)
        state.bind_channel(other)
        assert state.get_binding(CHANNEL_ID) == binding
        assert state.get_binding(other_channel) == other


# ---------------------------------------------------------------------------
# BotState — game mode
# ---------------------------------------------------------------------------


class TestGameMode:
    def test_is_game_mode_false_by_default(self, state: BotState) -> None:
        assert not state.is_game_mode(CHANNEL_ID)

    def test_set_game_mode_activates_channel(self, state: BotState) -> None:
        state.set_game_mode(CHANNEL_ID)
        assert state.is_game_mode(CHANNEL_ID)

    def test_clear_game_mode_deactivates_channel(self, state: BotState) -> None:
        state.set_game_mode(CHANNEL_ID)
        state.clear_game_mode(CHANNEL_ID)
        assert not state.is_game_mode(CHANNEL_ID)

    def test_clear_game_mode_is_idempotent(self, state: BotState) -> None:
        state.clear_game_mode(CHANNEL_ID)  # should not raise

    def test_game_mode_is_per_channel(self, state: BotState) -> None:
        other_channel = 999999999
        state.set_game_mode(CHANNEL_ID)
        assert not state.is_game_mode(other_channel)


# ---------------------------------------------------------------------------
# BotState — pending rolls
# ---------------------------------------------------------------------------


class TestPendingRolls:
    def test_has_pending_roll_false_by_default(self, state: BotState) -> None:
        assert not state.has_pending_roll(CHANNEL_ID)

    def test_set_pending_roll_stores_roll(
        self, state: BotState, pending_roll: PendingRoll
    ) -> None:
        state.set_pending_roll(pending_roll)
        assert state.get_pending_roll(CHANNEL_ID) == pending_roll

    def test_has_pending_roll_true_after_set(
        self, state: BotState, pending_roll: PendingRoll
    ) -> None:
        state.set_pending_roll(pending_roll)
        assert state.has_pending_roll(CHANNEL_ID)

    def test_clear_pending_roll_removes_roll(
        self, state: BotState, pending_roll: PendingRoll
    ) -> None:
        state.set_pending_roll(pending_roll)
        state.clear_pending_roll(CHANNEL_ID)
        assert state.get_pending_roll(CHANNEL_ID) is None
        assert not state.has_pending_roll(CHANNEL_ID)

    def test_clear_pending_roll_is_idempotent(self, state: BotState) -> None:
        state.clear_pending_roll(CHANNEL_ID)  # should not raise

    def test_set_pending_roll_overwrites_previous(
        self, state: BotState, pending_roll: PendingRoll
    ) -> None:
        new_roll = PendingRoll(
            channel_id=CHANNEL_ID,
            turn_id=uuid.uuid4(),
            roll_id=uuid.uuid4(),
            character_id=CHARACTER_ID,
            expires_at=datetime.now(UTC) + timedelta(seconds=120),
        )
        state.set_pending_roll(pending_roll)
        state.set_pending_roll(new_roll)
        assert state.get_pending_roll(CHANNEL_ID) == new_roll


# ---------------------------------------------------------------------------
# BotState — reaction windows
# ---------------------------------------------------------------------------


class TestReactionWindows:
    def test_has_reaction_window_false_by_default(self, state: BotState) -> None:
        assert not state.has_reaction_window(ROLL_ID)

    def test_set_and_get_reaction_window(
        self, state: BotState, reaction_window: ReactionWindow
    ) -> None:
        state.set_reaction_window(reaction_window)
        assert state.get_reaction_window(ROLL_ID) == reaction_window

    def test_accepts_str_roll_id_for_get(
        self, state: BotState, reaction_window: ReactionWindow
    ) -> None:
        state.set_reaction_window(reaction_window)
        assert state.get_reaction_window(str(ROLL_ID)) == reaction_window

    def test_clear_reaction_window_removes_it(
        self, state: BotState, reaction_window: ReactionWindow
    ) -> None:
        state.set_reaction_window(reaction_window)
        state.clear_reaction_window(ROLL_ID)
        assert state.get_reaction_window(ROLL_ID) is None
        assert not state.has_reaction_window(ROLL_ID)

    def test_clear_reaction_window_is_idempotent(self, state: BotState) -> None:
        state.clear_reaction_window(ROLL_ID)  # should not raise

    def test_multiple_reaction_windows_independent(self, state: BotState) -> None:
        roll_a = uuid.uuid4()
        roll_b = uuid.uuid4()
        win_a = ReactionWindow(roll_id=roll_a)
        win_b = ReactionWindow(roll_id=roll_b)
        state.set_reaction_window(win_a)
        state.set_reaction_window(win_b)
        state.clear_reaction_window(roll_a)
        assert state.get_reaction_window(roll_a) is None
        assert state.get_reaction_window(roll_b) == win_b
