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
import time
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

# ---------------------------------------------------------------------------
# LLM pricing constants (approximate, per million tokens)
# Used only for estimated_cost_usd in observability metadata.
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    # Sonnet: input $3/MTok, output $15/MTok, cache_read $0.30/MTok, cache_creation $3.75/MTok
    "sonnet": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    # Haiku: input $0.25/MTok, output $1.25/MTok, cache_read $0.03/MTok, cache_creation $0.30/MTok
    "haiku": {
        "input": 0.25,
        "output": 1.25,
        "cache_read": 0.03,
        "cache_creation": 0.30,
    },
}


def _estimate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    """Return estimated cost in USD for one LLM call.

    Uses hardcoded pricing constants.  Falls back to Sonnet pricing when the
    model cannot be identified.
    """
    model_lower = model_id.lower()
    if "haiku" in model_lower:
        prices = _PRICING["haiku"]
    else:
        prices = _PRICING["sonnet"]

    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read_tokens * prices["cache_read"]
        + cache_creation_tokens * prices["cache_creation"]
    ) / 1_000_000
    return cost


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
    '"potential_surprised_characters": [], "reason": ""}, "npc_updates": [], '
    '"suggested_actions": ["Slip through the gap before the guards arrive", '
    '"Demand the harbormaster explain herself"]}\n\n'
    'Rules for scene_transition.type: must be exactly "none", "combat_start", or '
    '"combat_end". Use "combat_start" only when NPCs initiate an unprovoked attack. '
    'Use "combat_end" only when all hostile NPCs are defeated or fled. '
    '"npc_updates" must be a list (may be empty). Each entry needs "event" '
    '(spawn|status_change|disposition_change|location_change) and "npc_name". '
    '"suggested_actions" must be a JSON array of 0–3 first-person action phrases '
    "(5–12 words each). Default to 2 suggestions. See earlier instructions for "
    "full rules. Always include all three top-level keys."
)

