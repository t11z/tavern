"""Turn observability layer — ADR-0018.

Provides dataclasses and an accumulator for recording pipeline telemetry
during a single Turn's execution. All types are serialisable to plain dicts
for JSONB persistence.

No imports from dm/ or api/ — stdlib only.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any


@dataclasses.dataclass
class PipelineStep:
    step: str  # Machine-readable step identifier
    started_at: datetime  # UTC
    duration_ms: int
    input_summary: dict  # type: ignore[type-arg]  # Summarised inputs (not full payloads)
    output_summary: dict  # type: ignore[type-arg]  # Summarised outputs (not full payloads)
    decision: str | None  # Human-readable one-line summary


@dataclasses.dataclass
class LLMCallRecord:
    call_type: str  # "narration", "classification", "summary_compression"
    model_id: str  # e.g. "claude-sonnet-4-20250514"
    model_tier: str  # "high" or "low"
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    latency_ms: int
    stream_first_token_ms: int | None
    estimated_cost_usd: float
    success: bool
    error: str | None


@dataclasses.dataclass
class TurnEventLog:
    turn_id: str  # FK to Turn (str UUID)
    pipeline_started_at: datetime
    pipeline_finished_at: datetime
    steps: list[PipelineStep]
    llm_calls: list[LLMCallRecord]
    warnings: list[str]
    errors: list[str]


def turn_event_log_to_dict(log: TurnEventLog) -> dict[str, Any]:
    """Serialise a TurnEventLog to a plain dict suitable for JSONB persistence.

    Converts all datetime objects to ISO-format strings.
    """
    raw = dataclasses.asdict(log)

    def _convert(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(item) for item in obj]
        return obj

    return _convert(raw)


class TurnEventLogAccumulator:
    """Mutable accumulator for pipeline telemetry during a single Turn.

    Usage::

        acc = TurnEventLogAccumulator(turn_id=str(turn.id))
        acc.add_step(step)
        acc.add_llm_call(record)
        log = acc.finalize()
        turn.event_log = turn_event_log_to_dict(log)
    """

    def __init__(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._pipeline_started_at: datetime = datetime.now(UTC)
        self._steps: list[PipelineStep] = []
        self._llm_calls: list[LLMCallRecord] = []
        self._warnings: list[str] = []
        self._errors: list[str] = []

    def add_step(self, step: PipelineStep) -> None:
        self._steps.append(step)

    def add_llm_call(self, record: LLMCallRecord) -> None:
        self._llm_calls.append(record)

    def add_warning(self, message: str) -> None:
        self._warnings.append(message)

    def add_error(self, message: str) -> None:
        self._errors.append(message)

    def finalize(self) -> TurnEventLog:
        """Record pipeline_finished_at and return the completed TurnEventLog."""
        return TurnEventLog(
            turn_id=self._turn_id,
            pipeline_started_at=self._pipeline_started_at,
            pipeline_finished_at=datetime.now(UTC),
            steps=list(self._steps),
            llm_calls=list(self._llm_calls),
            warnings=list(self._warnings),
            errors=list(self._errors),
        )
