"""Action classification for the SRD 5.2.1 Rules Engine.

Classifies free-text player actions into structured categories using
keyword matching.  No LLM calls — deterministic, synchronous, fast.

Classification order (first match wins):
  1. CAST_SPELL   — spell keywords or "cast"
  2. RANGED_ATTACK — ranged weapon or "shoot"/"fire"/"throw"
  3. MELEE_ATTACK  — melee weapon or "attack"/"strike"/"slash"/"hit"
  4. ABILITY_CHECK — "check"/"roll"/"try to"/"attempt" + ability keyword
  5. INTERACTION   — "use"/"open"/"take"/"grab"/"pick up"/"examine"
  6. MOVEMENT      — "move"/"run"/"walk"/"dash"/"flee"/"approach"
  7. UNKNOWN       — ambiguous but action-like (no clear narrative intent)
  8. NARRATIVE     — pure description with no mechanical trigger
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActionCategory(StrEnum):
    MELEE_ATTACK = "melee_attack"
    RANGED_ATTACK = "ranged_attack"
    CAST_SPELL = "cast_spell"
    ABILITY_CHECK = "ability_check"
    MOVEMENT = "movement"
    INTERACTION = "interaction"
    NARRATIVE = "narrative"
    UNKNOWN = "unknown"


@dataclass
class ActionAnalysis:
    category: ActionCategory
    target_name: str | None = None
    spell_index: str | None = None
    """Canonical spell index (lower-case, hyphenated) if category == CAST_SPELL."""
    ability: str | None = None
    """Ability name (e.g. ``"STR"``) if category == ABILITY_CHECK."""
    raw_action: str = field(default="", repr=False)
    matched_keywords: list[str] | None = None
    """Keywords from the player's text that triggered the classification."""
    decision_summary: str | None = None
    """Human-readable one-liner describing how the action was classified."""


# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_SPELL_KEYWORDS: frozenset[str] = frozenset(
    [
        "cast",
        "casting",
        "spell",
        "cantrip",
        "fire bolt",
        "firebolt",
        "magic missile",
        "burning hands",
        "cure wounds",
        "hold person",
        "thunderwave",
        "thunder wave",
        "healing word",
        "sacred flame",
        "toll the dead",
        "eldritch blast",
        "guiding bolt",
        "inflict wounds",
        "ray of frost",
        "poison spray",
        "vicious mockery",
        "sleep",
        "charm person",
        "grease",
        "identify",
        "detect magic",
        "shield",
        "mage armor",
        "misty step",
        "invisibility",
        "scorching ray",
        "shatter",
        "darkness",
        "blindness",
        "blindness/deafness",
        "hold monster",
        "fireball",
        "lightning bolt",
        "counterspell",
        "dispel magic",
        "fly",
        "haste",
        "slow",
        "animate dead",
        "bestow curse",
        "hypnotic pattern",
        "speak with dead",
        "wall of fire",
        "banishment",
        "polymorph",
        "dimension door",
        "ice storm",
        "wall of ice",
        "cone of cold",
        "cloudkill",
        "dominate person",
        "hold",
        "bless",
        "bane",
        "command",
        "heroism",
        "sanctuary",
        "faerie fire",
        "entangle",
        "speak with animals",
        "web",
        "moonbeam",
        "pass without trace",
        "call lightning",
        "erupting earth",
        "toll dead",
    ]
)

_RANGED_KEYWORDS: frozenset[str] = frozenset(
    [
        "shoot",
        "fire",
        "loose",
        "launch",
        "throw",
        "hurl",
        "fling",
        "snipe",
        "ranged",
        "arrow",
        "bolt",
        "crossbow",
        "bow",
        "sling",
        "javelin",
        "dart",
    ]
)

_MELEE_KEYWORDS: frozenset[str] = frozenset(
    [
        "attack",
        "strike",
        "slash",
        "hit",
        "swing",
        "stab",
        "thrust",
        "smite",
        "bash",
        "cut",
        "slice",
        "punch",
        "kick",
        "bite",
        "claw",
        "charge",
        "cleave",
        "lunge",
        "parry",
        "riposte",
    ]
)

_ABILITY_KEYWORDS: dict[str, str] = {
    "strength": "STR",
    "str": "STR",
    "dexterity": "DEX",
    "dex": "DEX",
    "constitution": "CON",
    "con": "CON",
    "intelligence": "INT",
    "int": "INT",
    "wisdom": "WIS",
    "wis": "WIS",
    "charisma": "CHA",
    "cha": "CHA",
    "athletics": "STR",
    "acrobatics": "DEX",
    "stealth": "DEX",
    "perception": "WIS",
    "insight": "WIS",
    "persuasion": "CHA",
    "deception": "CHA",
    "intimidation": "CHA",
    "history": "INT",
    "arcana": "INT",
    "nature": "INT",
    "religion": "INT",
    "investigation": "INT",
    "medicine": "WIS",
    "survival": "WIS",
    "animal handling": "WIS",
    "performance": "CHA",
    "sleight of hand": "DEX",
}

