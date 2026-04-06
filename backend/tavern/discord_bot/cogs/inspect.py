"""
InspectCog — /inspect command group for ADR-0018 Turn Observability.

Provides the campaign host with a Discord interface to the turn event log
and session telemetry. All responses are ephemeral.

Commands:
    /inspect turn <number>    — Pipeline steps + LLM call details for a turn
    /inspect session          — Session-level telemetry aggregate
    /inspect cost             — Session cost shortcut
"""

from __future__ import annotations

import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from ..models.state import BotState, ChannelBinding
from ..services.api_client import TavernAPI, TavernAPIError
from ..services.channel_manager import ChannelManager

logger = logging.getLogger(__name__)

TAVERN_AMBER = discord.Colour(0xD4A24E)

# Discord embed character limit.
_EMBED_LIMIT = 6000
# Field value truncation marker.
_TRUNCATE_SUFFIX = "\n…"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step_name(raw: str) -> str:
    """Format a snake_case step name as Title Case.

    Example: ``"action_analysis"`` → ``"Action Analysis"``
    """
    return raw.replace("_", " ").title()


def _pipeline_duration_ms(event_log: dict) -> int | None:
    """Compute pipeline wall-clock duration from ISO timestamps in the event log."""
    started = event_log.get("pipeline_started_at")
    finished = event_log.get("pipeline_finished_at")
    if not started or not finished:
        return None
    try:
        s = datetime.fromisoformat(started)
        f = datetime.fromisoformat(finished)
        return int((f - s).total_seconds() * 1000)
    except Exception:
        return None


def _total_cost(event_log: dict) -> float:
    """Sum estimated_cost_usd across all llm_calls in the event log."""
    return sum(call.get("estimated_cost_usd", 0.0) for call in event_log.get("llm_calls", []))


def _cache_pct(call: dict) -> int:
    """Return cache_read_tokens as a percentage of input_tokens, rounded."""
    input_tokens = call.get("input_tokens", 0)
    cache_tokens = call.get("cache_read_tokens", 0)
    return round(cache_tokens / max(input_tokens, 1) * 100)


