"""Dice roll embed builders and interactive roll prompt view.

Provides:
  build_roll_prompt_embed          — amber embed with dice spec and timeout footer
  RollPromptView                   — 🎲 Roll button + per-option buttons; only the
                                     active player can click; buttons disabled on use
  build_roll_result_embed          — coloured result embed (gold/nat-20, red/nat-1,
                                     green/hit, red/miss); advantage dice shown

  build_reaction_window_embed      — amber embed listing all eligible reactors
  ReactionWindowView               — per-reactor reaction + pass buttons; player-
                                     filtered; global all-pass button
  build_self_reaction_embed        — amber embed for rolling player's self-reactions
  SelfReactionView                 — self-reaction buttons + accept; rolling-player-only
  build_reaction_used_embed        — updated embed after a reaction is used
  build_reaction_window_closed_embed — final-outcome embed after window closes

All embed functions are pure (no I/O). Views call the API on click.
"""

from __future__ import annotations

import logging

import discord

from ..services.api_client import TavernAPI, TavernAPIError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

TAVERN_AMBER = discord.Colour(0xD4A24E)
_CRIT_HIT_COLOUR = discord.Colour(0xFFD700)  # Gold
_HIT_COLOUR = discord.Colour(0x15803D)  # Green
_MISS_COLOUR = discord.Colour(0xB91C1C)  # Red

# ---------------------------------------------------------------------------
# Option → emoji map
# ---------------------------------------------------------------------------

_OPTION_EMOJI: dict[str, str] = {
    "reckless_attack": "⚡",
    "great_weapon_master": "⚔️",
    "sharpshooter": "🎯",
    "bardic_inspiration": "🎵",
    "guided_strike": "✨",
    "elven_accuracy": "🌙",
}

_OUTCOMES_SUCCESS = {"hit", "success", "save"}

# ---------------------------------------------------------------------------
# Reaction → emoji map
# ---------------------------------------------------------------------------

_REACTION_EMOJI: dict[str, str] = {
    "shield_spell": "🛡️",
    "silvery_barbs": "🌟",
    "counterspell": "🔮",
    "bardic_inspiration": "🎵",
    "cutting_words": "✂️",
    "lucky_feat": "🍀",
    "absorb_elements": "🌊",
    "legendary_resistance": "💎",
    "parry": "🗡️",
}


def _option_emoji(option_id: str) -> str:
    return _OPTION_EMOJI.get(option_id, "🔮")


def _reaction_emoji(reaction_id: str) -> str:
    return _REACTION_EMOJI.get(reaction_id, "⚡")


def _format_target(target: dict) -> str:  # type: ignore[type-arg]
    """Format a target dict into a human-readable string."""
    target_type = target.get("type", "")
    value = target.get("value", "?")
    target_name = target.get("target_name", "")

    if target_type == "ac":
        return f"AC {value}" + (f" ({target_name})" if target_name else "")
    if target_type == "dc":
        return f"DC {value}"
    return str(value) if value != "?" else "?"


# ---------------------------------------------------------------------------
# Roll prompt embed
# ---------------------------------------------------------------------------


