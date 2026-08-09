"""Lossless, streamed match-state artifacts for MicroRTS matches.

The Java runner owns the observation point.  This module owns conversion of the
per-tick round-state files into the durable trace artifact consumed by the
commentator.  It deliberately does not participate in scoring.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


TRACE_SCHEMA_VERSION = "match-trace-v1"


@dataclass(frozen=True)
class TraceArtifact:
    metadata_path: Path
    trace_path: Path
    integrity_path: Path
    result_path: Path
    integrity: dict[str, Any]


def write_match_trace(
    *,
    round_state_dir: Path,
    match_dir: Path,
    metadata: dict[str, Any],
    result: dict[str, Any],
    expected_last_tick: int | None = None,
) -> TraceArtifact:
    """Stream round-state observations into the canonical match artifacts.

    Round-state files are already emitted by the Java game loop one per cycle.
    Reading them in filename order keeps memory bounded and makes the integrity
    report expose any missing quiet ticks instead of silently filling them.
    """

    match_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = match_dir / "match_metadata.json"
    trace_path = match_dir / "match_trace.jsonl.gz"
    integrity_path = match_dir / "match_trace_integrity.json"
    result_path = match_dir / "match_result.json"

    static = {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "start_timestamp": metadata.get("start_timestamp") or _utc_now(),
        **metadata,
    }
    for field in (
        "match_id", "candidate_id", "candidate_side", "opponent_name", "opponent_agent",
        "map_name", "map_width", "map_height", "terrain", "round_index", "generation_index", "seed",
        "evaluation_configuration",
    ):
        static.setdefault(field, None)
    _write_json(result_path, result)

    ticks: list[int] = []
    write_error: str | None = None
    try:
        with gzip.open(trace_path, "wt", encoding="utf-8", newline="\n") as handle:
            for path in sorted(round_state_dir.glob("round_*.log")):
                row = _parse_round_state(path.read_text(encoding="utf-8"))
                if row is None:
                    continue
                final_tick = result.get("final_tick")
                if isinstance(final_tick, (int, float)) and int(final_tick) == int(row["tick"]):
                    row["terminal"] = True
                    row["winner"] = result.get("winner")
                if static.get("map_width") is None and row.get("map_width") is not None:
                    static["map_width"] = row["map_width"]
                    static["map_height"] = row.get("map_height")
                ticks.append(int(row["tick"]))
                row.pop("map_width", None)
                row.pop("map_height", None)
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        write_error = str(exc) or type(exc).__name__
    _write_json(metadata_path, static)

    first_tick = min(ticks) if ticks else None
    last_tick = max(ticks) if ticks else None
    expected_last = expected_last_tick if expected_last_tick is not None else last_tick
    expected_count = None if first_tick is None or expected_last is None else max(0, expected_last - first_tick + 1)
    counts: dict[int, int] = {}
    for tick in ticks:
        counts[tick] = counts.get(tick, 0) + 1
    duplicate_ticks = sorted(tick for tick, count in counts.items() if count > 1)
    missing_ticks = [] if first_tick is None or expected_last is None else [
        tick for tick in range(first_tick, expected_last + 1) if counts.get(tick, 0) == 0
    ]
    out_of_order = [
        {"previous": previous, "current": current}
        for previous, current in zip(ticks, ticks[1:])
        if current < previous
    ]
    integrity = {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "first_tick": first_tick,
        "last_tick": last_tick,
        "recorded_tick_count": len(ticks),
        "expected_tick_count": expected_count,
        "complete": bool(
            write_error is None
            and expected_count is not None
            and len(ticks) == expected_count
            and not duplicate_ticks
            and not missing_ticks
            and not out_of_order
        ),
        "missing_tick_ranges": _ranges(missing_ticks),
        "duplicate_ticks": duplicate_ticks,
        "out_of_order_ticks": out_of_order,
        "trace_write_failure": write_error,
    }
    _write_json(integrity_path, integrity)
    return TraceArtifact(metadata_path, trace_path, integrity_path, result_path, integrity)


def iter_match_trace(path: Path) -> Iterator[dict[str, Any]]:
    """Lazily yield trace rows without loading the compressed trace in memory."""

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("match trace rows must be JSON objects")
                yield value


def _parse_round_state(text: str) -> dict[str, Any] | None:
    tick_match = re.search(r"(?:ROUND_TICK:\s*|current time\s+)(\d+)", text)
    if tick_match is None:
        return None
    tick = int(tick_match.group(1))
    resources = _resources(text)
    terminal_match = re.search(r"GAMEOVER:\s*(true|false)", text, re.IGNORECASE)
    terminal = bool(terminal_match and terminal_match.group(1).lower() == "true")
    map_match = re.search(r"Map size:\s*(\d+)x(\d+)", text)
    units: list[dict[str, Any]] = []
    for match in re.finditer(
        r"\((\d+),(\d+)\)\s+(Ally|Enemy)\s+(.+?)\s+Unit\s*\{([^}]*)\}",
        text,
    ):
        x, y = int(match.group(1)), int(match.group(2))
        owner_name, label, details = match.group(3), match.group(4).strip(), match.group(5)
        unit_type = label.removesuffix(" Unit").strip()
        owner = 0 if owner_name == "Ally" else 1
        fields = _detail_fields(details)
        units.append({
            "unit_id": fields.pop("unit_id", None),
            "owner": owner,
            "unit_type": unit_type,
            "x": x,
            "y": y,
            "hit_points": fields.pop("hit_points", None),
            "maximum_hit_points": fields.pop("maximum_hit_points", None),
            "carried_resources": fields.pop("carried_resources", None),
            "current_action": fields.pop("current_action", None),
            "action_target": fields.pop("action_target", None),
            "action_remaining_time": fields.pop("action_remaining_time", None),
        })
    units.sort(key=lambda item: (
        item["owner"], item["unit_type"], item["unit_id"] is None,
        str(item["unit_id"]), item["x"], item["y"],
    ))
    players = [_player_snapshot(0, resources[0], units), _player_snapshot(1, resources[1], units)]
    return {
        "tick": tick,
        "game_time": tick,
        "terminal": terminal,
        "winner": None,
        "players": players,
        "units": units,
        "map_width": None if map_match is None else int(map_match.group(1)),
        "map_height": None if map_match is None else int(map_match.group(2)),
    }


def _resources(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        r"p0 player 0\(([-+]?\d+(?:\.\d+)?)\).*?p1 player 1\(([-+]?\d+(?:\.\d+)?)\)",
        text,
    )
    return (None, None) if match is None else (float(match.group(1)), float(match.group(2)))


def _detail_fields(details: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    patterns = {
        "unit_id": r"(?:ID|id)\s*=\s*([\w.-]+)",
        "hit_points": r"(?:HP|hp)\s*=\s*(-?\d+)",
        "maximum_hit_points": r"(?:MaxHP|max_hp|maximum_hit_points)\s*=\s*(-?\d+)",
        "carried_resources": r"(?:resources|carried_resources)\s*=\s*(-?\d+(?:\.\d+)?)",
        "current_action": r"(?:action|current_action)\s*=\s*([\w.-]+)",
        "action_target": r"(?:target|action_target)\s*=\s*([^,}]+)",
        "action_remaining_time": r"(?:eta|action_remaining_time)\s*=\s*(-?\d+)",
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, details)
        if match is None:
            continue
        value: Any = match.group(1).strip()
        if name in {"hit_points", "maximum_hit_points", "action_remaining_time"}:
            value = int(value)
        elif name == "carried_resources":
            value = float(value)
        result[name] = value
    return result


def _player_snapshot(player_id: int, resources: float | None, units: list[dict[str, Any]]) -> dict[str, Any]:
    owned = [item for item in units if item["owner"] == player_id]
    counts: dict[str, int] = {}
    for unit in owned:
        counts[unit["unit_type"]] = counts.get(unit["unit_type"], 0) + 1
    return {
        "player_id": player_id,
        "resources": resources,
        "unit_count": len(owned),
        "worker_count": counts.get("Worker", 0),
        "combat_unit_count": sum(counts.get(name, 0) for name in ("Light", "Heavy", "Ranged")),
        "building_count": sum(counts.get(name, 0) for name in ("Base", "Barracks")),
        "base_count": counts.get("Base", 0),
        "barracks_count": counts.get("Barracks", 0),
        "unit_types": dict(sorted(counts.items())),
    }


def _ranges(values: Iterable[int]) -> list[dict[str, int]]:
    ordered = sorted(set(values))
    if not ordered:
        return []
    result: list[dict[str, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + 1:
            result.append({"start": start, "end": previous})
            start = value
        previous = value
    result.append({"start": start, "end": previous})
    return result


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