_ABILITY_TRIGGER_KEYWORDS: frozenset[str] = frozenset(
    ["check", "roll", "try to", "attempt", "skill"]
)

_INTERACTION_KEYWORDS: frozenset[str] = frozenset(
    [
        "use",
        "open",
        "close",
        "take",
        "grab",
        "pick up",
        "pick up",
        "drop",
        "put",
        "place",
        "equip",
        "drink",
        "read",
        "examine",
        "inspect",
        "search",
        "loot",
        "unlock",
        "lock",
        "pull",
        "push",
        "press",
        "activate",
        "deactivate",
        "talk",
        "speak",
        "ask",
        "tell",
        "give",
        "hand",
        "trade",
        "help",
        "assist",
        "hide",
        "dodge",
    ]
)

_MOVEMENT_KEYWORDS: frozenset[str] = frozenset(
    [
        "move",
        "run",
        "walk",
        "dash",
        "flee",
        "retreat",
        "approach",
        "advance",
        "step",
        "jump",
        "leap",
        "climb",
        "crawl",
        "swim",
        "fly",
        "teleport",
        "go to",
        "head to",
        "sneak",
        "follow",
        "chase",
        "pursue",
        "circle",
        "flank",
    ]
)

# ---------------------------------------------------------------------------
# Spell index mapping (display name → canonical index)
# ---------------------------------------------------------------------------

_SPELL_NAME_TO_INDEX: dict[str, str] = {
    "fire bolt": "fire-bolt",
    "firebolt": "fire-bolt",
    "magic missile": "magic-missile",
    "burning hands": "burning-hands",
    "cure wounds": "cure-wounds",
    "hold person": "hold-person",
    "thunder wave": "thunderwave",
    "thunderwave": "thunderwave",
    "healing word": "healing-word",
    "sacred flame": "sacred-flame",
    "toll the dead": "toll-the-dead",
    "toll dead": "toll-the-dead",
    "eldritch blast": "eldritch-blast",
    "guiding bolt": "guiding-bolt",
    "inflict wounds": "inflict-wounds",
    "ray of frost": "ray-of-frost",
    "poison spray": "poison-spray",
    "vicious mockery": "vicious-mockery",
    "sleep": "sleep",
    "charm person": "charm-person",
    "grease": "grease",
    "identify": "identify",
    "detect magic": "detect-magic",
    "shield": "shield",
    "mage armor": "mage-armor",
    "misty step": "misty-step",
    "invisibility": "invisibility",
    "scorching ray": "scorching-ray",
    "shatter": "shatter",
    "darkness": "darkness",
    "blindness/deafness": "blindness-deafness",
    "blindness": "blindness-deafness",
    "hold monster": "hold-monster",
    "fireball": "fireball",
    "lightning bolt": "lightning-bolt",
    "counterspell": "counterspell",
    "dispel magic": "dispel-magic",
    "fly": "fly",
    "haste": "haste",
    "slow": "slow",
    "animate dead": "animate-dead",
    "bestow curse": "bestow-curse",
    "hypnotic pattern": "hypnotic-pattern",
    "speak with dead": "speak-with-dead",
    "wall of fire": "wall-of-fire",
    "banishment": "banishment",
    "polymorph": "polymorph",
    "dimension door": "dimension-door",
    "ice storm": "ice-storm",
    "wall of ice": "wall-of-ice",
    "cone of cold": "cone-of-cold",
    "cloudkill": "cloudkill",
    "dominate person": "dominate-person",
    "bless": "bless",
    "bane": "bane",
    "command": "command",
    "heroism": "heroism",
    "sanctuary": "sanctuary",
    "faerie fire": "faerie-fire",
    "entangle": "entangle",
    "speak with animals": "speak-with-animals",
    "web": "web",
    "moonbeam": "moonbeam",
    "pass without trace": "pass-without-trace",
    "call lightning": "call-lightning",
    "erupting earth": "erupting-earth",
}


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return text.lower().split()


def _contains_any(text_lower: str, keywords: frozenset[str]) -> bool:
    return any(kw in text_lower for kw in keywords)


def _matched_keywords(text_lower: str, keywords: frozenset[str]) -> list[str]:
    """Return the subset of *keywords* that appear in *text_lower*."""
    return sorted(kw for kw in keywords if kw in text_lower)


def _extract_spell_index(text_lower: str) -> str | None:
    """Return the canonical spell index for the longest spell name found."""
    best: tuple[int, str] | None = None
    for name, index in _SPELL_NAME_TO_INDEX.items():
        if name in text_lower:
            if best is None or len(name) > best[0]:
                best = (len(name), index)
    return best[1] if best else None


