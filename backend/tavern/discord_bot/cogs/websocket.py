"""WebSocket event listener cog.

Maintains one persistent WebSocket connection per active campaign session.
Receives server-pushed events and dispatches them as discord.py custom events
so other cogs can respond without coupling to the WebSocket layer.

Lifecycle:
    CampaignCog dispatches ``tavern_session_start`` when /tavern start runs.
    WebSocketCog receives it, opens a WS connection, and starts a listener task.

    CampaignCog dispatches ``tavern_session_stop`` when /tavern stop runs.
    WebSocketCog receives it, cancels the listener task, and closes the connection.

Reconnection:
    If the connection drops mid-session, the cog retries with exponential backoff
    (1 → 2 → 4 → 8 → … → 30 s).  If the first reconnect delay exceeds 5 seconds
    the cog posts a warning in the campaign channel and restores a ✅ banner on
    success.  The bot fetches current campaign state via REST on reconnect to
    recover any missed events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

import discord
import websockets
import websockets.exceptions
from discord.ext import commands

from ..services.api_client import TavernAPI, TavernAPIError

logger = logging.getLogger(__name__)

# How long to wait before posting an in-channel warning about a disconnect.
_WARN_AFTER_SECONDS = 5

# Reconnect back-off schedule (seconds); last value is used for all further attempts.
_BACKOFF = [1, 2, 4, 8, 15, 30]

# Maps raw WebSocket event types to discord.py custom event names.
_DISPATCH_MAP: dict[str, str] = {
    "session.state": "tavern_session_state",
    "turn.roll_required": "tavern_turn_roll_required",
    "turn.roll_executed": "tavern_turn_roll_executed",
    "turn.self_reaction_window": "tavern_turn_self_reaction_window",
    "turn.reaction_window": "tavern_turn_reaction_window",
    "turn.reaction_used": "tavern_turn_reaction_used",
    "turn.reaction_window_closed": "tavern_turn_reaction_window_closed",
    "turn.narrative_start": "tavern_turn_narrative_start",
    "turn.narrative_chunk": "tavern_turn_narrative_chunk",
    "turn.narrative_end": "tavern_turn_narrative_end",
    "character.updated": "tavern_character_updated",
    "player.joined": "tavern_player_joined",
    "player.left": "tavern_player_left",
    "campaign.session_started": "tavern_session_started",
    "campaign.session_ended": "tavern_session_ended",
    "system.error": "tavern_system_error",
}


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------


@dataclass
class WebSocketConnection:
    """Holds all mutable state for one active campaign WebSocket connection."""

    campaign_id: str
    channel_id: int
    ws: websockets.WebSocketClientProtocol
    task: asyncio.Task  # type: ignore[type-arg]
    reconnect_attempts: int = 0
    last_sequence_number: int = 0
    _warned_disconnect: bool = field(default=False, repr=False)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class WebSocketCog(commands.Cog):
    """Listens to campaign WebSocket streams and dispatches game events."""

    def __init__(self, bot: commands.Bot, api: TavernAPI, ws_base_url: str) -> None:
        self.bot = bot
        self.api = api
        # e.g. "ws://tavern:8000"
        self._ws_base = ws_base_url.rstrip("/")
        # channel_id → active connection
        self._connections: dict[int, WebSocketConnection] = {}

    # ------------------------------------------------------------------
    # Discord.py session lifecycle listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_tavern_session_start")
    async def on_tavern_session_start(self, campaign_id: str, channel_id: int) -> None:
        """Connect to the campaign's WebSocket when a session starts."""
        if channel_id in self._connections:
            logger.debug(
                "WebSocket already open for channel %d (campaign %s); ignoring start.",
                channel_id,
                campaign_id,
            )
            return

        await self._connect(channel_id, campaign_id)

    @commands.Cog.listener("on_tavern_session_stop")
    async def on_tavern_session_stop(self, campaign_id: str, channel_id: int) -> None:
        """Disconnect from the campaign's WebSocket when a session stops."""
        await self._close(channel_id)

    # ------------------------------------------------------------------
    # Cog unload — close all connections gracefully
    # ------------------------------------------------------------------

    async def cog_unload(self) -> None:
        channel_ids = list(self._connections)
        for channel_id in channel_ids:
            await self._close(channel_id)

    # ------------------------------------------------------------------
    # Internal: connect
    # ------------------------------------------------------------------

    async def _connect(self, channel_id: int, campaign_id: str) -> None:
        """Open a WebSocket connection and start the listener task."""
        uri = f"{self._ws_base}/api/campaigns/{campaign_id}/ws"
        try:
            ws = await websockets.connect(uri)
        except Exception as exc:
            logger.error(
                "Failed to open WebSocket for campaign %s (channel %d): %s",
                campaign_id,
                channel_id,
                exc,
            )
            return

        task = asyncio.create_task(
            self._listen(channel_id, campaign_id),
            name=f"ws-listener-{channel_id}",
        )
        conn = WebSocketConnection(
            campaign_id=campaign_id,
            channel_id=channel_id,
            ws=ws,
            task=task,
        )
        self._connections[channel_id] = conn
        logger.info("WebSocket connected for campaign %s (channel %d).", campaign_id, channel_id)

    # ------------------------------------------------------------------
    # Internal: close
    # ------------------------------------------------------------------

    async def _close(self, channel_id: int) -> None:
        """Cancel the listener task and close the WebSocket (idempotent)."""
        conn = self._connections.pop(channel_id, None)
        if conn is None:
            return

        conn.task.cancel()
        try:
            await conn.task
        except (asyncio.CancelledError, Exception):
            pass

        try:
            await conn.ws.close()
        except Exception:
            pass

        logger.info(
            "WebSocket closed for campaign %s (channel %d).",
            conn.campaign_id,
            channel_id,
        )

    # ------------------------------------------------------------------
    # Internal: listener loop
    # ------------------------------------------------------------------

    async def _listen(self, channel_id: int, campaign_id: str) -> None:
        """Receive WebSocket messages and dispatch them as custom bot events.

        Runs until the task is cancelled or the connection is removed from
        self._connections.
        """
        while True:
            conn = self._connections.get(channel_id)
            if conn is None:
                # Session was stopped — exit cleanly.
                return

            try:
                raw = await conn.ws.recv()
            except asyncio.CancelledError:
                return
            except websockets.exceptions.ConnectionClosed:
                logger.warning(
                    "WebSocket closed unexpectedly for campaign %s (channel %d).",
                    campaign_id,
                    channel_id,
                )
                await self._reconnect(channel_id, campaign_id)
                return  # _reconnect starts a new _listen task on success

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON WebSocket message: %r", raw)
                continue

            event_type: str = event.get("event", "")
            payload: dict = event.get("payload", {})

            # Track sequence number if present.
            seq = payload.get("sequence")
            if isinstance(seq, int):
                conn.last_sequence_number = seq

            # Inject channel_id for downstream routing.
            payload["_channel_id"] = channel_id

            custom_event = _DISPATCH_MAP.get(event_type)
            if custom_event:
                self.bot.dispatch(custom_event, payload)
            else:
                logger.debug("Unhandled WebSocket event type: %s", event_type)

    # ------------------------------------------------------------------
    # Internal: reconnect with exponential backoff
    # ------------------------------------------------------------------

    async def _reconnect(self, channel_id: int, campaign_id: str) -> None:
        """Attempt to reconnect with exponential backoff.

        If the first retry delay is ≥ _WARN_AFTER_SECONDS, posts a warning
        in the campaign channel.  Posts a success message on reconnect.
        """
        conn = self._connections.get(channel_id)
        if conn is None:
            # Session was stopped while we were trying to reconnect.
            return

        attempt = conn.reconnect_attempts
        delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]

        logger.info(
            "Reconnecting campaign %s in %ds (attempt %d).",
            campaign_id,
            delay,
            attempt + 1,
        )

        already_warned = conn._warned_disconnect
        if delay >= _WARN_AFTER_SECONDS and not already_warned:
            conn._warned_disconnect = True
            await self._post_in_channel(channel_id, "⚠️ Reconnecting to the game server...")

        await asyncio.sleep(delay)

        # Re-check: session may have been stopped during the sleep.
        if channel_id not in self._connections:
            return

        uri = f"{self._ws_base}/api/campaigns/{campaign_id}/ws"
        try:
            new_ws = await websockets.connect(uri)
        except Exception as exc:
            logger.warning(
                "Reconnect attempt %d failed for campaign %s: %s",
                attempt + 1,
                campaign_id,
                exc,
            )
            # Update attempt count on the (possibly refreshed) connection.
            conn = self._connections.get(channel_id)
            if conn is not None:
                conn.reconnect_attempts = attempt + 1
            await self._reconnect(channel_id, campaign_id)
            return

        # Reconnect succeeded — update connection state.
        conn = self._connections.get(channel_id)
        if conn is None:
            # Stopped while we were connecting.
            await new_ws.close()
            return

        posted_warning = conn._warned_disconnect
        old_ws = conn.ws
        conn.ws = new_ws
        conn.reconnect_attempts = 0
        conn._warned_disconnect = False

        try:
            await old_ws.close()
        except Exception:
            pass

        # Fetch current campaign state to recover missed events.
        try:
            await self.api.get_campaign(campaign_id)
        except TavernAPIError as exc:
            logger.warning(
                "Could not fetch campaign state after reconnect (campaign %s): %s",
                campaign_id,
                exc,
            )

        if posted_warning:
            await self._post_in_channel(channel_id, "✅ Reconnected.")

        logger.info(
            "WebSocket reconnected for campaign %s (channel %d).",
            campaign_id,
            channel_id,
        )

        # Restart the listener task.
        new_task = asyncio.create_task(
            self._listen(channel_id, campaign_id),
            name=f"ws-listener-{channel_id}",
        )
        conn.task = new_task

    # ------------------------------------------------------------------
    # Internal: post a plain message in a channel
    # ------------------------------------------------------------------

    async def _post_in_channel(self, channel_id: int, content: str) -> None:
        """Fetch the Discord channel and post a plain text message."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                return

        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(content)
            except discord.Forbidden:
                logger.warning("No permission to post in channel %d.", channel_id)