# NPC lifecycle behavioral instructions appended to the system prompt (ADR-0013).
# Plain text only — no Markdown, no HTML (ADR-0002 §5).
_NPC_CONSISTENCY_INSTRUCTION = (
    "\n\nNPC CONSISTENCY RULES:\n"
    "- The NPCs: section lists all NPCs currently in the scene. Each entry shows the NPC's\n"
    "  canonical name, species, appearance, role, disposition, and status.\n"
    "- These attributes are AUTHORITATIVE. When describing or referencing an NPC listed in the\n"
    "  NPCs: section, you MUST use their canonical name, species, and appearance exactly as\n"
    "  given.\n"
    "  Do not invent alternative descriptions, change gender, alter physical features, or\n"
    "  rename NPCs that already exist in the NPCs: section.\n"
    "- When introducing a NEW character not present in the NPCs: section, emit a spawn event\n"
    "  in your GMSignals npc_updates. Provide: npc_name (unique within the campaign),\n"
    "  species, appearance (1-3 sentences of physical description), role, motivation,\n"
    "  disposition. Optionally provide stat_block_ref for SRD creatures (e.g. goblin,\n"
    "  bandit, veteran).\n"
    "- BEFORE emitting a spawn event, check the NPCs: section. If an NPC with that name already\n"
    "  exists, reference them by name — do not spawn a duplicate.\n"
    "- For NPCs you spawn: the name, species, and appearance you provide become permanent and\n"
    "  immutable. Choose carefully — you cannot change them later.\n"
    "- You may update an existing NPC's disposition, status, or location via npc_updates\n"
    "  events (disposition_change, status_change, location_change). Use the NPC's canonical\n"
    "  name in the npc_name field.\n"
    "- Crowd characters (unnamed bystanders, generic guards) do not require spawn events.\n"
    "  Only emit spawn events for characters the players interact with meaningfully or who\n"
    "  have narrative significance."
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
        """Append the GMSignals and NPC consistency instructions to the system prompt."""
        return system_text + _GM_SIGNALS_INSTRUCTION + _NPC_CONSISTENCY_INSTRUCTION

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

    async def narrate_stream_with_meta(
        self,
        snapshot: StateSnapshot,
        model_tier: Literal["high", "low"] = "high",
    ) -> tuple[str, dict]:
        """Stream narrative from Claude and return full text with usage metadata.

        Unlike narrate_stream (an async generator), this method buffers the
        complete response and extracts token usage from the final message.
        This allows the observability layer to record accurate token counts
        and cost estimates.

        Returns:
            A tuple of (full_raw_text, usage_dict) where usage_dict contains:
                input_tokens (int), output_tokens (int),
                cache_read_tokens (int), cache_creation_tokens (int),
                stream_first_token_ms (int | None).

        Raises:
            TimeoutError: If the request times out.
            RuntimeError: If the API rate limit is exceeded.
        """
        serialized = serialize_snapshot(snapshot)
        system_text: str = serialized["system"]  # type: ignore[assignment]
        system_text = self._build_system_with_signals(system_text)
        messages_list = serialized["messages"]  # type: ignore[assignment]
        user_content: str = messages_list[0]["content"]  # type: ignore[index]

        call_start = time.monotonic()
        first_token_ms: int | None = None
        raw = ""

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
                    if first_token_ms is None and text:
                        first_token_ms = int((time.monotonic() - call_start) * 1000)
                    raw += text

                final_message = await stream.get_final_message()
                usage = final_message.usage
                input_tokens = getattr(usage, "input_tokens", 0) or 0
                output_tokens = getattr(usage, "output_tokens", 0) or 0
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0

        except anthropic.APITimeoutError as exc:
            raise TimeoutError(f"Anthropic API request timed out: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError(
                f"Anthropic API rate limit exceeded — retry after a moment: {exc}"
            ) from exc

        return raw, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_creation,
            "stream_first_token_ms": first_token_ms,
        }

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
    ) -> tuple[str, GMSignals, dict]:
        """Collect the full narrative and parse the embedded GMSignals block.

        Applies the same tier-routing logic as narrate_turn.  Buffers all
        chunks from the provider stream (or the non-streaming fallback),
        splits the raw output at the GM_SIGNALS_DELIMITER, and returns:

          (narrative_text, gm_signals, llm_meta)

        where *narrative_text* is everything before the delimiter (stripped),
        *gm_signals* is the parsed GMSignals dataclass (safe_default() on any
        parse failure), and *llm_meta* is a diagnostic dict with LLM call
        metadata for the observability layer.

        Logs quality warnings on the narrative portion only.
        """
        turn = snapshot.current_turn
        if turn.rules_result is None and _is_simple_action(turn.player_action):
            tier: Literal["high", "low"] = "low"
        else:
            tier = "high"

        model_id = MODEL_MAP[tier]
        call_start = time.monotonic()
        first_token_ms: int | None = None
        error_msg: str | None = None
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0

        # Prefer narrate_stream_with_meta when available (AnthropicProvider) so
        # that token usage is captured from the final message.  Fall back to the
        # plain streaming generator, then to the non-streaming narrate() method.
        stream_with_meta_fn = getattr(self._provider, "narrate_stream_with_meta", None)
        provider_stream = getattr(self._provider, "narrate_stream", None)

        try:
            if stream_with_meta_fn is not None:
                raw, usage = await stream_with_meta_fn(snapshot, tier)
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_read_tokens = usage.get("cache_read_tokens", 0)
                cache_creation_tokens = usage.get("cache_creation_tokens", 0)
                first_token_ms = usage.get("stream_first_token_ms")
            elif provider_stream is not None:
                raw = ""
                async for chunk in provider_stream(snapshot, tier):
                    if first_token_ms is None and chunk:
                        first_token_ms = int((time.monotonic() - call_start) * 1000)
                    raw += chunk
            else:
                # Non-streaming fallback (used in tests / non-Anthropic providers)
                raw = await self._provider.narrate(snapshot, tier)
                if raw:
                    first_token_ms = int((time.monotonic() - call_start) * 1000)
        except Exception as exc:
            error_msg = str(exc)
            raise

        latency_ms = int((time.monotonic() - call_start) * 1000)

        # Split at the delimiter — everything before is narrative prose
        if GM_SIGNALS_DELIMITER in raw:
            narrative_text, _, _ = raw.partition(GM_SIGNALS_DELIMITER)
            narrative_text = narrative_text.rstrip()
        else:
            narrative_text = raw

        _check_response_quality(narrative_text)
        gm_signals, _gm_diag = parse_gm_signals(raw)

        llm_meta: dict = {
            "call_type": "narration",
            "model_id": model_id,
            "model_tier": tier,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "latency_ms": latency_ms,
            "stream_first_token_ms": first_token_ms,
            "estimated_cost_usd": _estimate_cost(
                model_id,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_creation_tokens,
            ),
            "success": error_msg is None,
            "error": error_msg,
        }

        return narrative_text, gm_signals, llm_meta

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