def _extract_target(text_lower: str) -> str | None:
    """Return a rough target name from prepositions ("at X", "on X", "the X")."""
    import re

    # "at the goblin", "on the ogre", "against the guard"
    m = re.search(r"\b(?:at|on|against|towards?|the)\s+(?:the\s+)?([a-z][a-z ]{1,30})", text_lower)
    if m:
        candidate = m.group(1).strip()
        # Reject single stop-words
        if candidate not in {"the", "a", "an", "it", "him", "her", "them"}:
            return candidate
    return None


def _extract_ability(text_lower: str) -> str | None:
    """Return ability abbreviation if any ability/skill keyword is found."""
    # Longest-match first (e.g. "animal handling" before "handle")
    for skill, ability in sorted(_ABILITY_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if skill in text_lower:
            return ability
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_action(
    player_action: str,
    character_state: dict | None = None,  # noqa: ARG001 — reserved for future use
    scene_context: dict | None = None,  # noqa: ARG001 — reserved for future use
) -> ActionAnalysis:
    """Classify a free-text player action into an :class:`ActionAnalysis`.

    Args:
        player_action: The raw player action string.
        character_state: Optional character dict (reserved; unused currently).
        scene_context: Optional scene dict (reserved; unused currently).

    Returns:
        :class:`ActionAnalysis` with a :class:`ActionCategory` and optional
        extracted fields.
    """
    text = player_action.strip()
    low = text.lower()

    # 1. Spell detection (highest specificity)
    if _contains_any(low, _SPELL_KEYWORDS):
        spell_index = _extract_spell_index(low)
        kws = _matched_keywords(low, _SPELL_KEYWORDS)
        summary = f"Classified as {ActionCategory.CAST_SPELL} via keywords: {', '.join(kws)}"
        if spell_index:
            summary += f"; spell={spell_index}"
        return ActionAnalysis(
            category=ActionCategory.CAST_SPELL,
            target_name=_extract_target(low),
            spell_index=spell_index,
            raw_action=text,
            matched_keywords=kws,
            decision_summary=summary,
        )

    # 2. Ranged attack
    if _contains_any(low, _RANGED_KEYWORDS):
        kws = _matched_keywords(low, _RANGED_KEYWORDS)
        _cat = ActionCategory.RANGED_ATTACK
        return ActionAnalysis(
            category=_cat,
            target_name=_extract_target(low),
            raw_action=text,
            matched_keywords=kws,
            decision_summary=f"Classified as {_cat} via keywords: {', '.join(kws)}",
        )

    # 3. Melee attack
    if _contains_any(low, _MELEE_KEYWORDS):
        kws = _matched_keywords(low, _MELEE_KEYWORDS)
        _cat = ActionCategory.MELEE_ATTACK
        return ActionAnalysis(
            category=_cat,
            target_name=_extract_target(low),
            raw_action=text,
            matched_keywords=kws,
            decision_summary=f"Classified as {_cat} via keywords: {', '.join(kws)}",
        )

    # 4. Ability check
    if _contains_any(low, _ABILITY_TRIGGER_KEYWORDS):
        ability = _extract_ability(low)
        if ability:
            kws = _matched_keywords(low, _ABILITY_TRIGGER_KEYWORDS)
            _cat = ActionCategory.ABILITY_CHECK
            _kw_str = ", ".join(kws)
            return ActionAnalysis(
                category=_cat,
                ability=ability,
                target_name=_extract_target(low),
                raw_action=text,
                matched_keywords=kws,
                decision_summary=(
                    f"Classified as {_cat} via keywords: {_kw_str}; ability={ability}"
                ),
            )

    # 5. Interaction
    if _contains_any(low, _INTERACTION_KEYWORDS):
        kws = _matched_keywords(low, _INTERACTION_KEYWORDS)
        _cat = ActionCategory.INTERACTION
        return ActionAnalysis(
            category=_cat,
            target_name=_extract_target(low),
            raw_action=text,
            matched_keywords=kws,
            decision_summary=f"Classified as {_cat} via keywords: {', '.join(kws)}",
        )

    # 6. Movement
    if _contains_any(low, _MOVEMENT_KEYWORDS):
        kws = _matched_keywords(low, _MOVEMENT_KEYWORDS)
        _cat = ActionCategory.MOVEMENT
        return ActionAnalysis(
            category=_cat,
            raw_action=text,
            matched_keywords=kws,
            decision_summary=f"Classified as {_cat} via keywords: {', '.join(kws)}",
        )

    # 7. Short text with action-like verbs → UNKNOWN rather than NARRATIVE
    words = _tokens(text)
    if len(words) <= 6:
        return ActionAnalysis(
            category=ActionCategory.UNKNOWN,
            raw_action=text,
            matched_keywords=[],
            decision_summary="Classified as unknown — short text with no recognised keywords",
        )

    # 8. Default: treat as pure narrative description
    return ActionAnalysis(
        category=ActionCategory.NARRATIVE,
        raw_action=text,
        matched_keywords=[],
        decision_summary="Classified as narrative — long text with no mechanical trigger keywords",
    )
