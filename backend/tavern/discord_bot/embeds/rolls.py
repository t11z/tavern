"""Dice roll embed builders and interactive roll prompt view.

Provides:
  build_roll_prompt_embed  — amber embed with dice spec and timeout footer
  RollPromptView           — 🎲 Roll button + per-option buttons; only the
                             active player can click; buttons disabled on use
  build_roll_result_embed  — coloured result embed (gold/nat-20, red/nat-1,
                             green/hit, red/miss); advantage dice shown

All embed functions are pure (no I/O). RollPromptView calls the API on click.
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


def _option_emoji(option_id: str) -> str:
    return _OPTION_EMOJI.get(option_id, "🔮")


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