def build_roll_prompt_embed(roll_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the ⚔️ roll prompt embed shown before a player rolls.

    Args:
        roll_data: Payload from the ``turn.roll_required`` WebSocket event.
                   Expected keys: ``description``, ``type``, ``dice``,
                   ``base_modifier``, ``target``, ``timeout_seconds``.

    Returns:
        An amber ``discord.Embed`` with a footer showing the timeout.
    """
    description = roll_data.get("description") or "Action"
    roll_type = roll_data.get("type", "roll")
    dice = roll_data.get("dice", "1d20")
    modifier = roll_data.get("base_modifier", 0)
    target = roll_data.get("target") or {}
    target_str = _format_target(target)
    timeout = roll_data.get("timeout_seconds", 120)

    mod_str = f"+ {modifier}" if modifier >= 0 else f"- {abs(modifier)}"
    body = f"Roll for **{roll_type}**! ({dice} {mod_str} vs {target_str})"

    embed = discord.Embed(
        title=f"⚔️ {description}",
        description=body,
        colour=TAVERN_AMBER,
    )
    embed.set_footer(text=f"⏱️ {timeout}s")
    return embed


# ---------------------------------------------------------------------------
# Roll prompt view (interactive buttons)
# ---------------------------------------------------------------------------


class RollPromptView(discord.ui.View):
    """Interactive buttons for the roll prompt.

    Renders:
      • 🎲 Roll — plain roll with no pre-roll options
      • One button per available ``pre_roll_option``, with a contextual emoji

    Only the active player (``active_player_id``) may interact.  All buttons
    are disabled immediately after any click.
    """

    def __init__(
        self,
        api: TavernAPI,
        campaign_id: str,
        turn_id: str,
        roll_id: str,
        active_player_id: int,
        pre_roll_options: list[dict],  # type: ignore[type-arg]
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._api = api
        self._campaign_id = campaign_id
        self._turn_id = turn_id
        self._roll_id = roll_id
        self._active_player_id = active_player_id

        # Plain roll button.
        plain_btn = discord.ui.Button(
            label="🎲 Roll",
            style=discord.ButtonStyle.primary,
            custom_id="roll_plain",
        )
        plain_btn.callback = self._make_callback([])
        self.add_item(plain_btn)

        # One button per available pre-roll option.
        for i, option in enumerate(pre_roll_options):
            if not option.get("available", True):
                continue
            emoji = _option_emoji(option.get("id", ""))
            btn = discord.ui.Button(
                label=f"{emoji} {option.get('name', option.get('id', 'Option'))}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"roll_option_{i}",
            )
            btn.callback = self._make_callback([option["id"]])
            self.add_item(btn)

    def _make_callback(self, options: list[str]):  # type: ignore[return]
        """Return an async callback that executes the roll with the given options."""

        async def callback(interaction: discord.Interaction) -> None:
            # Guard: only the active player may click.
            if interaction.user.id != self._active_player_id:
                await interaction.response.send_message(
                    "It's not your turn to roll!", ephemeral=True
                )
                return

            # Disable all buttons immediately to prevent double-clicks.
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.response.edit_message(view=self)

            # Execute the roll via the API.
            try:
                await self._api.execute_roll(
                    self._campaign_id, self._turn_id, self._roll_id, options
                )
            except TavernAPIError as exc:
                logger.error("execute_roll failed for roll %s: %s", self._roll_id, exc)
                await interaction.followup.send(f"❌ Roll failed: {exc.message}", ephemeral=True)
            self.stop()

        return callback


# ---------------------------------------------------------------------------
# Roll result embed
# ---------------------------------------------------------------------------


def build_roll_result_embed(result_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the 🎲 roll result embed.

    Handles:
      • Normal hit / miss → green / red
      • Natural 20        → gold, "CRITICAL HIT!" title
      • Natural 1         → red, "Critical Miss!" title
      • Advantage         → shows both dice, highest used
      • Next roll hint    → added as a field if ``next_roll`` key present

    Args:
        result_data: Payload from the ``turn.roll_executed`` event.
                     Expected keys: ``dice``, ``natural_result``, ``modifier``,
                     ``total``, ``target``, ``outcome``, ``advantage``,
                     ``rolls`` (list of individual die values), optional
                     ``next_roll`` (dict with ``type`` and ``dice``).

    Returns:
        A colour-coded ``discord.Embed``.
    """
    dice: str = result_data.get("dice", "1d20")
    natural: int = result_data.get("natural_result", 0)
    modifier: int = result_data.get("modifier", 0)
    total: int = result_data.get("total", 0)
    target: dict = result_data.get("target") or {}  # type: ignore[assignment]
    outcome: str = result_data.get("outcome", "unknown")
    advantage: bool = bool(result_data.get("advantage", False))
    rolls: list[int] = result_data.get("rolls") or [natural]
    next_roll: dict | None = result_data.get("next_roll")  # type: ignore[assignment]

    target_str = _format_target(target)
    outcome_upper = outcome.upper()

    # Determine title and colour.
    if natural == 20:
        title = "🎲 CRITICAL HIT!"
        colour = _CRIT_HIT_COLOUR
    elif natural == 1:
        title = "🎲 Critical Miss!"
        colour = _MISS_COLOUR
    elif outcome.lower() in _OUTCOMES_SUCCESS:
        title = "🎲 Roll Result"
        colour = _HIT_COLOUR
    else:
        title = "🎲 Roll Result"
        colour = _MISS_COLOUR

    # Build the result line.
    mod_str = f"+ {modifier}" if modifier >= 0 else f"- {abs(modifier)}"

    if advantage and len(rolls) >= 2:
        # Show both dice values; the highest is the used one.
        used = max(rolls)
        other = min(rolls)
        result_line = (
            f"**{used}** ~~{other}~~ ({dice}) {mod_str} = **{total}** "
            f"vs {target_str} — **{outcome_upper}**"
        )
    else:
        result_line = (
            f"**{natural}** ({dice}) {mod_str} = **{total}** vs {target_str} — **{outcome_upper}**"
        )

    embed = discord.Embed(title=title, description=result_line, colour=colour)

    # If another roll immediately follows (e.g. damage after hit), hint at it.
    if next_roll:
        next_type = next_roll.get("type", "roll")
        next_dice = next_roll.get("dice", "")
        next_mod = next_roll.get("modifier", 0)
        next_mod_str = f"+ {next_mod}" if next_mod >= 0 else f"- {abs(next_mod)}"
        hint = f"Roll for **{next_type}**! ({next_dice} {next_mod_str})"
        embed.add_field(name="⏭️ Up Next", value=hint, inline=False)

    return embed


# ---------------------------------------------------------------------------
# Shared helper for reaction embeds
# ---------------------------------------------------------------------------


def _format_roll_context(roll_result: dict) -> str:  # type: ignore[type-arg]
    """Build a short roll-context line from a roll_result sub-dict."""
    natural = roll_result.get("natural", 0)
    total = roll_result.get("total", 0)
    target = roll_result.get("target") or {}
    outcome = roll_result.get("provisional_outcome", "unknown")
    target_str = _format_target(target) if target else ""

    line = f"🎲 {natural} = **{total}**"
    if target_str:
        line += f" vs {target_str}"
    line += f" — **{outcome.upper()}**"
    return line


def _reactor_lines(available_reactions: list) -> list[str]:  # type: ignore[type-arg]
    """Build description lines listing each reactor and their available reactions."""
    lines: list[str] = []
    for reactor in available_reactions:
        name = reactor.get("reactor_name", "?")
        reactions: list[dict] = reactor.get("reactions") or []  # type: ignore[assignment]
        parts = [f"{_reaction_emoji(r.get('id', ''))} {r.get('name', '?')}" for r in reactions]
        lines.append(f"**{name}**: {' · '.join(parts)}")
    return lines


# ---------------------------------------------------------------------------
# Reaction window embed
# ---------------------------------------------------------------------------


def build_reaction_window_embed(reaction_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the ⚡ reaction window embed posted when cross-player reactions open.

    Args:
        reaction_data: Payload from the ``turn.reaction_window`` WebSocket event.
                       Expected keys: ``roll_result`` (dict with ``attacker``,
                       ``defender``, ``natural``, ``total``, ``target``,
                       ``provisional_outcome``), ``available_reactions`` (list),
                       ``window_seconds``.

    Returns:
        An amber ``discord.Embed`` listing each reactor and their options.
    """
    roll_result: dict = reaction_data.get("roll_result") or {}  # type: ignore[assignment]
    attacker: str = roll_result.get("attacker", "")
    defender: str = roll_result.get("defender", "")
    available_reactions: list = reaction_data.get("available_reactions") or []
    window_seconds: int = reaction_data.get("window_seconds", 15)

    if attacker and defender:
        context = f"{attacker} → {defender}"
    elif attacker:
        context = attacker
    else:
        context = "Roll result"

    lines = [context, _format_roll_context(roll_result), ""]
    lines.extend(_reactor_lines(available_reactions))

    embed = discord.Embed(
        title="⚡ REACTIONS AVAILABLE",
        description="\n".join(lines),
        colour=TAVERN_AMBER,
    )
    embed.set_footer(text=f"⏱️ {window_seconds}s")
    return embed


# ---------------------------------------------------------------------------
# Reaction window view (interactive buttons)
# ---------------------------------------------------------------------------


class ReactionWindowView(discord.ui.View):
    """Interactive buttons for cross-player reaction windows.

    Renders:
      • Per-reactor buttons: one per available reaction (emoji-labelled)
      • ⏭️ Pass button per reactor
      • ⏭️ All pass — skip (any player can click)

    Each reaction/pass button is guarded so only the reactor's Discord user
    can click it.  If the reactor's Discord user ID is unknown (``None`` in
    the identity map), the button is unguarded.
    """

    def __init__(
        self,
        api: TavernAPI,  # type: ignore[name-defined]
        campaign_id: str,
        turn_id: str,
        roll_id: str,
        available_reactions: list[dict],  # type: ignore[type-arg]
        identity_map: dict[str, int],
        responded: set[str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._api = api
        self._campaign_id = campaign_id
        self._turn_id = turn_id
        self._roll_id = roll_id
        self._identity_map = identity_map
        _responded = responded or set()

        # Track remaining reactor char IDs for all-pass submission.
        self._reactor_char_ids: list[str] = []

        for reactor in available_reactions:
            char_id: str = reactor.get("reactor_character_id", "")
            reactor_name: str = reactor.get("reactor_name", "?")
            reactions: list[dict] = reactor.get("reactions") or []  # type: ignore[assignment]

            if char_id in _responded:
                continue

            self._reactor_char_ids.append(char_id)
            discord_uid: int | None = identity_map.get(char_id)

            for reaction in reactions:
                r_id: str = reaction.get("id", "")
                r_name: str = reaction.get("name", r_id)
                emoji = _reaction_emoji(r_id)
                btn = discord.ui.Button(
                    label=f"{emoji} {r_name}",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"react_{char_id}_{r_id}",
                )
                btn.callback = self._make_reaction_callback(
                    char_id, r_id, discord_uid, reactor_name
                )
                self.add_item(btn)

            # Per-reactor pass button.
            pass_btn = discord.ui.Button(
                label=f"⏭️ Pass ({reactor_name})",
                style=discord.ButtonStyle.secondary,
                custom_id=f"pass_{char_id}",
            )
            pass_btn.callback = self._make_pass_callback(char_id, discord_uid, reactor_name)
            self.add_item(pass_btn)

        # Global all-pass button — no player guard.
        all_pass_btn = discord.ui.Button(
            label="⏭️ All pass — skip",
            style=discord.ButtonStyle.secondary,
            custom_id="all_pass",
        )
        all_pass_btn.callback = self._all_pass_callback
        self.add_item(all_pass_btn)

    def _make_reaction_callback(
        self,
        char_id: str,
        reaction_id: str,
        discord_uid: int | None,
        reactor_name: str,
    ):  # type: ignore[return]
        async def callback(interaction: discord.Interaction) -> None:
            if discord_uid is not None and interaction.user.id != discord_uid:
                await interaction.response.send_message(
                    f"This reaction belongs to **{reactor_name}**, not you!",
                    ephemeral=True,
                )
                return

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.response.edit_message(view=self)

            try:
                await self._api.submit_reaction(
                    self._campaign_id, self._turn_id, self._roll_id, char_id, reaction_id
                )
            except TavernAPIError as exc:
                logger.error("submit_reaction failed for %s: %s", reaction_id, exc)
                await interaction.followup.send(
                    f"❌ Reaction failed: {exc.message}", ephemeral=True
                )
            self.stop()

        return callback

    def _make_pass_callback(
        self,
        char_id: str,
        discord_uid: int | None,
        reactor_name: str,
    ):  # type: ignore[return]
        async def callback(interaction: discord.Interaction) -> None:
            if discord_uid is not None and interaction.user.id != discord_uid:
                await interaction.response.send_message(
                    f"This pass belongs to **{reactor_name}**, not you!",
                    ephemeral=True,
                )
                return

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.response.edit_message(view=self)

            try:
                await self._api.submit_pass(
                    self._campaign_id, self._turn_id, self._roll_id, char_id
                )
            except TavernAPIError as exc:
                logger.error("submit_pass failed for %s: %s", char_id, exc)
                await interaction.followup.send(f"❌ Pass failed: {exc.message}", ephemeral=True)
            self.stop()

        return callback

    async def _all_pass_callback(self, interaction: discord.Interaction) -> None:
        """Any player can click this — submits pass for all remaining reactors."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)

        for char_id in self._reactor_char_ids:
            try:
                await self._api.submit_pass(
                    self._campaign_id, self._turn_id, self._roll_id, char_id
                )
            except TavernAPIError as exc:
                logger.error("all_pass failed for %s: %s", char_id, exc)

        self.stop()


# ---------------------------------------------------------------------------
# Self-reaction embed
# ---------------------------------------------------------------------------


def build_self_reaction_embed(self_reaction_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the ✨ self-reaction embed shown to the rolling player.

    Displayed after a roll when the rolling player has abilities that trigger
    on seeing the result (e.g. Lucky feat).

    Args:
        self_reaction_data: Payload from the ``turn.self_reaction_window`` event.
                            Expected keys: ``natural_result``, ``modifier``,
                            ``total``, ``target``, ``provisional_outcome``,
                            ``self_reactions`` (list), ``self_reaction_window_seconds``.

    Returns:
        An amber ``discord.Embed`` showing the roll result and available self-reactions.
    """
    natural: int = self_reaction_data.get("natural_result", 0)
    modifier: int = self_reaction_data.get("modifier", 0)
    total: int = self_reaction_data.get("total", 0)
    target: dict = self_reaction_data.get("target") or {}  # type: ignore[assignment]
    outcome: str = self_reaction_data.get("provisional_outcome", "unknown")
    window_seconds: int = self_reaction_data.get("self_reaction_window_seconds", 10)

    mod_str = f"+ {modifier}" if modifier >= 0 else f"- {abs(modifier)}"
    target_str = _format_target(target) if target else ""
    result_line = f"🎲 **{natural}** {mod_str} = **{total}**"
    if target_str:
        result_line += f" vs {target_str}"
    result_line += f" — **{outcome.upper()}**"

    embed = discord.Embed(
        title="✨ Self-Reaction Available",
        description=result_line,
        colour=TAVERN_AMBER,
    )
    embed.set_footer(text=f"⏱️ {window_seconds}s — Only you can use this")
    return embed


# ---------------------------------------------------------------------------
# Self-reaction view (interactive buttons)
# ---------------------------------------------------------------------------


class SelfReactionView(discord.ui.View):
    """Interactive buttons for self-reactions (Lucky, Flash of Genius, etc.).

    Only the rolling player (``rolling_player_id``) may interact.  Buttons are
    disabled immediately after any click.
    """

    def __init__(
        self,
        api: TavernAPI,  # type: ignore[name-defined]
        campaign_id: str,
        turn_id: str,
        roll_id: str,
        character_id: str,
        rolling_player_id: int,
        self_reactions: list[dict],  # type: ignore[type-arg]
        timeout: float = 10.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._api = api
        self._campaign_id = campaign_id
        self._turn_id = turn_id
        self._roll_id = roll_id
        self._character_id = character_id
        self._rolling_player_id = rolling_player_id

        for i, reaction in enumerate(self_reactions):
            r_id: str = reaction.get("id", "")
            r_name: str = reaction.get("name", r_id)
            uses: int | None = reaction.get("uses_remaining")
            emoji = _reaction_emoji(r_id)
            label = f"{emoji} {r_name}"
            if uses is not None:
                label += f" ({uses})"

            btn = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"self_react_{i}_{r_id}",
            )
            btn.callback = self._make_self_reaction_callback(r_id)
            self.add_item(btn)

        accept_btn = discord.ui.Button(
            label="❌ Accept result",
            style=discord.ButtonStyle.secondary,
            custom_id="self_accept",
        )
        accept_btn.callback = self._accept_callback
        self.add_item(accept_btn)

    def _make_self_reaction_callback(self, reaction_id: str):  # type: ignore[return]
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self._rolling_player_id:
                await interaction.response.send_message(
                    "Only the rolling player can use self-reactions!",
                    ephemeral=True,
                )
                return

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.response.edit_message(view=self)

            try:
                await self._api.submit_reaction(
                    self._campaign_id,
                    self._turn_id,
                    self._roll_id,
                    self._character_id,
                    reaction_id,
                )
            except TavernAPIError as exc:
                logger.error("self_reaction failed for %s: %s", reaction_id, exc)
                await interaction.followup.send(
                    f"❌ Self-reaction failed: {exc.message}", ephemeral=True
                )
            self.stop()

        return callback

    async def _accept_callback(self, interaction: discord.Interaction) -> None:
        """Accept the roll result as-is; submits a pass for self-reactions."""
        if interaction.user.id != self._rolling_player_id:
            await interaction.response.send_message(
                "Only the rolling player can accept the result!",
                ephemeral=True,
            )
            return

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            await self._api.submit_pass(
                self._campaign_id, self._turn_id, self._roll_id, self._character_id
            )
        except TavernAPIError as exc:
            logger.error("self_accept pass failed: %s", exc)
            await interaction.followup.send(f"❌ Failed: {exc.message}", ephemeral=True)
        self.stop()


# ---------------------------------------------------------------------------
# Reaction used embed  (in-place update)
# ---------------------------------------------------------------------------


def build_reaction_used_embed(reaction_used_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the updated reaction window embed after a reaction is used.

    Handles both player reactions and NPC reactions (distinguished by
    ``is_npc``).  Shows what was used, the new outcome, and the list of
    reactors who still have options.

    Args:
        reaction_used_data: Payload from the ``turn.reaction_used`` event.
                            Expected keys: ``reactor_name``, ``reaction_id``,
                            ``reaction_name``, ``is_npc``, ``new_outcome``,
                            ``uses_remaining`` (optional), ``remaining_reactions``
                            (list), ``window_seconds``.

    Returns:
        An amber ``discord.Embed`` ready to replace the original window embed.
    """
    reactor_name: str = reaction_used_data.get("reactor_name", "Unknown")
    reaction_id: str = reaction_used_data.get("reaction_id", "")
    reaction_name: str = reaction_used_data.get("reaction_name", "Reaction")
    is_npc: bool = bool(reaction_used_data.get("is_npc", False))
    new_outcome: str = reaction_used_data.get("new_outcome", "unknown")
    uses_remaining: int | None = reaction_used_data.get("uses_remaining")
    remaining_reactions: list = reaction_used_data.get("remaining_reactions") or []
    window_seconds: int = reaction_used_data.get("window_seconds", 15)

    emoji = _reaction_emoji(reaction_id)

    if is_npc:
        action_line = f"⚡ **{reactor_name}** uses **{reaction_name}**!"
        if uses_remaining is not None:
            action_line += f" ({uses_remaining} remaining)"
    else:
        action_line = f"{emoji} **{reactor_name}** uses **{reaction_name}**!"

    outcome_line = f"Outcome now: **{new_outcome.upper()}**"

    lines = [action_line, outcome_line]
    reactor_lines = _reactor_lines(remaining_reactions)
    if reactor_lines:
        lines.append("")
        lines.extend(reactor_lines)

    embed = discord.Embed(
        title="⚡ REACTIONS AVAILABLE",
        description="\n".join(lines),
        colour=TAVERN_AMBER,
    )
    if window_seconds:
        embed.set_footer(text=f"⏱️ {window_seconds}s")
    return embed


# ---------------------------------------------------------------------------
# Reaction window closed embed
# ---------------------------------------------------------------------------


def build_reaction_window_closed_embed(closed_data: dict) -> discord.Embed:  # type: ignore[type-arg]
    """Build the final embed shown when the reaction window closes.

    Colour is green for a successful outcome (hit/success/save) and red
    otherwise.

    Args:
        closed_data: Payload from the ``turn.reaction_window_closed`` event.
                     Expected keys: ``final_outcome``, ``roll_result`` (optional
                     dict with ``natural``, ``total``, ``target``).

    Returns:
        A colour-coded ``discord.Embed`` showing the final roll outcome.
    """
    final_outcome: str = closed_data.get("final_outcome", "unknown")
    roll_result: dict = closed_data.get("roll_result") or {}  # type: ignore[assignment]

    colour = _HIT_COLOUR if final_outcome.lower() in _OUTCOMES_SUCCESS else _MISS_COLOUR

    natural = roll_result.get("natural", 0)
    total = roll_result.get("total", 0)
    target = roll_result.get("target") or {}

    if natural and total:
        target_str = _format_target(target) if target else ""
        description = f"🎲 {natural} = **{total}**"
        if target_str:
            description += f" vs {target_str}"
        description += f" — **{final_outcome.upper()}**"
    else:
        description = f"Final outcome: **{final_outcome.upper()}**"

    return discord.Embed(
        title="✅ Reactions Resolved",
        description=description,
        colour=colour,
    )
