"""CombatClassifier — binary LLM classifier for combat initiation detection.

Determines whether a player action begins combat, as specified in ADR-0011.

Design constraints (ADR-0011):
- No dependency on core/. Reads only from the StateSnapshot assembled by
  the Context Builder.
- Only invoked in Exploration mode. Raises RuntimeError if called in combat
  mode (snapshot.session_mode == 'combat').
- Uses Claude Haiku (low tier) — binary classification with structured JSON
  output does not require Sonnet-class reasoning.
- On any parse failure or API error: return safe fallback
  CombatClassification(combat_starts=False, ..., confidence='low') and log
  the error. Never raise from a classifier failure.
- The reason field is for logging only — never player-facing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Literal

import anthropic

from tavern.dm.context_builder import StateSnapshot

# ---------------------------------------------------------------------------
# Pricing helper (mirrors narrator._estimate_cost — kept local to avoid coupling)
# ---------------------------------------------------------------------------

_CLASSIFIER_PRICING: dict[str, float] = {
    # Haiku pricing: input $0.25/MTok, output $1.25/MTok,
    # cache_read $0.03/MTok, cache_creation $0.30/MTok
    "input": 0.25,
    "output": 1.25,
    "cache_read": 0.03,
    "cache_creation": 0.30,
}


def _estimate_classification_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    """Return estimated cost in USD for one classifier call.

    The classifier always uses Haiku (low tier), so Haiku pricing is used
    regardless of model_id.  model_id is accepted for forward compatibility.
    """
    prices = _CLASSIFIER_PRICING
    cost = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read_tokens * prices["cache_read"]
        + cache_creation_tokens * prices["cache_creation"]
    ) / 1_000_000
    return cost


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model constant (ADR-0011: Haiku for the classifier)
# ---------------------------------------------------------------------------

_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
_CLASSIFIER_MAX_TOKENS = 150

# ---------------------------------------------------------------------------
# Classifier system prompt (≤200 words per ADR-0011 §4)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a combat-initiation classifier for a D&D 5e game engine. \
Your sole task: determine whether the player action begins combat.

Combat STARTS when the action is:
- A direct attack on a creature (melee strike, ranged shot, spell targeting a creature harmfully)
- Casting a harmful spell at a creature, making peaceful resolution immediately impossible
- Any action that unambiguously commits the player to violence against a specific target

Combat does NOT start when the action is:
- Drawing, sheathing, or displaying a weapon without attacking
- Threatening dialogue or intimidation without a physical attack
- Observing, approaching, or moving near a hostile creature
- Ambiguous posturing that could still resolve peacefully

Return ONLY a JSON object with exactly these fields — no preamble, no explanation:
{
  "combat_starts": true or false,
  "combatants": ["NPC name", ...],
  "confidence": "high" or "low",
  "reason": "one sentence"
}

"combatants" lists only NPC names present in the scene who would participate. \
"confidence" is "low" only when the action is genuinely ambiguous. \
"reason" is one sentence for logging — never shown to players.\
"""

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CombatClassification:
    """Result of the CombatClassifier.classify() call.

    combat_starts: True if the action initiates combat.
    combatants:    NPC names present in the scene who are drawn into combat.
    confidence:    'high' for unambiguous actions, 'low' for edge cases.
    reason:        One sentence for logging only — never player-facing.
    """

    combat_starts: bool
    combatants: list[str]
    confidence: Literal["high", "low"]
    reason: str


_SAFE_FALLBACK = CombatClassification(
    combat_starts=False,
    combatants=[],
    confidence="low",
    reason="classifier parse error",
)

# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class CombatClassifier:
    """Binary LLM classifier: does this player action initiate combat?

    Uses Claude Haiku for low-latency, low-cost classification.
    Must only be called when the session is in Exploration mode.
    """

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def classify(
        self,
        action_text: str,
        snapshot: StateSnapshot,
    ) -> tuple[CombatClassification, dict]:
        """Classify whether the player action begins combat.

        Args:
            action_text: Verbatim player action string.
            snapshot:    Current game state snapshot assembled by the Context
                         Builder. Must be in Exploration mode.

        Returns:
            A tuple of (CombatClassification, llm_meta_dict).

            CombatClassification carries the classifier's verdict.
            Returns a safe fallback (combat_starts=False, confidence='low')
            on API error or malformed response — never raises.

            llm_meta_dict keys match the narration metadata structure with
            call_type="classification".  On error, success=False and error
            contains the exception message.

        Raises:
            RuntimeError: If snapshot.session_mode == 'combat'. The classifier
                          must never be invoked during an active combat session.
        """
        if snapshot.session_mode == "combat":
            raise RuntimeError("CombatClassifier called in combat mode")

        user_message = _build_user_message(action_text, snapshot)
        call_start = time.monotonic()

        def _meta(
            *,
            success: bool,
            error: str | None,
            input_tokens: int = 0,
            output_tokens: int = 0,
            cache_read_tokens: int = 0,
            cache_creation_tokens: int = 0,
            latency_ms: int = 0,
        ) -> dict:
            cost = _estimate_classification_cost(
                _CLASSIFIER_MODEL,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_creation_tokens,
            )
            return {
                "call_type": "classification",
                "model_id": _CLASSIFIER_MODEL,
                "model_tier": "low",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "latency_ms": latency_ms,
                "stream_first_token_ms": None,
                "estimated_cost_usd": cost,
                "success": success,
                "error": error,
            }

        try:
            response = await self._client.messages.create(
                model=_CLASSIFIER_MODEL,
                max_tokens=_CLASSIFIER_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - call_start) * 1000)
            logger.error(
                "CombatClassifier API call failed (returning safe fallback): %s",
                exc,
            )
            return _SAFE_FALLBACK, _meta(
                success=False,
                error=str(exc),
                latency_ms=latency_ms,
            )

        latency_ms = int((time.monotonic() - call_start) * 1000)
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0

        if not response.content:
            logger.error("CombatClassifier received empty response (returning safe fallback)")
            return _SAFE_FALLBACK, _meta(
                success=False,
                error="empty response",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                latency_ms=latency_ms,
            )

        raw = response.content[0].text  # type: ignore[union-attr]
        result = _parse_classification(raw)
        logger.debug(
            "CombatClassification: combat_starts=%s confidence=%s reason=%r",
            result.combat_starts,
            result.confidence,
            result.reason,
        )
        return result, _meta(
            success=True,
            error=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_user_message(action_text: str, snapshot: StateSnapshot) -> str:
    """Construct the user message: action + minimal scene context.

    Input budget target: ~200 tokens (ADR-0011 §4).
    Includes only what the classifier needs: NPC names, location, threats.
    No rolling summary, no character stats.
    """
    scene = snapshot.scene
    parts: list[str] = [f"Player action: {action_text}"]
    parts.append(f"Location: {scene.location}")
    if scene.npcs:
        parts.append("NPCs present: " + ", ".join(scene.npcs))
    if scene.threats:
        parts.append("Active threats: " + ", ".join(scene.threats))
    return "\n".join(parts)


def _parse_classification(raw: str) -> CombatClassification:
    """Parse and validate the classifier JSON response.

    Checks for conversational bleed-through before attempting JSON parse.
    On any parse or validation error: log and return safe fallback.
    """
    # Audit finding: system prompt uses JSON-only constraint and safe fallback
    # is already in place — adding bleed-through check for an earlier, more
    # descriptive log before the JSONDecodeError path.
    _BLEED_SIGNALS = ("?", "I'm ready", "I'd be happy", "Here's", "Let me know", "I can help")
    raw_lower = raw.lower()
    if any(sig.lower() in raw_lower for sig in _BLEED_SIGNALS):
        logger.warning(
            "CombatClassifier response appears conversational (returning safe fallback): %r",
            raw[:200],
        )
        return _SAFE_FALLBACK

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.error(
            "CombatClassifier returned non-JSON response (returning safe fallback): %r",
            raw[:500],
        )
        return _SAFE_FALLBACK

    # Validate required fields and types
    try:
        combat_starts = data["combat_starts"]
        combatants = data["combatants"]
        confidence = data["confidence"]
        reason = data["reason"]

        if not isinstance(combat_starts, bool):
            raise TypeError(f"combat_starts must be bool, got {type(combat_starts)}")
        if not isinstance(combatants, list):
            raise TypeError(f"combatants must be list, got {type(combatants)}")
        if confidence not in ("high", "low"):
            raise ValueError(f"confidence must be 'high' or 'low', got {confidence!r}")
        if not isinstance(reason, str):
            raise TypeError(f"reason must be str, got {type(reason)}")

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "CombatClassifier response failed schema validation "
            "(returning safe fallback): %s — raw: %r",
            exc,
            raw[:500],
        )
        return _SAFE_FALLBACK

    return CombatClassification(
        combat_starts=combat_starts,
        combatants=list(combatants),
        confidence=confidence,  # type: ignore[arg-type]
        reason=reason,
    )
