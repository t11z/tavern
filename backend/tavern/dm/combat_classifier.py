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
from dataclasses import dataclass
from typing import Literal

import anthropic

from tavern.dm.context_builder import StateSnapshot

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
    ) -> CombatClassification:
        """Classify whether the player action begins combat.

        Args:
            action_text: Verbatim player action string.
            snapshot:    Current game state snapshot assembled by the Context
                         Builder. Must be in Exploration mode.

        Returns:
            CombatClassification with the classifier's verdict.
            Returns a safe fallback (combat_starts=False, confidence='low')
            on API error or malformed response — never raises.

        Raises:
            RuntimeError: If snapshot.session_mode == 'combat'. The classifier
                          must never be invoked during an active combat session.
        """
        if snapshot.session_mode == "combat":
            raise RuntimeError("CombatClassifier called in combat mode")

        user_message = _build_user_message(action_text, snapshot)

        try:
            response = await self._client.messages.create(
                model=_CLASSIFIER_MODEL,
                max_tokens=_CLASSIFIER_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
        except Exception as exc:
            logger.error(
                "CombatClassifier API call failed (returning safe fallback): %s",
                exc,
            )
            return _SAFE_FALLBACK

        if not response.content:
            logger.error("CombatClassifier received empty response (returning safe fallback)")
            return _SAFE_FALLBACK

        raw = response.content[0].text  # type: ignore[union-attr]
        return _parse_classification(raw)


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

    On any parse or validation error: log and return safe fallback.
    """
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
