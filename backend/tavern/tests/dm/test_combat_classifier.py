"""Tests for dm/combat_classifier.py (ADR-0011).

All tests mock the Anthropic API — no real API calls are made.
Covers CombatClassifier.classify() and TurnContext.stealth_rolls.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from tavern.dm.combat_classifier import CombatClassification, CombatClassifier
from tavern.dm.context_builder import SceneContext, StateSnapshot, TurnContext

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    session_mode: str = "exploration",
    npcs: list[str] | None = None,
    threats: list[str] | None = None,
    location: str = "Harbormaster's office",
) -> StateSnapshot:
    """Minimal StateSnapshot for classifier tests."""
    return StateSnapshot(
        system_prompt="You are a DM.",
        characters=[],
        scene=SceneContext(
            location=location,
            description="A cluttered dockside office.",
            npcs=npcs or ["Harbormaster Talis — neutral"],
            environment="dimly lit",
            threats=threats or [],
            time_of_day="afternoon",
        ),
        rolling_summary="The party arrived at the harbour.",
        current_turn=TurnContext(
            player_action="placeholder",
            rules_result=None,
        ),
        session_mode=session_mode,
    )


def _make_api_response(text: str) -> MagicMock:
    """Build a minimal mock that looks like an Anthropic messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


def _json_response(
    combat_starts: bool,
    combatants: list[str] | None = None,
    confidence: str = "high",
    reason: str = "Test reason.",
) -> str:
    return json.dumps(
        {
            "combat_starts": combat_starts,
            "combatants": combatants or [],
            "confidence": confidence,
            "reason": reason,
        }
    )


@pytest.fixture
def classifier() -> CombatClassifier:
    """CombatClassifier with a dummy API key; messages.create is not mocked here."""
    return CombatClassifier(api_key="test-key")


# ---------------------------------------------------------------------------
# classify() — positive combat detection
# ---------------------------------------------------------------------------


class TestClassifyAttackAction:
    async def test_attack_action_returns_combat_starts_true(
        self, classifier: CombatClassifier
    ) -> None:
        """'I attack the guard with my sword' → combat_starts=True."""
        snapshot = _make_snapshot(npcs=["Guard — hostile"])
        mock_create = AsyncMock(
            return_value=_make_api_response(
                _json_response(
                    combat_starts=True,
                    combatants=["Guard"],
                    confidence="high",
                    reason="Direct melee attack on a guard.",
                )
            )
        )
        classifier._client.messages.create = mock_create

        result, _meta = await classifier.classify("I attack the guard with my sword", snapshot)

        assert result.combat_starts is True
        assert result.confidence == "high"
        assert isinstance(result.combatants, list)

    async def test_attack_action_calls_api_with_action_in_message(
        self, classifier: CombatClassifier
    ) -> None:
        """The action text must appear in the user message sent to the API."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=True))
        )
        classifier._client.messages.create = mock_create

        await classifier.classify("I attack the guard with my sword", snapshot)

        call_kwargs = mock_create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "I attack the guard with my sword" in user_content


# ---------------------------------------------------------------------------
# classify() — negative (non-combat) detection
# ---------------------------------------------------------------------------


class TestClassifyNonCombatActions:
    async def test_draw_sword_returns_combat_starts_false(
        self, classifier: CombatClassifier
    ) -> None:
        """'I draw my sword menacingly' → combat_starts=False."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(
                _json_response(
                    combat_starts=False,
                    combatants=[],
                    confidence="high",
                    reason="Drawing a weapon without attacking is not combat initiation.",
                )
            )
        )
        classifier._client.messages.create = mock_create

        result, _meta = await classifier.classify("I draw my sword menacingly", snapshot)

        assert result.combat_starts is False

    async def test_approach_harbormaster_returns_combat_starts_false(
        self, classifier: CombatClassifier
    ) -> None:
        """'I approach the harbormaster' → combat_starts=False."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(
                _json_response(
                    combat_starts=False,
                    combatants=[],
                    confidence="high",
                    reason="Approaching an NPC is movement, not an attack.",
                )
            )
        )
        classifier._client.messages.create = mock_create

        result, _meta = await classifier.classify("I approach the harbormaster", snapshot)

        assert result.combat_starts is False

    async def test_non_combat_result_has_correct_fields(
        self, classifier: CombatClassifier
    ) -> None:
        """Non-combat result should be a well-formed CombatClassification."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        result, _meta = await classifier.classify("I look around the room", snapshot)

        assert isinstance(result, CombatClassification)
        assert result.combat_starts is False
        assert isinstance(result.combatants, list)
        assert result.confidence in ("high", "low")
        assert isinstance(result.reason, str)


