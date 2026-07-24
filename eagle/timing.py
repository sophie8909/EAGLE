"""Canonical timing records for EAGLE runs.

This module owns wall-clock event timestamps, monotonic durations, and the
append-only run timing stream. Evolutionary operators and GUI analysis consume
these records; neither layer recomputes request durations independently.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Stopwatch:
    """One monotonic span with human-readable UTC boundaries."""

    started_at: str
    _started: float

    @classmethod
    def start(cls) -> "Stopwatch":
        return cls(utc_now(), time.monotonic())

    def finish(self, *, status: str = "success", error: str | None = None) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "duration_seconds": round(max(0.0, time.monotonic() - self._started), 9),
            "status": status,
            "error": error,
        }


def duration(value: object) -> float:
    if isinstance(value, dict):
        value = value.get("duration_seconds")
    return float(value) if isinstance(value, (int, float)) else 0.0


def append_event(path: Path, event: dict[str, Any]) -> None:
    """Append one structured timing event without changing runtime decisions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def operation_timing(candidate_timing: dict[str, Any], operation: str) -> dict[str, Any]:
    payload = candidate_timing.get(operation)
    return payload if isinstance(payload, dict) else {}


def build_generation_event(
    *,
    run_id: str,
    generation: int,
    candidates: Iterable[Any],
    span: dict[str, Any],
) -> dict[str, Any]:
    values = list(candidates)
    mutation = [operation_timing(item.timing, "mutation") for item in values]
    crossover = [operation_timing(item.timing, "crossover") for item in values]
    request_total = sum(
        duration(item.timing.get("generation_llm"))
        + duration(item.timing.get("reflection_llm"))
        + duration(item.timing.get("rewrite_llm"))
        + duration(item.timing.get("strategy_alignment_llm"))
        for item in values
    )
    return {
        "event": "generation",
        "run_id": run_id,
        "generation": generation,
        "started_at": span.get("started_at"),
        "finished_at": span.get("finished_at"),
        "duration_seconds": span.get("duration_seconds"),
        "mutation_count": sum(bool(item) for item in mutation),
        "crossover_count": sum(bool(item) for item in crossover),
        "aggregate_mutation_duration_seconds": sum(duration(item.get("generation_only_duration_seconds")) for item in mutation),
        "aggregate_crossover_duration_seconds": sum(duration(item.get("generation_only_duration_seconds")) for item in crossover),
        "aggregate_llm_request_duration_seconds": request_total,
        "aggregate_validation_duration_seconds": sum(duration(item.timing.get("validation")) for item in values),
        "aggregate_compilation_duration_seconds": sum(duration(item.timing.get("compilation")) for item in values),
        "aggregate_evaluation_duration_seconds": sum(duration(item.timing.get("evaluation")) for item in values),
    }
