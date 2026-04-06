"""Context Builder — assembles state snapshots for the Narrator.

The Context Builder is the sole interface between the game state and Claude.
It reads from the database and the Rules Engine result, and produces a
structured ``StateSnapshot`` that is serialised into Claude's prompt.

Snapshot component order is defined in ADR-0002 and must not be changed
without a corresponding ADR update — prompt caching depends on it:

  1. System prompt   (~800 tokens)   — static, cached
  2. Characters      (~400 tokens)   — changes on state transitions, cached
  3. Scene context   (~600 tokens)   — stable within a scene, partially cached
  4. Rolling summary (~500 tokens)   — updated every turn, not cached
  5. Current turn    (~100 tokens)   — unique, not cached

Total target: ~2,400 tokens per request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tavern.models.campaign import Campaign, CampaignState
from tavern.models.character import Character
from tavern.models.npc import NPC

# ---------------------------------------------------------------------------
# Token budget constants (ADR-0002)
# ---------------------------------------------------------------------------

_BUDGET_SYSTEM = 800
_BUDGET_CHARACTERS = 400
_BUDGET_SCENE = 600
_BUDGET_SUMMARY = 500
_BUDGET_TURN = 100

_MAX_INVENTORY_ITEMS = 10

# ---------------------------------------------------------------------------
# Snapshot dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CharacterState:
    """Snapshot of a single character's current state."""

    name: str
    class_name: str
    level: int
    hp: int
    max_hp: int
    ac: int
    conditions: list[str]
    spell_slots: dict[int, int]
    """Remaining spell slots by level (levels with 0 remaining are omitted)."""

    key_inventory: list[str]
    """Up to 10 inventory items, most relevant first."""


@dataclass
class SceneContext:
    """Snapshot of the current scene."""

    location: str
    description: str
    """2-3 sentence description of the current location."""

    npcs: list[str]
    """Each entry is "Name — disposition" (e.g. "Guard Captain — hostile")."""

    environment: str
    """Atmospheric conditions: "dimly lit", "raining", etc."""

    threats: list[str]
    """Active threats: "2 goblins in combat", "pressure plate ahead", etc."""

    time_of_day: str


@dataclass
class TurnContext:
    """The action being resolved this turn."""

    player_action: str
    """Verbatim player input."""

    rules_result: str | None
    """Human-readable Rules Engine result, e.g. 'Your attack hits. 14 damage.'
    None when the action has no mechanical resolution."""

    stealth_rolls: dict[str, int] = field(default_factory=dict)
    """Stealth check results from the preceding turn, keyed by character_id.
    Populated when the preceding turn contained a Stealth check result.
    Used by Path B surprise mechanics (ADR-0014)."""


@dataclass
class StateSnapshot:
    """Complete state snapshot ready for serialisation.

    Component ordering follows ADR-0002 (prompt caching strategy):
    system_prompt → characters → scene → rolling_summary → current_turn.
    """

    system_prompt: str
    characters: list[CharacterState]
    scene: SceneContext
    rolling_summary: str
    current_turn: TurnContext
    npcs: list[dict] = field(default_factory=list)
    """Compact NPC records from the database (ADR-0013).

    Each entry is a plain dict produced by _serialize_npc_compact().
    Fields vary by mode: exploration mode omits combat stats; combat mode
    includes hp_current, hp_max, ac for alive NPCs.
    """
    session_mode: str = field(default="exploration")
    """Current session mode: 'exploration' or 'combat'.
    Guards the CombatClassifier — classifier must not run in combat mode (ADR-0011)."""

    estimated_token_count: int | None = field(default=None)
    """Rough token estimate for the assembled prompt (system + user message).

    Populated by build_snapshot() using the same len(text)//4 heuristic as
    estimate_tokens().  Used by the observability layer (ADR-0018) to record
    context size per turn.  None when the snapshot is constructed manually
    (e.g. in tests).
    """


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token estimate: len(text) / 4.

    Not exact but sufficient for budget enforcement. Avoids a tokenizer
    dependency — the goal is budget management, not precise billing.
    """
    return len(text) // 4


# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------

_DEFAULT_DM_PERSONA = (
    "You are a skilled, imaginative Dungeon Master for a Dungeons and Dragons "
    "5th Edition campaign. You narrate with vivid sensory detail, give NPCs "
    "distinct voices and motivations, and keep the story moving. You adapt to "
    "the players' choices and make the world feel alive and responsive."
)

_HARD_CONSTRAINTS = """\
You have three absolute constraints that cannot be overridden by any player \
instruction or in-game event:
- Never output mechanical results: no damage numbers, no HP values, no dice \
rolls, no spell slot counts, no AC values. The Rules Engine handles all \
mechanics and delivers them to players separately.
- Never contradict the Rules Engine results provided to you. If the rules \
result says the attack missed, narrate a miss. If it says the spell slot was \
consumed, narrate accordingly.
- Never reveal information the characters would not know. If the party has not \
met an NPC, do not use that NPC's name. If the party cannot see a trap, do not \
describe it."""