# ---------------------------------------------------------------------------
# classify() — error handling
# ---------------------------------------------------------------------------


class TestClassifyErrorHandling:
    async def test_api_error_returns_safe_fallback(self, classifier: CombatClassifier) -> None:
        """API error → safe fallback (combat_starts=False, confidence='low')."""
        snapshot = _make_snapshot()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        classifier._client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=request)
        )

        result, _meta = await classifier.classify("I attack the guard", snapshot)

        assert result.combat_starts is False
        assert result.combatants == []
        assert result.confidence == "low"

    async def test_rate_limit_error_returns_safe_fallback(
        self, classifier: CombatClassifier
    ) -> None:
        """Rate limit error → safe fallback."""
        snapshot = _make_snapshot()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raw_response = httpx.Response(429, request=request)
        classifier._client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                "rate limit",
                response=raw_response,
                body=None,
            )
        )

        result, _meta = await classifier.classify("I attack the guard", snapshot)

        assert result.combat_starts is False
        assert result.confidence == "low"

    async def test_malformed_json_returns_safe_fallback(
        self, classifier: CombatClassifier
    ) -> None:
        """Non-JSON response → safe fallback."""
        snapshot = _make_snapshot()
        classifier._client.messages.create = AsyncMock(
            return_value=_make_api_response("Sorry, I cannot help with that.")
        )

        result, _meta = await classifier.classify("I attack the guard", snapshot)

        assert result.combat_starts is False
        assert result.combatants == []
        assert result.confidence == "low"

    async def test_missing_field_in_json_returns_safe_fallback(
        self, classifier: CombatClassifier
    ) -> None:
        """JSON with missing required field → safe fallback."""
        snapshot = _make_snapshot()
        incomplete = json.dumps({"combat_starts": True, "combatants": []})
        classifier._client.messages.create = AsyncMock(return_value=_make_api_response(incomplete))

        result, _meta = await classifier.classify("I attack the guard", snapshot)

        assert result.combat_starts is False
        assert result.confidence == "low"

    async def test_wrong_type_in_json_returns_safe_fallback(
        self, classifier: CombatClassifier
    ) -> None:
        """JSON with wrong type for combat_starts → safe fallback."""
        snapshot = _make_snapshot()
        bad_schema = json.dumps(
            {
                "combat_starts": "yes",  # should be bool
                "combatants": [],
                "confidence": "high",
                "reason": "test",
            }
        )
        classifier._client.messages.create = AsyncMock(return_value=_make_api_response(bad_schema))

        result, _meta = await classifier.classify("I attack the guard", snapshot)

        assert result.combat_starts is False
        assert result.confidence == "low"

    async def test_api_error_is_logged(
        self, classifier: CombatClassifier, caplog: pytest.LogCaptureFixture
    ) -> None:
        """API errors must be logged at ERROR level."""
        snapshot = _make_snapshot()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        classifier._client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=request)
        )

        with caplog.at_level(logging.ERROR, logger="tavern.dm.combat_classifier"):
            await classifier.classify("I attack", snapshot)

        assert any(record.levelno >= logging.ERROR for record in caplog.records)

    async def test_malformed_json_is_logged(
        self, classifier: CombatClassifier, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Malformed JSON must be logged at ERROR level."""
        snapshot = _make_snapshot()
        classifier._client.messages.create = AsyncMock(
            return_value=_make_api_response("not json {{{{")
        )

        with caplog.at_level(logging.ERROR, logger="tavern.dm.combat_classifier"):
            await classifier.classify("I attack", snapshot)

        assert any(record.levelno >= logging.ERROR for record in caplog.records)


# ---------------------------------------------------------------------------
# classify() — combat mode guard
# ---------------------------------------------------------------------------


class TestCombatModeGuard:
    async def test_raises_runtime_error_in_combat_mode(self, classifier: CombatClassifier) -> None:
        """classify() must raise RuntimeError when session_mode is 'combat'."""
        snapshot = _make_snapshot(session_mode="combat")

        with pytest.raises(RuntimeError, match="combat mode"):
            await classifier.classify("I attack the guard", snapshot)

    async def test_does_not_call_api_in_combat_mode(self, classifier: CombatClassifier) -> None:
        """No API call should be made when the guard fires."""
        snapshot = _make_snapshot(session_mode="combat")
        mock_create = AsyncMock()
        classifier._client.messages.create = mock_create

        with pytest.raises(RuntimeError):
            await classifier.classify("I attack the guard", snapshot)

        mock_create.assert_not_called()

    async def test_does_not_raise_in_exploration_mode(self, classifier: CombatClassifier) -> None:
        """classify() should not raise for session_mode='exploration'."""
        snapshot = _make_snapshot(session_mode="exploration")
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        result, _meta = await classifier.classify("I look around", snapshot)

        assert isinstance(result, CombatClassification)


# ---------------------------------------------------------------------------
# classify() — uses correct model and parameters
# ---------------------------------------------------------------------------


class TestClassifierApiParameters:
    async def test_uses_haiku_model(self, classifier: CombatClassifier) -> None:
        """Classifier must use Haiku per ADR-0011 §4."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        await classifier.classify("I look around", snapshot)

        assert mock_create.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"

    async def test_uses_max_tokens_150(self, classifier: CombatClassifier) -> None:
        """max_tokens must be 150 per ADR-0011 §4 token budget."""
        snapshot = _make_snapshot()
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        await classifier.classify("I look around", snapshot)

        assert mock_create.call_args.kwargs["max_tokens"] == 150

    async def test_scene_npcs_included_in_user_message(self, classifier: CombatClassifier) -> None:
        """NPC names from the snapshot scene must appear in the user message."""
        snapshot = _make_snapshot(npcs=["Guard Captain Rook — hostile", "Dockworker — neutral"])
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        await classifier.classify("I threaten the captain", snapshot)

        user_content = mock_create.call_args.kwargs["messages"][0]["content"]
        assert "Guard Captain Rook" in user_content

    async def test_location_included_in_user_message(self, classifier: CombatClassifier) -> None:
        """Location from the snapshot scene must appear in the user message."""
        snapshot = _make_snapshot(location="Rusty Anchor Tavern")
        mock_create = AsyncMock(
            return_value=_make_api_response(_json_response(combat_starts=False))
        )
        classifier._client.messages.create = mock_create

        await classifier.classify("I look around", snapshot)

        user_content = mock_create.call_args.kwargs["messages"][0]["content"]
        assert "Rusty Anchor Tavern" in user_content


# ---------------------------------------------------------------------------
# TurnContext.stealth_rolls — dataclass field
# ---------------------------------------------------------------------------


class TestTurnContextStealthRolls:
    def test_turn_context_has_stealth_rolls_field(self) -> None:
        """TurnContext must have a stealth_rolls field."""
        turn = TurnContext(player_action="I sneak past the guards.", rules_result=None)
        assert hasattr(turn, "stealth_rolls")

    def test_stealth_rolls_defaults_to_empty_dict(self) -> None:
        """stealth_rolls must default to an empty dict."""
        turn = TurnContext(player_action="I move forward.", rules_result=None)
        assert turn.stealth_rolls == {}

    def test_stealth_rolls_accepts_character_id_to_roll_mapping(self) -> None:
        """stealth_rolls is a dict mapping character_id (str) to roll result (int)."""
        turn = TurnContext(
            player_action="I sneak.",
            rules_result=None,
            stealth_rolls={"char-abc-123": 18, "char-def-456": 12},
        )
        assert turn.stealth_rolls["char-abc-123"] == 18
        assert turn.stealth_rolls["char-def-456"] == 12

    def test_stealth_rolls_default_is_not_shared_between_instances(self) -> None:
        """Mutable default must use field(default_factory=dict), not a shared dict."""
        turn_a = TurnContext(player_action="A", rules_result=None)
        turn_b = TurnContext(player_action="B", rules_result=None)
        turn_a.stealth_rolls["char-1"] = 15
        # Mutation of turn_a must not affect turn_b
        assert turn_b.stealth_rolls == {}

    def test_state_snapshot_session_mode_defaults_to_exploration(self) -> None:
        """StateSnapshot.session_mode must default to 'exploration'."""
        snapshot = _make_snapshot()
        assert snapshot.session_mode == "exploration"

    def test_state_snapshot_session_mode_can_be_set_to_combat(self) -> None:
        """StateSnapshot.session_mode must accept 'combat'."""
        snapshot = _make_snapshot(session_mode="combat")
        assert snapshot.session_mode == "combat"
