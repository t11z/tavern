"""Tests for the Narrator and AnthropicProvider.

All tests mock the Anthropic API — no real API calls are made.
The AsyncMock replaces AsyncAnthropic.messages.create with a fake that
returns a response object matching the shape of the real API response.
"""

from __future__ import annotations

import logging
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest

from tavern.dm.context_builder import SceneContext, StateSnapshot, TurnContext
from tavern.dm.narrator import (
    MODEL_MAP,
    NARRATION_MAX_TOKENS,
    NARRATION_TEMPERATURE,
    SUMMARY_MAX_TOKENS,
    SUMMARY_TEMPERATURE,
    AnthropicProvider,
    LLMProvider,
    Narrator,
    _is_simple_action,
    _validate_structured_output,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_NARRATIVE = (
    "The goblin crumples to the ground with a wet gurgle, "
    "its rusty blade clattering on the stone floor. "
    "Silence settles over the corridor."
)


def _make_response(text: str) -> MagicMock:
    """Build a minimal mock that looks like an Anthropic messages response."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_snapshot(
    player_action: str = "I open the door",
    rules_result: str | None = None,
) -> StateSnapshot:
    """Minimal StateSnapshot for routing and serialisation tests."""
    return StateSnapshot(
        system_prompt="You are a DM.",
        characters=[],
        scene=SceneContext(
            location="The Dungeon",
            description="Dark corridors stretch ahead.",
            npcs=[],
            environment="dimly lit",
            threats=[],
            time_of_day="night",
        ),
        rolling_summary="The party descended into the dungeon.",
        current_turn=TurnContext(
            player_action=player_action,
            rules_result=rules_result,
        ),
    )


@pytest.fixture
def provider() -> AnthropicProvider:
    """AnthropicProvider with a dummy API key; messages.create is not mocked here."""
    return AnthropicProvider(api_key="test-key")


@pytest.fixture
def mock_provider() -> LLMProvider:
    """In-memory LLMProvider mock that implements the protocol."""

    class _MockProvider:
        def __init__(self) -> None:
            self.last_tier: Literal["high", "low"] | None = None
            self.last_snapshot: StateSnapshot | None = None
            self.narrate_return = FAKE_NARRATIVE
            self.summary_return = "Summary updated."

        async def narrate(
            self,
            snapshot: StateSnapshot,
            model_tier: Literal["high", "low"],
        ) -> str:
            self.last_tier = model_tier
            self.last_snapshot = snapshot
            return self.narrate_return

        async def compress_summary(
            self,
            turns: list[str],
            current_summary: str,
            max_tokens: int = 500,
        ) -> str:
            return self.summary_return

    return _MockProvider()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_anthropic_provider_satisfies_llm_provider_protocol(
        self, provider: AnthropicProvider
    ) -> None:
        """AnthropicProvider must be structurally compatible with LLMProvider."""
        # Runtime protocol check: both methods must exist with correct names
        assert hasattr(provider, "narrate")
        assert hasattr(provider, "compress_summary")
        assert callable(provider.narrate)
        assert callable(provider.compress_summary)

    def test_llm_provider_is_a_protocol(self) -> None:

        import typing

        # LLMProvider is defined as Protocol — verify it has runtime_checkable interface
        assert issubclass(LLMProvider, typing.Protocol)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Model tier mapping
# ---------------------------------------------------------------------------


class TestModelTierMapping:
    def test_high_tier_maps_to_sonnet(self) -> None:
        assert MODEL_MAP["high"] == "claude-sonnet-4-20250514"

    def test_low_tier_maps_to_haiku(self) -> None:
        assert MODEL_MAP["low"] == "claude-haiku-4-5-20251001"

    def test_model_map_has_exactly_two_tiers(self) -> None:
        assert set(MODEL_MAP) == {"high", "low"}

    async def test_narrate_passes_high_tier_model_to_api(
        self, provider: AnthropicProvider
    ) -> None:
        snapshot = _make_snapshot()
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(snapshot, "high")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == MODEL_MAP["high"]

    async def test_narrate_passes_low_tier_model_to_api(self, provider: AnthropicProvider) -> None:
        snapshot = _make_snapshot()
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(snapshot, "low")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == MODEL_MAP["low"]


# ---------------------------------------------------------------------------
# AnthropicProvider.narrate
# ---------------------------------------------------------------------------


class TestAnthropicProviderNarrate:
    async def test_returns_text_from_response(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        result = await provider.narrate(_make_snapshot(), "high")

        assert result == FAKE_NARRATIVE

    async def test_uses_correct_max_tokens(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(_make_snapshot(), "high")

        assert mock_create.call_args.kwargs["max_tokens"] == NARRATION_MAX_TOKENS

    async def test_uses_correct_temperature(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(_make_snapshot(), "high")

        assert mock_create.call_args.kwargs["temperature"] == NARRATION_TEMPERATURE

    async def test_system_prompt_has_cache_control(self, provider: AnthropicProvider) -> None:
        """System prompt must carry cache_control ephemeral for prompt caching (ADR-0002)."""
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(_make_snapshot(), "high")

        system_param = mock_create.call_args.kwargs["system"]
        assert isinstance(system_param, list)
        assert system_param[0]["cache_control"] == {"type": "ephemeral"}
        assert system_param[0]["type"] == "text"

    async def test_user_message_is_assembled_from_snapshot(
        self, provider: AnthropicProvider
    ) -> None:
        snapshot = _make_snapshot(player_action="I search the chest")
        mock_create = AsyncMock(return_value=_make_response(FAKE_NARRATIVE))
        provider._client.messages.create = mock_create

        await provider.narrate(snapshot, "high")

        messages_param = mock_create.call_args.kwargs["messages"]
        assert messages_param[0]["role"] == "user"
        assert "I search the chest" in messages_param[0]["content"]

    async def test_timeout_raises_timeout_error(self, provider: AnthropicProvider) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=request)
        )

        with pytest.raises(TimeoutError, match="timed out"):
            await provider.narrate(_make_snapshot(), "high")

    async def test_rate_limit_raises_runtime_error_with_retry_hint(
        self, provider: AnthropicProvider
    ) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raw_response = httpx.Response(429, request=request)
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                "rate limit",
                response=raw_response,
                body=None,
            )
        )

        with pytest.raises(RuntimeError, match="retry"):
            await provider.narrate(_make_snapshot(), "high")

    async def test_empty_response_raises_value_error(self, provider: AnthropicProvider) -> None:
        empty_response = MagicMock()
        empty_response.content = []
        provider._client.messages.create = AsyncMock(return_value=empty_response)

        with pytest.raises(ValueError, match="empty"):
            await provider.narrate(_make_snapshot(), "high")


# ---------------------------------------------------------------------------
# AnthropicProvider.compress_summary
# ---------------------------------------------------------------------------


class TestAnthropicProviderCompressSummary:
    async def test_always_uses_low_tier_model(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1: party moved north."], "Prior summary.")

        assert mock_create.call_args.kwargs["model"] == MODEL_MAP["low"]

    async def test_uses_low_temperature_for_compression(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1."], "")

        assert mock_create.call_args.kwargs["temperature"] == SUMMARY_TEMPERATURE

    async def test_prompt_includes_current_summary(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        current = "Party is in the dungeon."
        await provider.compress_summary(["Turn 1."], current)

        prompt = mock_create.call_args.kwargs["messages"][0]["content"]
        assert current in prompt

    async def test_prompt_includes_new_turns(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        turns = ["Turn 5: Kira cast Burning Hands.", "Turn 6: Aldric struck the skeleton."]
        await provider.compress_summary(turns, "")

        prompt = mock_create.call_args.kwargs["messages"][0]["content"]
        assert "Kira cast Burning Hands" in prompt
        assert "Aldric struck the skeleton" in prompt

    async def test_respects_custom_max_tokens(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1."], "", max_tokens=300)

        assert mock_create.call_args.kwargs["max_tokens"] == 300

    async def test_default_max_tokens_is_summary_budget(self, provider: AnthropicProvider) -> None:
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1."], "")

        assert mock_create.call_args.kwargs["max_tokens"] == SUMMARY_MAX_TOKENS

    async def test_returns_compressed_text(self, provider: AnthropicProvider) -> None:
        expected = "Turn 1-3: Party entered dungeon, fought goblins, found key."
        mock_create = AsyncMock(return_value=_make_response(expected))
        provider._client.messages.create = mock_create

        result = await provider.compress_summary(["Turn 1.", "Turn 2.", "Turn 3."], "")

        assert result == expected

    async def test_timeout_raises_timeout_error(self, provider: AnthropicProvider) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=request)
        )

        with pytest.raises(TimeoutError):
            await provider.compress_summary(["Turn 1."], "")

    async def test_empty_response_raises_value_error(self, provider: AnthropicProvider) -> None:
        empty = MagicMock()
        empty.content = []
        provider._client.messages.create = AsyncMock(return_value=empty)

        with pytest.raises(ValueError):
            await provider.compress_summary(["Turn 1."], "")

    async def test_both_empty_returns_empty_without_api_call(
        self, provider: AnthropicProvider
    ) -> None:
        """When both turns and current_summary are empty, skip the API call entirely."""
        mock_create = AsyncMock()
        provider._client.messages.create = mock_create

        result = await provider.compress_summary([], "")

        assert result == ""
        mock_create.assert_not_called()

    async def test_whitespace_only_inputs_return_empty_without_api_call(
        self, provider: AnthropicProvider
    ) -> None:
        mock_create = AsyncMock()
        provider._client.messages.create = mock_create

        result = await provider.compress_summary([], "   ")

        assert result == ""
        mock_create.assert_not_called()

    async def test_has_system_prompt(self, provider: AnthropicProvider) -> None:
        """compress_summary must send a system prompt to lock Claude into compressor role."""
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1."], "")

        kwargs = mock_create.call_args.kwargs
        assert "system" in kwargs
        system = kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["type"] == "text"
        assert "compressor" in system[0]["text"].lower()

    async def test_prompt_uses_section_headers(self, provider: AnthropicProvider) -> None:
        """User message must use EXISTING SUMMARY / NEW TURNS headers."""
        mock_create = AsyncMock(return_value=_make_response("Compressed."))
        provider._client.messages.create = mock_create

        await provider.compress_summary(["Turn 1: party moved north."], "Prior events.")

        prompt = mock_create.call_args.kwargs["messages"][0]["content"]
        assert "EXISTING SUMMARY:" in prompt
        assert "NEW TURNS:" in prompt

    async def test_bleed_through_falls_back_to_current_summary(
        self, provider: AnthropicProvider
    ) -> None:
        """If the API returns conversational text, compress_summary returns current_summary."""
        bleed = "I'd be happy to help compress your session notes!"
        mock_create = AsyncMock(return_value=_make_response(bleed))
        provider._client.messages.create = mock_create

        prior = "Party entered the dungeon and defeated two goblins."
        result = await provider.compress_summary(["Turn 7: Kael searched the room."], prior)

        assert result == prior

    async def test_bleed_through_logs_error(
        self, provider: AnthropicProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        bleed = "I'd be happy to help compress your session notes!"
        mock_create = AsyncMock(return_value=_make_response(bleed))
        provider._client.messages.create = mock_create

        with caplog.at_level(logging.ERROR, logger="tavern.dm.narrator"):
            await provider.compress_summary(["Turn 1."], "Prior summary.")

        assert any("invalid output" in r.message for r in caplog.records)

    async def test_question_mark_in_output_falls_back(self, provider: AnthropicProvider) -> None:
        """A question mark in summary output is a bleed-through signal."""
        mock_create = AsyncMock(return_value=_make_response("Could you clarify what happened?"))
        provider._client.messages.create = mock_create

        prior = "Prior summary."
        result = await provider.compress_summary(["Turn 1."], prior)

        assert result == prior

    async def test_valid_summary_is_returned_unchanged(self, provider: AnthropicProvider) -> None:
        """Clean summary text passes validation and is returned as-is."""
        summary = (
            "Turn 1-3: Party entered dungeon, fought goblins (12 slashing damage), found key."
        )
        mock_create = AsyncMock(return_value=_make_response(summary))
        provider._client.messages.create = mock_create

        result = await provider.compress_summary(["Turn 3: party found key."], "Prior.")

        assert result == summary


# ---------------------------------------------------------------------------
# _validate_structured_output
# ---------------------------------------------------------------------------


class TestValidateStructuredOutput:
    def test_clean_text_passes(self) -> None:
        assert (
            _validate_structured_output("Party fought three goblins and retreated north.", "Test")
            is True
        )

    def test_question_mark_fails(self) -> None:
        assert _validate_structured_output("What would you like me to compress?", "Test") is False

    def test_assistant_phrase_fails(self) -> None:
        assert _validate_structured_output("I'd be happy to help with that.", "Test") is False

    def test_phrase_check_is_case_insensitive(self) -> None:
        assert _validate_structured_output("HERE'S a summary for you.", "Test") is False

    def test_mechanical_content_passes(self) -> None:
        text = "Kira cast Fireball. Three orcs took 28 fire damage. Session ended at the inn."
        assert _validate_structured_output(text, "Test") is True

    def test_logs_warning_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            _validate_structured_output("Let me know if you need anything!", "Summary compression")

        assert any("bleed-through" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Routing logic (_is_simple_action)
# ---------------------------------------------------------------------------


class TestIsSimpleAction:
    def test_short_non_combat_action_is_simple(self) -> None:
        assert _is_simple_action("I open the door") is True

    def test_long_action_is_not_simple(self) -> None:
        # 20+ words
        long_action = " ".join(["word"] * 20)
        assert _is_simple_action(long_action) is False

    def test_attack_keyword_is_not_simple(self) -> None:
        assert _is_simple_action("I attack the goblin") is False

    def test_cast_keyword_is_not_simple(self) -> None:
        assert _is_simple_action("I cast fireball at the guards") is False

    def test_short_spell_action_is_not_simple(self) -> None:
        assert _is_simple_action("I cast Mage Hand") is False

    def test_examine_object_is_simple(self) -> None:
        assert _is_simple_action("I examine the bookshelf") is True

    def test_pick_up_item_is_simple(self) -> None:
        assert _is_simple_action("I pick up the torch") is True

    def test_nineteen_word_action_is_simple(self) -> None:
        action = " ".join(["walk"] * 19)
        assert _is_simple_action(action) is True

    def test_exactly_twenty_words_is_not_simple(self) -> None:
        action = " ".join(["walk"] * 20)
        assert _is_simple_action(action) is False


# ---------------------------------------------------------------------------
# Narrator routing
# ---------------------------------------------------------------------------


class TestNarratorRouting:
    async def test_combat_turn_uses_high_tier(self, mock_provider: LLMProvider) -> None:
        """Turn with rules_result (combat) → Sonnet (ADR-0002)."""
        narrator = Narrator(provider=mock_provider)
        snapshot = _make_snapshot(
            player_action="I attack the orc",
            rules_result="Attack hits. 12 slashing damage.",
        )

        await narrator.narrate_turn(snapshot)

        assert mock_provider.last_tier == "high"  # type: ignore[attr-defined]

    async def test_simple_action_without_result_uses_low_tier(
        self, mock_provider: LLMProvider
    ) -> None:
        """Simple action, no mechanical result → Haiku (ADR-0002)."""
        narrator = Narrator(provider=mock_provider)
        snapshot = _make_snapshot(
            player_action="I open the door",
            rules_result=None,
        )

        await narrator.narrate_turn(snapshot)

        assert mock_provider.last_tier == "low"  # type: ignore[attr-defined]

    async def test_complex_action_without_result_uses_high_tier(
        self, mock_provider: LLMProvider
    ) -> None:
        """Long / complex action with no rules_result still uses Sonnet (fail safe)."""
        narrator = Narrator(provider=mock_provider)
        snapshot = _make_snapshot(
            player_action=(
                "I carefully examine the ancient runes on the door and try to decipher "
                "their meaning by cross-referencing my knowledge of Elvish history"
            ),
            rules_result=None,
        )

        await narrator.narrate_turn(snapshot)

        assert mock_provider.last_tier == "high"  # type: ignore[attr-defined]

    async def test_spell_action_without_result_uses_high_tier(
        self, mock_provider: LLMProvider
    ) -> None:
        narrator = Narrator(provider=mock_provider)
        snapshot = _make_snapshot(
            player_action="I cast Detect Magic",
            rules_result=None,
        )

        await narrator.narrate_turn(snapshot)

        assert mock_provider.last_tier == "high"  # type: ignore[attr-defined]

    async def test_default_is_always_high_tier(self, mock_provider: LLMProvider) -> None:
        """Any ambiguous or borderline action defaults to Sonnet (ADR-0002 fail safe)."""
        narrator = Narrator(provider=mock_provider)
        # rules_result present → always high
        snapshot = _make_snapshot(
            player_action="I nod",
            rules_result="Initiative check: 14",
        )

        await narrator.narrate_turn(snapshot)

        assert mock_provider.last_tier == "high"  # type: ignore[attr-defined]

    async def test_returns_narrative_from_provider(self, mock_provider: LLMProvider) -> None:
        narrator = Narrator(provider=mock_provider)
        result = await narrator.narrate_turn(_make_snapshot())
        assert result == FAKE_NARRATIVE


# ---------------------------------------------------------------------------
# Summary delegation
# ---------------------------------------------------------------------------


class TestNarratorUpdateSummary:
    async def test_delegates_to_provider_compress_summary(
        self, mock_provider: LLMProvider
    ) -> None:
        narrator = Narrator(provider=mock_provider)
        result = await narrator.update_summary(
            ["Turn 1: party moved north."],
            "Prior summary.",
        )
        assert result == "Summary updated."

    async def test_always_uses_provider_compress_regardless_of_content(
        self, mock_provider: LLMProvider
    ) -> None:
        """Summary compression always goes through provider (Haiku per ADR-0002)."""
        narrator = Narrator(provider=mock_provider)
        # Even empty turns should still call compress_summary
        result = await narrator.update_summary([], "")
        assert result == "Summary updated."


# ---------------------------------------------------------------------------
# Response validation warnings
# ---------------------------------------------------------------------------


class TestResponseValidation:
    async def test_markdown_bold_triggers_warning(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_provider.narrate_return = "The **goblin** falls."  # type: ignore[attr-defined]
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            await narrator.narrate_turn(_make_snapshot())

        assert any("Markdown" in record.message for record in caplog.records)

    async def test_markdown_heading_triggers_warning(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_provider.narrate_return = "# Scene\nThe goblin falls."  # type: ignore[attr-defined]
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            await narrator.narrate_turn(_make_snapshot())

        assert any("Markdown" in record.message for record in caplog.records)

    async def test_mechanical_damage_number_triggers_warning(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_provider.narrate_return = "You deal 14 damage to the goblin."  # type: ignore[attr-defined]
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            await narrator.narrate_turn(_make_snapshot())

        assert any("mechanical" in record.message for record in caplog.records)

    async def test_hp_value_triggers_warning(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_provider.narrate_return = "The goblin has 5 HP remaining."  # type: ignore[attr-defined]
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            await narrator.narrate_turn(_make_snapshot())

        assert any("mechanical" in record.message for record in caplog.records)

    async def test_clean_plain_text_produces_no_warning(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_provider.narrate_return = (  # type: ignore[attr-defined]
            "The goblin crumples to the floor, its eyes glazing over. "
            "A heavy silence settles over the corridor."
        )
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            await narrator.narrate_turn(_make_snapshot())

        assert len(caplog.records) == 0

    async def test_narrative_returned_even_when_warning_logged(
        self, mock_provider: LLMProvider, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning does not suppress the narrative — that decision belongs to the caller."""
        bad_text = "You deal **14 damage** to the goblin."
        mock_provider.narrate_return = bad_text  # type: ignore[attr-defined]
        narrator = Narrator(provider=mock_provider)

        with caplog.at_level(logging.WARNING, logger="tavern.dm.narrator"):
            result = await narrator.narrate_turn(_make_snapshot())

        assert result == bad_text


# ---------------------------------------------------------------------------
# AnthropicProvider.generate_campaign_brief — bleed-through validation
# ---------------------------------------------------------------------------


class TestGenerateCampaignBriefValidation:
    async def test_bleed_through_raises_value_error(self, provider: AnthropicProvider) -> None:
        """If the raw response is conversational instead of JSON, raise ValueError."""
        bleed = "I'd be happy to help you set up your campaign! What tone do you prefer?"
        mock_create = AsyncMock(return_value=_make_response(bleed))
        provider._client.messages.create = mock_create

        with pytest.raises(ValueError, match="conversational"):
            await provider.generate_campaign_brief("Lost Throne", "classic_fantasy")

    async def test_valid_json_response_succeeds(self, provider: AnthropicProvider) -> None:
        valid_json = (
            '{"campaign_brief": "A perilous quest.", "opening_scene": "The inn is quiet.", '
            '"location": "Silverveil", "environment": "foggy village", "time_of_day": "evening"}'
        )
        mock_create = AsyncMock(return_value=_make_response(valid_json))
        provider._client.messages.create = mock_create

        result = await provider.generate_campaign_brief("Lost Throne", "classic_fantasy")

        assert result["location"] == "Silverveil"
