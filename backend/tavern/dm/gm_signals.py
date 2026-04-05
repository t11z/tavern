"""GMSignals — structured signals from the Narrator for scene and NPC management.

The Narrator appends a GMSignals block after every narrative response.
The block is delimited by GM_SIGNALS_DELIMITER on its own line, followed
by a JSON object.  The turns pipeline strips the delimiter and JSON before
broadcasting narrative text to clients.

ADR-0012: NPC-initiated combat
ADR-0013: NPC lifecycle
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Delimiter
# ---------------------------------------------------------------------------

GM_SIGNALS_DELIMITER = "---GM_SIGNALS---"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SceneTransition:
    """Requested scene mode transition from the Narrator."""

    type: Literal["combat_start", "combat_end", "none"]
    combatants: list[str] = field(default_factory=list)
    """NPC names that should participate in combat (for combat_start)."""

    potential_surprised_characters: list[str] = field(default_factory=list)
    """character_ids of PCs that may be surprised (for NPC-initiated combat)."""

    reason: str = ""
    """One sentence for logging — never player-facing."""


@dataclass
class NPCUpdate:
    """An NPC state change signalled by the Narrator."""

    event: Literal["spawn", "status_change", "disposition_change", "location_change"]
    npc_name: str
    npc_id: str | None = None
    reason: str = ""

    # --- Spawn-only fields ---
    species: str | None = None
    appearance: str | None = None
    role: str | None = None
    motivation: str | None = None
    disposition: Literal["friendly", "neutral", "hostile", "unknown"] | None = None
    hp_max: int | None = None
    ac: int | None = None
    stat_block_ref: str | None = None

    # --- Non-spawn fields ---
    new_status: Literal["alive", "dead", "fled", "unknown"] | None = None
    new_disposition: Literal["friendly", "neutral", "hostile", "unknown"] | None = None
    new_location: str | None = None


@dataclass
class GMSignals:
    """Complete GM signal envelope appended to every Narrator response."""

    scene_transition: SceneTransition = field(default_factory=lambda: SceneTransition(type="none"))
    npc_updates: list[NPCUpdate] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    """0–3 narrative action suggestions for the active player (ADR-0015)."""


# ---------------------------------------------------------------------------
# Safe default
# ---------------------------------------------------------------------------


def safe_default() -> GMSignals:
    """Return a GMSignals with no-op values (safe fallback on any parse failure)."""
    return GMSignals()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_gm_signals(raw: str) -> GMSignals:
    """Parse the GMSignals block from the raw Narrator output.

    Expected format::

        <narrative prose>
        ---GM_SIGNALS---
        {"scene_transition": {...}, "npc_updates": [...]}

    On ANY failure (missing delimiter, JSON error, schema error): logs the
    error with the raw content and returns safe_default().  Never raises.

    Args:
        raw: The complete raw text returned by the Narrator, including the
            delimiter line and the JSON block.

    Returns:
        Parsed GMSignals, or safe_default() on any error.
    """
    if GM_SIGNALS_DELIMITER not in raw:
        logger.error(
            "GMSignals delimiter not found in Narrator output — using safe default. "
            "Raw (first 500 chars): %r",
            raw[:500],
        )
        return safe_default()

    # Split on the first occurrence of the delimiter
    _narrative_part, _, tail = raw.partition(GM_SIGNALS_DELIMITER)
    json_text = tail.strip()

    if not json_text:
        logger.error(
            "GMSignals delimiter found but no JSON followed — using safe default. "
            "Raw (first 500 chars): %r",
            raw[:500],
        )
        return safe_default()

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        logger.error(
            "GMSignals JSON parse error (%s) — using safe default. Raw tail (first 500 chars): %r",
            exc,
            json_text[:500],
        )
        return safe_default()

    # --- Validate top-level structure ---
    if not isinstance(data, dict):
        logger.error("GMSignals JSON is not an object — using safe default. data=%r", data)
        return safe_default()

    # --- Parse scene_transition ---
    st_raw = data.get("scene_transition", {})
    if not isinstance(st_raw, dict):
        logger.error(
            "GMSignals scene_transition is not an object — using safe default. "
            "scene_transition=%r",
            st_raw,
        )
        return safe_default()

    st_type = st_raw.get("type", "none")
    if st_type not in ("combat_start", "combat_end", "none"):
        logger.error(
            "GMSignals scene_transition.type invalid value %r — using safe default.",
            st_type,
        )
        return safe_default()

    scene_transition = SceneTransition(
        type=st_type,  # type: ignore[arg-type]
        combatants=list(st_raw.get("combatants", [])),
        potential_surprised_characters=list(st_raw.get("potential_surprised_characters", [])),
        reason=str(st_raw.get("reason", "")),
    )

    # --- Parse npc_updates ---
    npc_updates_raw = data.get("npc_updates", [])
    if not isinstance(npc_updates_raw, list):
        logger.error(
            "GMSignals npc_updates is not a list — using safe default. npc_updates=%r",
            npc_updates_raw,
        )
        return safe_default()

    npc_updates: list[NPCUpdate] = []
    for idx, u in enumerate(npc_updates_raw):
        if not isinstance(u, dict):
            logger.error("GMSignals npc_updates[%d] is not an object — skipping. u=%r", idx, u)
            continue

        event = u.get("event")
        if event not in ("spawn", "status_change", "disposition_change", "location_change"):
            logger.error(
                "GMSignals npc_updates[%d].event invalid value %r — skipping.",
                idx,
                event,
            )
            continue

        npc_name = u.get("npc_name")
        if not npc_name or not isinstance(npc_name, str):
            logger.error(
                "GMSignals npc_updates[%d].npc_name missing or invalid — skipping.",
                idx,
            )
            continue

        update = NPCUpdate(
            event=event,  # type: ignore[arg-type]
            npc_name=npc_name,
            npc_id=u.get("npc_id"),
            reason=str(u.get("reason", "")),
            # Spawn fields
            species=u.get("species"),
            appearance=u.get("appearance"),
            role=u.get("role"),
            motivation=u.get("motivation"),
            disposition=u.get("disposition"),
            hp_max=u.get("hp_max"),
            ac=u.get("ac"),
            stat_block_ref=u.get("stat_block_ref"),
            # Non-spawn fields
            new_status=u.get("new_status"),
            new_disposition=u.get("new_disposition"),
            new_location=u.get("new_location"),
        )
        npc_updates.append(update)

    # --- Parse suggested_actions (ADR-0015) ---
    _MAX_SUGGESTIONS = 3
    _MAX_SUGGESTION_LEN = 80

    suggested_actions_raw = data.get("suggested_actions", [])
    if not isinstance(suggested_actions_raw, list):
        logger.warning(
            "GMSignals suggested_actions is not a list — defaulting to empty. "
            "suggested_actions=%r",
            suggested_actions_raw,
        )
        suggested_actions_raw = []

    # Truncate to max 3 entries; truncate each entry to 80 chars
    suggested_actions: list[str] = []
    for item in suggested_actions_raw[:_MAX_SUGGESTIONS]:
        if not isinstance(item, str) or not item.strip():
            logger.warning(
                "GMSignals suggested_actions item is not a non-empty string — skipping. item=%r",
                item,
            )
            continue
        suggested_actions.append(item[:_MAX_SUGGESTION_LEN])

    return GMSignals(
        scene_transition=scene_transition,
        npc_updates=npc_updates,
        suggested_actions=suggested_actions,
    )