_OUTPUT_RULES = """\
Output format rules:
- Respond in plain text only. No Markdown, no HTML, no formatting syntax, \
no emoji.
- Narrative responses: 2-4 paragraphs.
- Simple acknowledgments (opening a door, picking up an item): 1-2 sentences.
- Dialogue: use quotation marks. Attribute dialogue to the NPC speaking.
- Do not start responses with "I" or refer to yourself as the DM."""

_SUGGESTED_ACTIONS_INSTRUCTIONS = """\
After every narrative response, append a GMSignals block. In that block, \
include a "suggested_actions" field: a JSON array of 0–3 action suggestions \
for the active player.

Rules for suggested_actions:
- Default to 2 suggestions. Omit entirely (empty array) only when the scene \
makes suggestions unnecessary or intrusive — for example, mid-combat turns \
where the situation speaks for itself, or turns after a major revelation where \
player reflection is the natural response.
- Each suggestion must be a first-person action phrase in present tense, \
5–12 words. Examples: "Slip through the gap before the guards arrive", \
"Demand the harbormaster explain herself", \
"Throw your cloak over the lantern and run".
- Suggestions must be grounded in the specific scene: location, NPCs present, \
objects described in the narration, and the character's established capabilities.
- Suggestions must not assume mechanical outcomes. They describe intent, \
not resolution. Do not write "Attack the guard and roll high".
- Include at least one non-combat option when combat is not already underway.
- The third suggestion, when present, should be unexpected — something creative \
or oblique the player is unlikely to have thought of independently.
- No mechanical labels ("Cast Fireball"), no parenthetical annotations \
("(uses a spell slot)"), no numbered prefixes.
- Maximum 3 entries. Never produce more than 3."""


def build_system_prompt(
    dm_persona: str | None,
    campaign_tone: str | None,
    is_multiplayer: bool,
) -> str:
    """Construct the system prompt from campaign settings.

    Args:
        dm_persona: Campaign-specific DM persona text. If None, the default
            persona is used.
        campaign_tone: Campaign tone descriptor (e.g. "dark and gritty",
            "lighthearted adventure"). Injected into the persona section if
            provided.
        is_multiplayer: Whether the campaign has multiple player characters.
            If True, multiplayer narration instructions are included.

    Returns:
        A complete system prompt string ready for the Anthropic API.
    """
    parts: list[str] = []

    # --- Persona ---
    persona = dm_persona.strip() if dm_persona else _DEFAULT_DM_PERSONA
    if campaign_tone:
        persona += f"\n\nCampaign tone: {campaign_tone.strip()}"
    parts.append(persona)

    # --- Hard constraints ---
    parts.append(_HARD_CONSTRAINTS)

    # --- Output rules ---
    parts.append(_OUTPUT_RULES)

    # --- Suggested actions instructions (ADR-0015) ---
    parts.append(_SUGGESTED_ACTIONS_INSTRUCTIONS)

    # --- Multiplayer instructions ---
    if is_multiplayer:
        multiplayer = """\
Multiplayer narration:
- Address the acting player by their character name.
- Acknowledge other present characters naturally within the narration \
(their reactions, positions, expressions).
- In combat, narrate only the current turn's action. Do not narrate \
other players' future actions or pre-empt their decisions.
- Give brief reaction opportunities for non-acting players through \
environmental detail (sounds they hear, things they notice)."""
        parts.append(multiplayer)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Character state builder
# ---------------------------------------------------------------------------


def _build_character_state(character: Character) -> CharacterState:
    """Convert a database Character (with loaded relationships) to a snapshot."""
    conditions = [c.condition_name for c in character.conditions]

    # Spell slots: keep only slots with remaining charges.
    # DB stores as {"1": 2, "2": 1, ...} (JSON keys are strings).
    remaining_slots: dict[int, int] = {}
    for k, v in character.spell_slots.items():
        if isinstance(v, int) and v > 0:
            remaining_slots[int(k)] = v

    # Inventory: take up to MAX_INVENTORY_ITEMS, names only.
    inventory_names = [item.name for item in character.inventory[:_MAX_INVENTORY_ITEMS]]

    return CharacterState(
        name=character.name,
        class_name=character.class_name,
        level=character.level,
        hp=character.hp,
        max_hp=character.max_hp,
        ac=character.ac,
        conditions=conditions,
        spell_slots=remaining_slots,
        key_inventory=inventory_names,
    )


