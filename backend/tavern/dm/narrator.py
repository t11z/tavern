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

import logging
import re
from typing import Literal, Protocol

import anthropic

from tavern.dm.context_builder import StateSnapshot, serialize_snapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (ADR-0002 model routing)
# ---------------------------------------------------------------------------

MODEL_MAP: dict[str, str] = {
    "high": "claude-sonnet-4-20250514",
    "low": "claude-haiku-4-5-20251001",
}

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

    async def compress_summary(
        self,
        turns: list[str],
        current_summary: str,
        max_tokens: int = SUMMARY_MAX_TOKENS,
    ) -> str:
        """Compress recent turns into a rolling summary update using Haiku.

        Always uses the "low" tier — summary compression is mechanical
        text transformation, not creative narration (ADR-0002).

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded.
            ValueError: If the response contains no content.
        """
        turns_text = "\n".join(turns)
        prompt = (
            "You are a note-taker for a tabletop RPG session.\n"
            "Compress the following recent turns into a brief summary that "
            "captures key events, decisions, and outcomes. Preserve character "
            "names, locations, and mechanical results. Drop dialogue and "
            f"atmospheric detail. Keep it under {max_tokens} tokens.\n\n"
            f"Current summary: {current_summary}\n\n"
            f"New turns:\n{turns_text}"
        )

        try:
            response = await self._client.messages.create(
                model=MODEL_MAP["low"],
                max_tokens=max_tokens,
                temperature=SUMMARY_TEMPERATURE,
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

        return response.content[0].text  # type: ignore[union-attr]


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
