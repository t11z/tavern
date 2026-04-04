"""In-memory state model for the Discord bot.

The bot holds *minimal* local state — only what is needed to route Discord
events to the correct campaign and to track short-lived interactive windows
(pending rolls, reaction windows). Everything here is recoverable from the
Tavern API on restart; there is no local persistence.

State classes are plain Python dataclasses. BotState is the single mutable
container the bot reads and writes throughout its lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class ChannelBinding:
    """Maps a Discord text channel to a Tavern campaign."""

    channel_id: int
    campaign_id: UUID
    guild_id: int


@dataclass
class PendingRoll:
    """A roll that has been requested but not yet triggered by the player.

    Lives on a channel while the turn is in ``awaiting_roll`` state.
    ``expires_at`` mirrors the server-side ``turn_timeout`` setting — when it
    passes, the server auto-rolls and the bot clears this record.
    """

    channel_id: int
    turn_id: UUID
    roll_id: UUID
    character_id: UUID
    expires_at: datetime


@dataclass
class ReactionWindow:
    """Tracks an open reaction window for a specific roll.

    ``eligible_reactors`` is the set of character UUIDs that may still react.
    ``responded`` is the set that have reacted or explicitly passed.  When
    ``responded`` equals ``eligible_reactors`` the window can be closed early.

    ``channel_id``, ``turn_id``, and ``message_id`` are set when the window
    is opened so that the bot can edit the window message in-place as reactions
    are used and submit API calls from the ``/pass`` command.
    """

    roll_id: UUID
    eligible_reactors: set[UUID] = field(default_factory=set)
    responded: set[UUID] = field(default_factory=set)
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    channel_id: int = 0
    turn_id: UUID | None = None
    message_id: int | None = None

    @property
    def all_responded(self) -> bool:
        return self.eligible_reactors.issubset(self.responded)

    def mark_responded(self, character_id: UUID) -> None:
        self.responded.add(character_id)


# ---------------------------------------------------------------------------
# BotState
# ---------------------------------------------------------------------------


class BotState:
    """Single mutable container for all transient bot state.

    Not thread-safe — the discord.py event loop is single-threaded so this is
    fine.  If background tasks are added in future, use asyncio.Lock.
    """

    def __init__(self) -> None:
        self.bindings: dict[int, ChannelBinding] = {}
        self.active_sessions: set[int] = set()
        self.pending_rolls: dict[int, PendingRoll] = {}
        self.reaction_windows: dict[str, ReactionWindow] = {}
        # channel_id → pinned session banner message_id
        self.pinned_banners: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Channel → campaign bindings
    # ------------------------------------------------------------------

    def bind_channel(self, binding: ChannelBinding) -> None:
        """Associate a Discord channel with a campaign."""
        self.bindings[binding.channel_id] = binding

    def unbind_channel(self, channel_id: int) -> None:
        """Remove the campaign binding for a channel (idempotent)."""
        self.bindings.pop(channel_id, None)

    def get_binding(self, channel_id: int) -> ChannelBinding | None:
        return self.bindings.get(channel_id)

    # ------------------------------------------------------------------
    # Game Mode  (active session in channel)
    # ------------------------------------------------------------------

    def is_game_mode(self, channel_id: int) -> bool:
        """Return True if the channel has an active session (Game Mode)."""
        return channel_id in self.active_sessions

    def set_game_mode(self, channel_id: int) -> None:
        """Mark a channel as being in Game Mode."""
        self.active_sessions.add(channel_id)

    def clear_game_mode(self, channel_id: int) -> None:
        """Remove Game Mode from a channel (idempotent)."""
        self.active_sessions.discard(channel_id)

    # ------------------------------------------------------------------
    # Pending rolls
    # ------------------------------------------------------------------

    def set_pending_roll(self, roll: PendingRoll) -> None:
        """Record a roll that is waiting for the player to trigger /roll."""
        self.pending_rolls[roll.channel_id] = roll

    def get_pending_roll(self, channel_id: int) -> PendingRoll | None:
        return self.pending_rolls.get(channel_id)

    def clear_pending_roll(self, channel_id: int) -> None:
        """Remove the pending roll for a channel (idempotent)."""
        self.pending_rolls.pop(channel_id, None)

    def has_pending_roll(self, channel_id: int) -> bool:
        return channel_id in self.pending_rolls

    # ------------------------------------------------------------------
    # Reaction windows
    # ------------------------------------------------------------------

    def set_reaction_window(self, window: ReactionWindow) -> None:
        self.reaction_windows[str(window.roll_id)] = window

    def get_reaction_window(self, roll_id: str | UUID) -> ReactionWindow | None:
        return self.reaction_windows.get(str(roll_id))

    def clear_reaction_window(self, roll_id: str | UUID) -> None:
        self.reaction_windows.pop(str(roll_id), None)

    def has_reaction_window(self, roll_id: str | UUID) -> bool:
        return str(roll_id) in self.reaction_windows

    # ------------------------------------------------------------------
    # Pinned session banners
    # ------------------------------------------------------------------

    def set_pinned_banner(self, channel_id: int, message_id: int) -> None:
        """Record the message ID of a pinned session banner."""
        self.pinned_banners[channel_id] = message_id

    def get_pinned_banner(self, channel_id: int) -> int | None:
        return self.pinned_banners.get(channel_id)

    def clear_pinned_banner(self, channel_id: int) -> None:
        """Remove the pinned banner record for a channel (idempotent)."""
        self.pinned_banners.pop(channel_id, None)