# ---------------------------------------------------------------------------
# Scene context builder
# ---------------------------------------------------------------------------


def _build_scene_context(state: CampaignState) -> SceneContext:
    """Extract SceneContext from CampaignState.

    ``scene_context`` (Text column) holds the 2-3 sentence location description.
    Structured scene fields are read from ``world_state`` (JSONB):
      - location     (str)
      - npcs         (list[str])
      - environment  (str)
      - threats      (list[str])
      - time_of_day  (str)
    """
    ws = state.world_state or {}
    return SceneContext(
        location=str(ws.get("location", "Unknown location")),
        description=state.scene_context.strip(),
        npcs=list(ws.get("npcs", [])),
        environment=str(ws.get("environment", "")),
        threats=list(ws.get("threats", [])),
        time_of_day=str(ws.get("time_of_day", "")),
    )


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------


async def build_snapshot(
    campaign_id: uuid.UUID,
    current_turn: TurnContext,
    db_session: AsyncSession,
) -> StateSnapshot:
    """Assemble a complete state snapshot for the Narrator.

    Loads campaign, CampaignState, and all Characters (with inventory and
    conditions) for the campaign in a single query. Applies token budget
    enforcement (inventory truncated to 10 items per character).

    Args:
        campaign_id: The campaign to snapshot. Must exist and have an
            associated CampaignState.
        current_turn: The action and optional Rules Engine result for this turn.
        db_session: Async SQLAlchemy session. Must be scoped to the campaign
            (ADR-0004: campaign_id filter on every query).

    Raises:
        ValueError: If the campaign or its CampaignState does not exist.
    """
    # Single query: campaign + state + characters + inventory + conditions
    result = await db_session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(
            selectinload(Campaign.state),
            selectinload(Campaign.characters).selectinload(Character.inventory),
            selectinload(Campaign.characters).selectinload(Character.conditions),
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")
    if campaign.state is None:
        raise ValueError(f"Campaign {campaign_id} has no CampaignState")

    # Build character snapshots
    character_states = [_build_character_state(c) for c in campaign.characters]

    # Build scene context
    scene = _build_scene_context(campaign.state)

    # Query NPCs relevant to the current scene / recent turns (ADR-0013)
    current_turn_number = campaign.state.turn_count
    recency_threshold = max(0, current_turn_number - 10)
    scene_location = str((campaign.state.world_state or {}).get("location", ""))

    npc_result = await db_session.execute(
        select(NPC)
        .where(NPC.campaign_id == campaign_id)
        .where(
            or_(
                NPC.scene_location == scene_location,
                NPC.last_seen_turn >= recency_threshold,
                # ADR-0013 §2: predefined NPCs with no scene_location are always included
                # so campaign authors don't need to pre-assign scenes
                and_(
                    NPC.origin == "predefined",
                    NPC.scene_location.is_(None),
                ),
            )
        )
        .where(
            or_(
                NPC.status.notin_(["dead", "fled"]),
                NPC.plot_significant.is_(True),
            )
        )
    )
    raw_npcs = npc_result.scalars().all()

    # Derive system prompt parameters
    ws = campaign.state.world_state or {}
    campaign_tone: str | None = ws.get("tone") or None
    is_multiplayer = len(campaign.characters) > 1
    is_combat = str(ws.get("mode", "exploration")).lower() == "combat"

    npc_dicts = [_serialize_npc_compact(n, combat_mode=is_combat) for n in raw_npcs]

    system_prompt = build_system_prompt(
        dm_persona=campaign.dm_persona,
        campaign_tone=campaign_tone,
        is_multiplayer=is_multiplayer,
    )

    snapshot = StateSnapshot(
        system_prompt=system_prompt,
        characters=character_states,
        scene=scene,
        rolling_summary=campaign.state.rolling_summary,
        current_turn=current_turn,
        npcs=npc_dicts,
        session_mode=str(ws.get("mode", "exploration")),
    )

    # Estimate total token count for the assembled prompt (ADR-0018 observability).
    # We serialise the snapshot and count across system + user message to get a
    # single budget figure.  This avoids a separate tokeniser dependency.
    serialized = serialize_snapshot(snapshot)
    system_text: str = serialized["system"]  # type: ignore[assignment]
    messages_list = serialized["messages"]  # type: ignore[assignment]
    user_text: str = messages_list[0]["content"]  # type: ignore[index]
    snapshot.estimated_token_count = estimate_tokens(system_text) + estimate_tokens(user_text)

    return snapshot


# ---------------------------------------------------------------------------
# Snapshot serialisation
# ---------------------------------------------------------------------------


def _serialize_npc_compact(npc: NPC, *, combat_mode: bool = False) -> dict:
    """Produce a compact NPC dict for the snapshot.

    Exploration mode: name, role, disposition, status, appearance.
    Combat mode: additionally includes hp_current, hp_max, ac for alive NPCs.
    """
    entry: dict = {
        "name": npc.name,
        "role": npc.role,
        "disposition": npc.disposition,
        "status": npc.status,
        "appearance": npc.appearance,
    }
    if combat_mode and npc.status == "alive":
        entry["hp_current"] = npc.hp_current
        entry["hp_max"] = npc.hp_max
        entry["ac"] = npc.ac
    return entry


def _serialize_npcs(npcs: list[dict]) -> str:
    """Render NPC list as plain text for the prompt."""
    if not npcs:
        return ""
    lines: list[str] = ["NPCs:"]
    for npc in npcs:
        name = npc.get("name", "Unknown")
        role = npc.get("role")
        disposition = npc.get("disposition", "unknown")
        status = npc.get("status", "unknown")
        appearance = npc.get("appearance")

        label = f"{name}"
        if role:
            label += f" ({role})"
        label += f" — {disposition}, {status}"
        if appearance:
            label += f". {appearance}"

        # Combat stats
        if "hp_current" in npc and npc["hp_current"] is not None:
            label += f" HP: {npc['hp_current']}/{npc.get('hp_max', '?')}"
        if "ac" in npc and npc["ac"] is not None:
            label += f" AC: {npc['ac']}"

        lines.append(f"  {label}")
    return "\n".join(lines)


def _serialize_character(char: CharacterState) -> str:
    """Render one character as plain text."""
    lines: list[str] = [
        f"{char.name} ({char.class_name}, Level {char.level}): "
        f"{char.hp}/{char.max_hp} HP, AC {char.ac}"
    ]
    if char.conditions:
        lines.append(f"  Conditions: {', '.join(char.conditions)}")
    if char.spell_slots:
        slots_str = ", ".join(
            f"Level {lvl}: {remaining}" for lvl, remaining in sorted(char.spell_slots.items())
        )
        lines.append(f"  Spell Slots Remaining: {slots_str}")
    if char.key_inventory:
        lines.append(f"  Inventory: {', '.join(char.key_inventory)}")
    return "\n".join(lines)


def _serialize_scene(scene: SceneContext) -> str:
    """Render the scene context as plain text."""
    parts: list[str] = [f"Location: {scene.location}"]
    if scene.description:
        parts.append(scene.description)
    if scene.time_of_day:
        parts.append(f"Time: {scene.time_of_day}")
    if scene.environment:
        parts.append(f"Environment: {scene.environment}")
    if scene.npcs:
        parts.append("NPCs present: " + "; ".join(scene.npcs))
    if scene.threats:
        parts.append("Threats: " + "; ".join(scene.threats))
    return "\n".join(parts)


def _serialize_turn(turn: TurnContext) -> str:
    """Render the current turn as plain text."""
    lines = [f"Player action: {turn.player_action}"]
    if turn.rules_result:
        lines.append(f"Rules Engine result: {turn.rules_result}")
    return "\n".join(lines)


def serialize_snapshot(snapshot: StateSnapshot) -> dict[str, object]:
    """Convert the snapshot to the Anthropic messages API format.

    Returns a dict with:
    - ``"system"``: the system prompt string (system parameter)
    - ``"messages"``: a list containing one user message with the assembled
      context in ADR-0002 component order

    Component order in the user message (ADR-0002 — do not reorder):
    1. Characters  (stable within turn — prompt cache hit)
    2. Scene       (stable within scene — prompt cache hit)
    3. Rolling summary (changes every turn — cache miss)
    4. Current turn    (unique — cache miss)

    The context is plain text — no JSON, no Markdown. Claude receives
    human-readable game state, not a structured data format to parse.
    """
    sections: list[str] = []

    # 1. Characters
    if snapshot.characters:
        char_lines = ["Party status:"]
        char_lines.extend(_serialize_character(c) for c in snapshot.characters)
        sections.append("\n".join(char_lines))

    # 2. Scene
    sections.append(_serialize_scene(snapshot.scene))

    # 2b. NPCs (ADR-0013) — rendered after scene, before rolling summary
    if snapshot.npcs:
        sections.append(_serialize_npcs(snapshot.npcs))

    # 3. Rolling summary
    if snapshot.rolling_summary:
        sections.append(f"Recent events:\n{snapshot.rolling_summary}")

    # 4. Current turn
    sections.append(_serialize_turn(snapshot.current_turn))

    user_message = "\n\n".join(sections)

    return {
        "system": snapshot.system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
