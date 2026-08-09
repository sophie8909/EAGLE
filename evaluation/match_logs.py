"""Temporary, streamed MicroRTS match logs used by Match Commentator.

The evaluator owns game-performance scoring.  This module only turns the
engine's existing round-state files into a stable, compressed evidence stream.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

from .game_performance import parse_round_state


MATCH_LOG_SCHEMA_VERSION = "eagle-match-log-v1"


def write_match_log(
    path: Path,
    *,
    metadata: dict[str, Any],
    round_state_dir: Path,
    raw_result: dict[str, Any],
    tick_limit: int,
) -> int:
    """Stream one deterministic JSON record per available engine tick.

    Round-state files are read one at a time and are never collected into a
    list.  If MicroRTS did not emit a round-state file, the final result is the
    only state the engine exposed and is recorded as a fallback tick.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as output:
        for state_path in sorted(round_state_dir.glob("round_*.log")):
            raw_state = state_path.read_text(encoding="utf-8", errors="replace")
            record = _round_state_record(metadata, raw_state, state_path)
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            output.write("\n")
            count += 1
        if count == 0:
            fallback_tick = int(raw_result.get("final_tick") or tick_limit)
            record = {
                "schema_version": MATCH_LOG_SCHEMA_VERSION,
                "metadata": dict(metadata),
                "tick": fallback_tick,
                "players": _result_players(raw_result),
                "units": [],
                "raw_state": None,
                "state_source": "result_json_fallback",
            }
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            output.write("\n")
            count = 1
    return count


def iter_match_log(path: Path) -> Iterator[dict[str, Any]]:
    """Yield match-log records in file order without loading the trace."""

    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def read_match_log_chunks(path: Path, *, max_chars: int) -> Iterator[list[dict[str, Any]]]:
    """Group complete tick records into bounded, non-overlapping chunks."""

    if max_chars < 256:
        raise ValueError("max_chars must be at least 256")
    chunk: list[dict[str, Any]] = []
    size = 2
    for record in iter_match_log(path):
        encoded_size = len(json.dumps(record, ensure_ascii=False, sort_keys=True)) + 1
        if chunk and size + encoded_size > max_chars:
            yield chunk
            chunk = []
            size = 2
        chunk.append(record)
        size += encoded_size
    if chunk:
        yield chunk


def delete_match_log(path: Path | None) -> None:
    """Delete only the intentional temporary compressed trace."""

    if path is not None:
        path.unlink(missing_ok=True)


def _round_state_record(metadata: dict[str, Any], raw_state: str, state_path: Path) -> dict[str, Any]:
    tick_data = parse_round_state(raw_state, player_index=0, scoring_config=_default_scoring_config())
    units = _parse_units(raw_state)
    return {
        "schema_version": MATCH_LOG_SCHEMA_VERSION,
        "metadata": dict(metadata),
        "tick": tick_data.tick,
        "players": [
            {"player_id": "p0", "resources": tick_data.player_resource},
            {"player_id": "p1", "resources": tick_data.enemy_resource},
        ],
        "units": units,
        "state_source": str(state_path.name),
        "raw_state": raw_state,
    }


def _parse_units(raw_state: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for ordinal, line in enumerate(raw_state.splitlines()):
        match = re.search(
            r"\((\d+),(\d+)\)\s+(Ally|Enemy)\s+(.+?)\s+Unit\s+\{([^}]*)\}",
            line,
        )
        if not match:
            continue
        fields = match.group(5)
        units.append(
            {
                "unit_id": _field(fields, "ID"),
                "owner": "p0" if match.group(3) == "Ally" else "p1",
                "unit_type": match.group(4).strip(),
                "x": int(match.group(1)),
                "y": int(match.group(2)),
                "hit_points": _number(_field(fields, "HP")),
                "carried_resources": _number(_field(fields, "resources")),
                "current_action": _field(fields, "action"),
                "action_target": _field(fields, "target"),
                "state_ordinal": ordinal,
            }
        )
    return sorted(units, key=lambda item: (str(item["owner"]), str(item["unit_type"]), item["x"], item["y"], item["state_ordinal"]))


def _result_players(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    players = raw_result.get("players") or {}
    return [
        {"player_id": "p0", "resources": (players.get("p0") or {}).get("resource_total")},
        {"player_id": "p1", "resources": (players.get("p1") or {}).get("resource_total")},
    ]


def _field(fields: str, name: str) -> Any:
    match = re.search(rf"(?:^|,\s*){re.escape(name)}=([^,]+)", fields, re.IGNORECASE)
    return None if match is None else match.group(1).strip()


def _number(value: Any) -> Any:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number


def _default_scoring_config():
    from .game_performance import GamePerformanceConfig

    return GamePerformanceConfig()