def _truncate(text: str, limit: int) -> str:
    """Truncate text to ``limit`` characters, appending '…' if cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _build_turn_embed(
    seq: int,
    event_log: dict,
    character_name: str | None,
) -> discord.Embed:
    """Build the /inspect turn embed from an event_log dict."""
    dur = _pipeline_duration_ms(event_log)
    cost = _total_cost(event_log)

    char_label = character_name or "Unknown"
    dur_label = f"{dur:,}ms" if dur is not None else "—"

    embed = discord.Embed(
        title=f"Turn {seq} — {char_label}",
        description=f"Pipeline: {dur_label} | Cost: ${cost:.4f}",
        colour=TAVERN_AMBER,
    )

    # --- Pipeline Steps ---
    steps: list[dict] = event_log.get("steps", [])
    if steps:
        lines: list[str] = []
        for step in steps:
            name = _step_name(step.get("step", "?"))
            step_dur = step.get("duration_ms")
            dur_part = f" ({step_dur}ms)" if step_dur is not None else ""
            decision = step.get("decision")
            decision_part = f" → {decision}" if decision else ""
            lines.append(f"  {name}{dur_part}{decision_part}")
        field_value = _truncate("\n".join(lines), 1000)
        embed.add_field(name="Pipeline Steps", value=field_value, inline=False)
    else:
        embed.add_field(name="Pipeline Steps", value="  (none recorded)", inline=False)

    # --- LLM Calls ---
    llm_calls: list[dict] = event_log.get("llm_calls", [])
    if llm_calls:
        lines = []
        for call in llm_calls:
            call_type = call.get("call_type", "?")
            tier = call.get("model_tier", "?")
            input_tok = call.get("input_tokens", 0)
            output_tok = call.get("output_tokens", 0)
            cache = _cache_pct(call)
            c = call.get("estimated_cost_usd", 0.0)
            latency = call.get("latency_ms")
            latency_part = f" | {latency}ms" if latency is not None else ""
            lines.append(
                f"  {call_type}: {tier} | {input_tok}→{output_tok}"
                f" | {cache}% cache | ${c:.4f}{latency_part}"
            )
        field_value = _truncate("\n".join(lines), 1000)
        embed.add_field(name="LLM Calls", value=field_value, inline=False)
    else:
        embed.add_field(name="LLM Calls", value="  (none recorded)", inline=False)

    # --- Warnings ---
    warnings: list[str] = event_log.get("warnings", [])
    warn_text = ", ".join(warnings) if warnings else "none"
    embed.add_field(name="Warnings", value=_truncate(warn_text, 500), inline=False)

    return embed


def _build_session_embed(campaign_name: str, telemetry: dict) -> discord.Embed:
    """Build the /inspect session embed from a telemetry dict."""
    total_cost = telemetry.get("total_cost_usd", 0.0)
    total_in = telemetry.get("total_input_tokens", 0)
    total_out = telemetry.get("total_output_tokens", 0)
    turns = telemetry.get("turns_processed", 0)
    avg_narration = telemetry.get("avg_narration_latency_ms", 0)
    avg_pipeline = telemetry.get("avg_pipeline_duration_ms", 0)
    cache_rate = telemetry.get("cache_hit_rate", 0.0)
    model_dist: dict[str, int] = telemetry.get("model_tier_distribution", {})
    classifier_inv = telemetry.get("classifier_invocations", 0)
    classifier_low = telemetry.get("classifier_low_confidence_count", 0)
    gm_failures = telemetry.get("gm_signals_parse_failures", 0)

    model_str = (
        " | ".join(f"{tier}: {count}" for tier, count in sorted(model_dist.items()))
        if model_dist
        else "—"
    )

    embed = discord.Embed(
        title=f"Session Telemetry — {campaign_name}",
        colour=TAVERN_AMBER,
    )
    embed.add_field(
        name="Cost & Tokens",
        value=f"${total_cost:.4f} | {total_in:,} in / {total_out:,} out",
        inline=False,
    )
    embed.add_field(name="Turns Processed", value=str(turns), inline=True)
    embed.add_field(
        name="Avg Latency",
        value=f"Narration: {avg_narration:,.0f}ms | Pipeline: {avg_pipeline:,.0f}ms",
        inline=False,
    )
    embed.add_field(name="Cache Hit Rate", value=f"{cache_rate:.0%}", inline=True)
    embed.add_field(name="Model Split", value=model_str, inline=False)
    embed.add_field(
        name="Classifier",
        value=f"{classifier_inv} invocations, {classifier_low} low-confidence",
        inline=False,
    )
    embed.add_field(name="GM Signals Parse Failures", value=str(gm_failures), inline=True)
    return embed


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class InspectCog(commands.Cog):
    """All /inspect subcommands — ADR-0018 Turn Observability."""

    def __init__(
        self,
        bot: commands.Bot,
        api: TavernAPI,
        channel_manager: ChannelManager,
        state: BotState,
    ) -> None:
        self.bot = bot
        self.api = api
        self.channel_manager = channel_manager
        self.state = state

    # ------------------------------------------------------------------
    # Shared helpers  (mirrors CampaignCog pattern exactly)
    # ------------------------------------------------------------------

    async def _require_binding(self, interaction: discord.Interaction) -> ChannelBinding | None:
        """Return the channel's campaign binding or send an ephemeral error."""
        binding = self.state.get_binding(interaction.channel_id)  # type: ignore[arg-type]
        if binding is None:
            await interaction.response.send_message(
                "No campaign in this channel. Use `/lfg` to start one.",
                ephemeral=True,
            )
        return binding

    async def is_owner(self, interaction: discord.Interaction, campaign_id: str) -> bool:
        """Return True if the invoking user is the campaign owner.

        Auth is not yet implemented (ADR-0006 known deviation — Phase 6).
        Returns True for all users until the membership endpoint is available.
        """
        # TODO: enforce campaign ownership when ADR-0006 auth is implemented
        # TODO(auth): call GET /api/campaigns/{id}/members and check role == "owner"
        return True

    async def _require_owner(self, interaction: discord.Interaction, campaign_id: str) -> bool:
        """Check ownership and send an ephemeral error if not owner. Returns True if owner."""
        if not await self.is_owner(interaction, campaign_id):
            await interaction.response.send_message(
                "Only the campaign owner can do that.", ephemeral=True
            )
            return False
        return True

    async def _require_active_session(
        self, interaction: discord.Interaction, campaign_id: str
    ) -> str | None:
        """Fetch the active session ID, or send an ephemeral error and return None."""
        try:
            data = await self.api.get_active_session(campaign_id)
            return str(data["session_id"])
        except TavernAPIError as exc:
            if exc.status_code == 404:
                await interaction.followup.send(
                    "No active session — start one with `/tavern start`.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"❌ Could not fetch session: {exc.message}", ephemeral=True
                )
            return None

    # ------------------------------------------------------------------
    # /inspect group
    # ------------------------------------------------------------------

    inspect_group = app_commands.Group(
        name="inspect",
        description="Inspect turn diagnostics and session telemetry (host only).",
    )

    # ------------------------------------------------------------------
    # /inspect turn <number>
    # ------------------------------------------------------------------

    @inspect_group.command(name="turn", description="Inspect a specific turn's pipeline.")
    @app_commands.describe(number="Turn sequence number")
    async def inspect_turn(self, interaction: discord.Interaction, number: int) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)

        if not await self._require_owner(interaction, campaign_id):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        # Find the turn by sequence_number — list up to 100 turns and search.
        try:
            turns = await self.api.list_turns(campaign_id, limit=100)
        except TavernAPIError:
            await interaction.followup.send(
                "Failed to fetch turn data. Is the API running?", ephemeral=True
            )
            return

        turn_item = next((t for t in turns if t.get("sequence_number") == number), None)
        if turn_item is None:
            await interaction.followup.send(f"Turn {number} not found.", ephemeral=True)
            return

        turn_id: str = str(turn_item.get("turn_id") or turn_item.get("id", ""))

        # Fetch the event log for this specific turn.
        try:
            log_data = await self.api.get_turn_event_log(campaign_id, turn_id)
        except TavernAPIError as exc:
            if exc.status_code == 404:
                await interaction.followup.send(
                    f"No diagnostic data available for turn {number} (pre-observability turn).",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "Failed to fetch turn data. Is the API running?", ephemeral=True
                )
            return

        event_log: dict | None = log_data.get("event_log")
        if not event_log:
            await interaction.followup.send(
                f"No diagnostic data available for turn {number} (pre-observability turn).",
                ephemeral=True,
            )
            return

        character_name: str | None = (
            turn_item.get("character_name") or str(turn_item.get("character_id", "")) or None
        )

        embed = _build_turn_embed(number, event_log, character_name)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /inspect session
    # ------------------------------------------------------------------

    @inspect_group.command(name="session", description="Session telemetry summary.")
    async def inspect_session(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)

        if not await self._require_owner(interaction, campaign_id):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        session_id = await self._require_active_session(interaction, campaign_id)
        if session_id is None:
            return

        # Fetch campaign name for embed title.
        campaign_name = "Campaign"
        try:
            campaign = await self.api.get_campaign(campaign_id)
            campaign_name = campaign.get("name", "Campaign")
        except TavernAPIError:
            pass

        try:
            telemetry = await self.api.get_session_telemetry(campaign_id, session_id)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not fetch telemetry: {exc.message}", ephemeral=True
            )
            return

        embed = _build_session_embed(campaign_name, telemetry)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /inspect cost
    # ------------------------------------------------------------------

    @inspect_group.command(name="cost", description="Session cost summary.")
    async def inspect_cost(self, interaction: discord.Interaction) -> None:
        binding = await self._require_binding(interaction)
        if binding is None:
            return

        campaign_id = str(binding.campaign_id)

        if not await self._require_owner(interaction, campaign_id):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        session_id = await self._require_active_session(interaction, campaign_id)
        if session_id is None:
            return

        try:
            telemetry = await self.api.get_session_telemetry(campaign_id, session_id)
        except TavernAPIError as exc:
            await interaction.followup.send(
                f"❌ Could not fetch telemetry: {exc.message}", ephemeral=True
            )
            return

        total_cost = telemetry.get("total_cost_usd", 0.0)
        turns = telemetry.get("turns_processed", 0)
        total_in = telemetry.get("total_input_tokens", 0)
        total_out = telemetry.get("total_output_tokens", 0)

        cost_per_turn = total_cost / max(turns, 1)

        lines = [
            f"**Session cost: ${total_cost:.4f}**",
            f"  {turns} turns | ~${cost_per_turn:.4f}/turn",
            f"  {total_in:,} input / {total_out:,} output tokens",
        ]

        await interaction.followup.send("\n".join(lines), ephemeral=True)
