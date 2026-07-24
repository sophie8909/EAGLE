"""Read and summarize persisted EAGLE timing artifacts for Analysis."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_timing_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "timing.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                events.append(payload)
    return events


def read_candidate_timings(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/timing.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            records.append({"candidate_id": path.parent.name, **payload})
    return records


def summarize_run_timing(run_dir: Path) -> dict[str, Any]:
    events = read_timing_events(run_dir)
    candidates = read_candidate_timings(run_dir)
    generations = [event for event in events if event.get("event") == "generation"]
    requests = [event for event in events if event.get("event") == "llm_request"]
    operations: list[dict[str, Any]] = []
    stage_totals: defaultdict[str, float] = defaultdict(float)
    for record in candidates:
        for name in ("mutation", "crossover", "child_generation", "validation", "compilation", "evaluation"):
            value = record.get(name)
            if isinstance(value, dict):
                seconds = _number(value.get("generation_only_duration_seconds", value.get("duration_seconds")))
                stage_totals[name] += seconds
                if name in {"mutation", "crossover", "child_generation"} and seconds:
                    operations.append({"candidate_id": record["candidate_id"], "operation": name, "duration_seconds": seconds, "status": value.get("status")})
    operations.sort(key=lambda item: item["duration_seconds"], reverse=True)
    return {
        "run_id": run_dir.name,
        "total_run_duration_seconds": sum(_number(event.get("duration_seconds")) for event in generations),
        "generations": generations,
        "operation_totals": dict(stage_totals),
        "operation_records": operations,
        "llm_requests": requests,
        "slowest_requests": sorted(requests, key=lambda item: _number(item.get("duration_seconds")), reverse=True)[:20],
    }


def plot_payloads(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    generations = summary.get("generations", [])
    return {
        "generation_duration": {
            "xAxis": {"type": "category", "data": [event.get("generation") for event in generations]},
            "yAxis": {"type": "value", "name": "seconds"},
            "series": [{"type": "line", "data": [_number(event.get("duration_seconds")) for event in generations], "name": "generation"}],
        },
        "operation_breakdown": {
            "xAxis": {"type": "category", "data": list(summary.get("operation_totals", {}))},
            "yAxis": {"type": "value", "name": "seconds"},
            "series": [{"type": "bar", "data": list(summary.get("operation_totals", {}).values()), "name": "duration"}],
        },
        "llm_by_stage": _grouped_bar(summary.get("llm_requests", []), "operation_stage"),
        "llm_by_model": _grouped_bar(summary.get("llm_requests", []), "model_id"),
    }


def _grouped_bar(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    totals: defaultdict[str, float] = defaultdict(float)
    for record in records:
        totals[str(record.get(key) or "unknown")] += _number(record.get("duration_seconds"))
    return {
        "xAxis": {"type": "category", "data": list(totals)},
        "yAxis": {"type": "value", "name": "seconds"},
        "series": [{"type": "bar", "data": list(totals.values()), "name": "duration"}],
    }


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
