"""Narrator — sends state snapshots to Claude and returns narrative responses.

The Narrator is the sole component that communicates with the LLM provider.
It receives a StateSnapshot from the Context Builder, routes it to the
appropriate model tier, and returns plain-text narrative.

Model routing (ADR-0002):
  - "high" tier → Sonnet (narrative responses, NPC dialogue, scene descriptions)
  - "low"  tier → Haiku  (short acknowledgments, summary compression)
  - Default is always "high" — fail safe.

Prompt caching (ADR-0002):
  The system prompt has cache_control: {"type": "ephemeral"} so Anthropic
  caches it across requests in the same session. Component ordering in the
  snapshot (system → characters → scene → summary → turn) ensures maximum
  cache hits. Do not reorder without updating ADR-0002.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Literal, Protocol

import anthropic

from tavern.dm.context_builder import StateSnapshot, serialize_snapshot
from tavern.dm.gm_signals import GM_SIGNALS_DELIMITER, GMSignals, parse_gm_signals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (ADR-0002 model routing)
# ---------------------------------------------------------------------------

MODEL_MAP: dict[str, str] = {
    "high": "claude-sonnet-4-20250514",
    "low": "claude-haiku-4-5-20251001",
}

# GMSignals instruction appended to the system prompt for every narration
# request (ADR-0012, ADR-0013).  The model MUST append the delimiter line and
# JSON block after every narrative response so the turn pipeline can extract
# structured signals without player-facing text being contaminated.
_GM_SIGNALS_INSTRUCTION = (
    "\n\nAfter your narrative response, you MUST always append a GMSignals block "
    "on a new line. The delimiter must appear on its own line with no leading or "
    "trailing spaces, followed immediately by the JSON object on the next line. "
    "Do not omit either element.\n\n"
    "Format (copy exactly):\n"
    f"{GM_SIGNALS_DELIMITER}\n"
    '{"scene_transition": {"type": "none", "combatants": [], '
    '"potential_surprised_characters": [], "reason": ""}, "npc_updates": []}\n\n'
    'Rules for scene_transition.type: must be exactly "none", "combat_start", or '
    '"combat_end". Use "combat_start" only when NPCs initiate an unprovoked attack. '
    'Use "combat_end" only when all hostile NPCs are defeated or fled. '
    '"npc_updates" must be a list (may be empty). Each entry needs "event" '
    '(spawn|status_change|disposition_change|location_change) and "npc_name". '
    "Always include both top-level keys."
)

NARRATION_MAX_TOKENS: int = 1024
NARRATION_TEMPERATURE: float = 0.8
SUMMARY_MAX_TOKENS: int = 500
SUMMARY_TEMPERATURE: float = 0.3  # Low creativity for mechanical compression

# ---------------------------------------------------------------------------
# Routing heuristics
# ---------------------------------------------------------------------------

_SIMPLE_ACTION_MAX_WORDS = 20

# Keywords that indicate a complex / combat action → always route to "high"
_COMPLEX_KEYWORDS = frozenset(
    {
        "attack",
        "cast",
        "spell",
        "hit",
        "damage",
        "fight",
        "stab",
        "shoot",
        "fire",
        "strike",
        "grapple",
        "shove",
        "fireball",
        "lightning",
        "heal",
        "cure",
        "channel",
    }
)

# ---------------------------------------------------------------------------
# Response validation patterns
# ---------------------------------------------------------------------------

_MARKDOWN_RE = re.compile(r"(\*\*|__|\*(?!\s)|_(?!\s)|#{1,6} |`|~~~|---)")
_MECHANICAL_RE = re.compile(r"\b\d+\s*(damage|hp|hit points?|AC|d\d+)\b", re.IGNORECASE)


def _is_simple_action(player_action: str) -> bool:
    """Return True if the action is too simple to warrant Sonnet narration."""
    words = player_action.split()
    if len(words) >= _SIMPLE_ACTION_MAX_WORDS:
        return False
    action_lower = player_action.lower()
    return not any(keyword in action_lower for keyword in _COMPLEX_KEYWORDS)


def _check_response_quality(text: str) -> None:
    """Log warnings if the response violates output format constraints.

    Enforcement is probabilistic — the system prompt should prevent these,
    but monitoring provides a safety net (ADR-0002, Consequences section).
    """
    if _MARKDOWN_RE.search(text):
        logger.warning(
            "Narrator response contains Markdown formatting (system prompt violation): %r",
            text[:200],
        )
    if _MECHANICAL_RE.search(text):
        logger.warning(
            "Narrator response contains mechanical numbers (system prompt violation): %r",
            text[:200],
        )


# Known assistant-mode phrases that should never appear in structured output
_ASSISTANT_BLEED_PHRASES = [
    "I'm ready to",
    "I'd be happy to",
    "Could you please",
    "Let me know",
    "Here's",
    "Here is",
    "I'll help",
    "I can help",
    "Sure!",
    "Of course!",
    "I notice",
    "However, I",
]


def _validate_structured_output(text: str, output_type: str) -> bool:
    """Check if LLM output looks like assistant conversation instead of structured content.

    Returns True if the output passes validation, False if it appears
    to be conversational bleed-through.

    Logs a warning with the output_type label on failure.
    """
    if "?" in text:
        logger.warning(
            "%s output contains question marks (likely assistant bleed-through): %r",
            output_type,
            text[:200],
        )
        return False

    text_lower = text.lower()
    for phrase in _ASSISTANT_BLEED_PHRASES:
        if phrase.lower() in text_lower:
            logger.warning(
                "%s output contains assistant phrase %r (bleed-through): %r",
                output_type,
                phrase,
                text[:200],
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class LLMProvider(Protocol):
    """Interface for LLM providers. Swap implementations without touching Narrator."""

    async def narrate(
        self,
        snapshot: StateSnapshot,
        model_tier: Literal["high", "low"],
    ) -> str:
        """Send the snapshot to the LLM and return narrative plain text."""
        ...

    async def compress_summary(
        self,
        turns: list[str],
        current_summary: str,
        max_tokens: int = 500,
    ) -> str:
        """Compress recent turns into an updated rolling summary."""
        ...


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class AnthropicProvider:
    """LLMProvider implementation backed by the Anthropic Messages API.

    Prompt caching: the system prompt is sent as a list with
    cache_control so Anthropic caches it across requests in the same
    session (0.1× normal input price on cache reads).
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def _build_system_with_signals(self, system_text: str) -> str:
        """Append the GMSignals instruction to the system prompt."""
        return system_text + _GM_SIGNALS_INSTRUCTION

    async def narrate(
        self,
        snapshot: StateSnapshot,
        model_tier: Literal["high", "low"] = "high",
    ) -> str:
        """Send the snapshot to Claude and return the narrative response.

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded (includes retry hint).
            ValueError: If the response contains no content.
        """
        serialized = serialize_snapshot(snapshot)
        system_text: str = serialized["system"]  # type: ignore[assignment]
        system_text = self._build_system_with_signals(system_text)
        messages_list = serialized["messages"]  # type: ignore[assignment]
        user_content: str = messages_list[0]["content"]  # type: ignore[index]

        try:
            response = await self._client.messages.create(
                model=MODEL_MAP[model_tier],
                max_tokens=NARRATION_MAX_TOKENS,
                temperature=NARRATION_TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APITimeoutError as exc:
            raise TimeoutError(f"Anthropic API request timed out: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic API rate limit exceeded — retry after a moment: {exc}"
            ) from exc

        if not response.content:
            raise ValueError("Anthropic API returned an empty response")

        return response.content[0].text  # type: ignore[union-attr]

    async def narrate_stream(
        self,
        snapshot: StateSnapshot,
        model_tier: Literal["high", "low"] = "high",
    ) -> AsyncGenerator[str, None]:
        """Stream narrative tokens from Claude.

        Uses the Anthropic SDK streaming mode. Each yielded value is a
        raw text chunk — callers assemble the full narrative by joining.

        Note: The GMSignals delimiter and JSON tail are included in the raw
        stream.  Use narrate_stream_buffered() when you need the narrative
        text split from the GMSignals block.

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded.
        """
        serialized = serialize_snapshot(snapshot)
        system_text: str = serialized["system"]  # type: ignore[assignment]
        system_text = self._build_system_with_signals(system_text)
        messages_list = serialized["messages"]  # type: ignore[assignment]
        user_content: str = messages_list[0]["content"]  # type: ignore[index]

        try:
            async with self._client.messages.stream(
                model=MODEL_MAP[model_tier],
                max_tokens=NARRATION_MAX_TOKENS,
                temperature=NARRATION_TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.APITimeoutError as exc:
            raise TimeoutError(f"Anthropic API request timed out: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic API rate limit exceeded — retry after a moment: {exc}"
            ) from exc

    async def generate_campaign_brief(self, name: str, tone: str) -> dict[str, str]:
        """Generate a campaign brief and opening scene using Claude Haiku.

        Returns a dict with keys:
            campaign_brief, opening_scene, location, environment, time_of_day

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded.
            ValueError: If the response cannot be parsed or is missing fields.
        """
        prompt = (
            "You are setting up a new D&D 5e campaign. Generate the opening scene.\n\n"
            f"Campaign name: {name}\n"
            f"Tone: {tone}\n\n"
            "Respond with ONLY a JSON object, no other text:\n"
            "{\n"
            '  "campaign_brief": "2-3 sentences describing the campaign premise",\n'
            '  "opening_scene": "2-3 sentences describing what the players see right now",\n'
            '  "location": "Name of the starting location",\n'
            '  "environment": "Atmospheric conditions (e.g., \'dimly lit tavern\')",\n'
            '  "time_of_day": "morning"\n'
            "}"
        )

        try:
            response = await self._client.messages.create(
                model=MODEL_MAP["low"],
                max_tokens=500,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APITimeoutError as exc:
            raise TimeoutError(f"Anthropic API request timed out: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic API rate limit exceeded — retry after a moment: {exc}"
            ) from exc

        if not response.content:
            raise ValueError("Anthropic API returned an empty response")

        raw = response.content[0].text  # type: ignore[union-attr]

        if not _validate_structured_output(raw, "Campaign brief"):
            raise ValueError(
                "Campaign brief response appears to be conversational rather than JSON: "
                f"{raw[:200]!r}"
            )

        # Strip optional markdown code fences before parsing
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        try:
            brief: dict[str, str] = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse campaign brief JSON: {exc}") from exc

        required = {"campaign_brief", "opening_scene", "location", "environment", "time_of_day"}
        missing = required - brief.keys()
        if missing:
            raise ValueError(f"Campaign brief response missing fields: {missing}")

        return brief

    async def compress_summary(
        self,
        turns: list[str],
        current_summary: str,
        max_tokens: int = SUMMARY_MAX_TOKENS,
    ) -> str:
        """Compress recent turns into a rolling summary update using Haiku.

        Always uses the "low" tier — summary compression is mechanical
        text transformation, not creative narration (ADR-0002).

        If both turns and current_summary are empty, returns "" immediately
        without making an API call.

        On bleed-through detection (Claude responds conversationally instead
        of with a summary), logs an error and returns current_summary unchanged.

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded.
            ValueError: If the response contains no content.
        """
        turns_text = "\n".join(turns)
        if not turns_text.strip() and not (current_summary or "").strip():
            return ""

        prompt = (
            "Compress the new turns into the existing summary. "
            "Preserve character names, locations, and mechanical results "
            "(dice rolls, damage, HP changes, spell slots). "
            "Drop verbatim dialogue and atmospheric detail. "
            f"Keep the result under {max_tokens} tokens.\n\n"
            f"EXISTING SUMMARY:\n{current_summary or '(none)'}\n\n"
            f"NEW TURNS:\n{turns_text or '(none)'}"
        )

        try:
            response = await self._client.messages.create(
                model=MODEL_MAP["low"],
                max_tokens=max_tokens,
                temperature=SUMMARY_TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": (
                            "You are a turn-log compressor for a tabletop RPG session. "
                            "Your ONLY output is the compressed summary text. "
                            "Rules:\n"
                            "- Output ONLY the updated summary. Nothing else.\n"
                            "- No preamble. No questions. No meta-commentary.\n"
                            "- No bullet points about what you would do.\n"
                            "- Never ask for clarification.\n"
                            "- Never refer to yourself or your capabilities.\n"
                            "- If the new turns section is empty, return the existing "
                            "summary unchanged.\n"
                            "- If both existing summary and new turns are empty, return "
                            "an empty string."
                        ),
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APITimeoutError as exc:
            raise TimeoutError(
                f"Anthropic API request timed out during summary compression: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic API rate limit exceeded — retry after a moment: {exc}"
            ) from exc

        if not response.content:
            raise ValueError("Anthropic API returned an empty response during summary compression")

        result = response.content[0].text  # type: ignore[union-attr]

        if not _validate_structured_output(result, "Summary compression"):
            logger.error(
                "Summary compression produced invalid output — "
                "returning previous summary unchanged"
            )
            return current_summary

        return result


# ---------------------------------------------------------------------------
# Narrator orchestrator
# ---------------------------------------------------------------------------


class Narrator:
    """Orchestrates the narration pipeline.

    Routing logic (ADR-0002):
    - Default: "high" tier (Sonnet) — fail safe
    - Use "low" tier (Haiku) only when:
      - The action has no mechanical result (rules_result is None) AND
      - The player action is simple (< 20 words, no combat/spell keywords)
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def narrate_turn_stream(
        self,
        snapshot: StateSnapshot,
    ) -> tuple[str, GMSignals]:
        """Collect the full narrative and parse the embedded GMSignals block.

        Applies the same tier-routing logic as narrate_turn.  Buffers all
        chunks from the provider stream (or the non-streaming fallback),
        splits the raw output at the GM_SIGNALS_DELIMITER, and returns:

          (narrative_text, gm_signals)

        where *narrative_text* is everything before the delimiter (stripped)
        and *gm_signals* is the parsed GMSignals dataclass.  On any parse
        failure parse_gm_signals() returns safe_default().

        Logs quality warnings on the narrative portion only.
        """
        turn = snapshot.current_turn
        if turn.rules_result is None and _is_simple_action(turn.player_action):
            tier: Literal["high", "low"] = "low"
        else:
            tier = "high"

        provider_stream = getattr(self._provider, "narrate_stream", None)
        if provider_stream is not None:
            raw = ""
            async for chunk in provider_stream(snapshot, tier):
                raw += chunk
        else:
            # Non-streaming fallback
            raw = await self._provider.narrate(snapshot, tier)

        # Split at the delimiter — everything before is narrative prose
        if GM_SIGNALS_DELIMITER in raw:
            narrative_text, _, _ = raw.partition(GM_SIGNALS_DELIMITER)
            narrative_text = narrative_text.rstrip()
        else:
            narrative_text = raw

        _check_response_quality(narrative_text)
        gm_signals = parse_gm_signals(raw)
        return narrative_text, gm_signals

    async def narrate_turn(self, snapshot: StateSnapshot) -> str:
        """Determine model tier, get narration, and validate the response.

        Returns plain-text narrative. Logs a warning if the response
        contains Markdown, HTML, or mechanical numbers — enforcement is
        probabilistic (ADR-0002, Consequences section).
        """
        turn = snapshot.current_turn

        # Route to "low" only for simple, non-mechanical actions
        if turn.rules_result is None and _is_simple_action(turn.player_action):
            tier: Literal["high", "low"] = "low"
        else:
            tier = "high"

        narrative = await self._provider.narrate(snapshot, tier)
        _check_response_quality(narrative)
        return narrative

    async def update_summary(
        self,
        recent_turns: list[str],
        current_summary: str,
    ) -> str:
        """Compress recent turns into an updated rolling summary.

        Always delegates to the provider's compress_summary (Haiku per ADR-0002).
        """
        return await self._provider.compress_summary(recent_turns, current_summary)

    async def generate_campaign_brief(self, name: str, tone: str) -> dict[str, str]:
        """Generate a campaign brief and opening scene using Claude Haiku.

        Returns a dict with keys:
            campaign_brief, opening_scene, location, environment, time_of_day

        Raises:
            TimeoutError, RuntimeError, ValueError — caller should handle all
            and fall back to static defaults.
        """
        generate_fn = getattr(self._provider, "generate_campaign_brief", None)
        if generate_fn is None:
            raise NotImplementedError("Provider does not support campaign brief generation")
        return await generate_fn(name, tone)
