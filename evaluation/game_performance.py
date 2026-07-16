"""Per-tick MicroRTS telemetry and game-performance scoring."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


RESULT_WIN_SCORE = 100.0
RESULT_DRAW_SCORE = 0.0
RESULT_LOSS_SCORE = -100.0

UNIT_COSTS = {
    "Resource": 0.0,
    "Base": 10.0,
    "Barracks": 5.0,
    "Worker": 1.0,
    "Light": 2.0,
    "Heavy": 4.0,
    "Ranged": 2.0,
}
BUILDING_TYPES = {"Base", "Barracks"}
COMBAT_TYPES = {"Worker", "Light", "Heavy", "Ranged"}


@dataclass(frozen=True)
class GamePerformanceConfig:
    result_win_score: float = RESULT_WIN_SCORE
    result_draw_score: float = RESULT_DRAW_SCORE
    result_loss_score: float = RESULT_LOSS_SCORE
    army_weight: float = 1.0
    building_weight: float = 1.0
    resource_weight: float = 1.0
    survival_weight: float = 200.0
    final_resource_weight: float = 1.0

    def to_json_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class MatchTickTelemetry:
    tick: int
    player_resource: float
    enemy_resource: float
    player_units_by_type: dict[str, int]
    enemy_units_by_type: dict[str, int]
    player_unit_count: int
    enemy_unit_count: int
    player_combat_value: float
    enemy_combat_value: float
    player_building_value: float
    enemy_building_value: float
    player_total_unit_value: float
    enemy_total_unit_value: float
    army_value_diff: float
    building_value_diff: float
    resource_diff: float
    state_score: float

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GamePerformanceBreakdown:
    result_score: float
    average_state_score: float
    survival_score: float
    final_resource_diff: float
    total_performance: float

    def to_json_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class MatchTelemetry:
    player_index: int
    opponent_index: int
    max_tick: int
    end_tick: int
    result: str
    ticks: list[MatchTickTelemetry]
    final_player_resource: float
    final_enemy_resource: float
    replay_path: str | None = None
    performance: GamePerformanceBreakdown | None = None
    scoring_config: GamePerformanceConfig = field(default_factory=GamePerformanceConfig)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "player_index": self.player_index,
            "opponent_index": self.opponent_index,
            "max_tick": self.max_tick,
            "end_tick": self.end_tick,
            "result": self.result,
            "ticks": [tick.to_json_dict() for tick in self.ticks],
            "final_player_resource": self.final_player_resource,
            "final_enemy_resource": self.final_enemy_resource,
            "replay_path": self.replay_path,
            "performance": None if self.performance is None else self.performance.to_json_dict(),
            "scoring_config": self.scoring_config.to_json_dict(),
        }


def build_match_telemetry(
    *,
    raw_result: dict[str, Any],
    round_state_dir: Path,
    max_tick: int,
    player_index: int = 0,
    opponent_index: int = 1,
    replay_path: str | None = None,
    scoring_config: GamePerformanceConfig | None = None,
) -> MatchTelemetry:
    scoring_config = scoring_config or GamePerformanceConfig()
    ticks = read_tick_telemetry(round_state_dir, player_index=player_index, scoring_config=scoring_config)
    end_tick = int_or_default(raw_result.get("final_tick", raw_result.get("ticks")), max_tick)
    result = str(raw_result.get("result") or result_from_winner(raw_result.get("winner"), raw_result.get("tick_timeout")))

    if not ticks:
        ticks = [tick_from_result(raw_result, tick=end_tick, player_index=player_index, scoring_config=scoring_config)]
    final_tick = ticks[-1]
    performance = compute_performance_breakdown(
        result=result,
        winner=raw_result.get("winner"),
        end_tick=end_tick,
        max_tick=max_tick,
        ticks=ticks,
        scoring_config=scoring_config,
        player_index=player_index,
    )
    return MatchTelemetry(
        player_index=player_index,
        opponent_index=opponent_index,
        max_tick=max_tick,
        end_tick=end_tick,
        result=result,
        ticks=ticks,
        final_player_resource=final_tick.player_resource,
        final_enemy_resource=final_tick.enemy_resource,
        replay_path=replay_path,
        performance=performance,
        scoring_config=scoring_config,
    )


def read_tick_telemetry(
    round_state_dir: Path,
    *,
    player_index: int,
    scoring_config: GamePerformanceConfig,
) -> list[MatchTickTelemetry]:
    ticks: dict[int, MatchTickTelemetry] = {}
    for path in sorted(round_state_dir.glob("round_*.log")):
        tick = parse_round_state(path.read_text(encoding="utf-8"), player_index=player_index, scoring_config=scoring_config)
        ticks[tick.tick] = tick
    return [ticks[key] for key in sorted(ticks)]


def parse_round_state(
    text: str,
    *,
    player_index: int,
    scoring_config: GamePerformanceConfig,
) -> MatchTickTelemetry:
    tick = 0
    p0_resource = 0.0
    p1_resource = 0.0
    p0_units: dict[str, int] = {}
    p1_units: dict[str, int] = {}
    header = re.search(r"current time\s+(\d+).*?p0 player 0\(([-\d.]+)\).*?p1 player 1\(([-\d.]+)\)", text)
    if header:
        tick = int(header.group(1))
        p0_resource = float(header.group(2))
        p1_resource = float(header.group(3))
    for line in text.splitlines():
        parsed = parse_unit_line(line)
        if parsed is None:
            continue
        owner, unit_type = parsed
        if owner == 0:
            p0_units[unit_type] = p0_units.get(unit_type, 0) + 1
        elif owner == 1:
            p1_units[unit_type] = p1_units.get(unit_type, 0) + 1

    if player_index == 0:
        return tick_telemetry(tick, p0_resource, p1_resource, p0_units, p1_units, scoring_config)
    return tick_telemetry(tick, p1_resource, p0_resource, p1_units, p0_units, scoring_config)


def parse_unit_line(line: str) -> tuple[int, str] | None:
    match = re.search(r"\)\s+(Ally|Enemy)\s+(.+?) Unit\s+\{", line)
    if not match:
        return None
    owner = 0 if match.group(1) == "Ally" else 1
    unit_type = match.group(2).strip()
    return owner, unit_type


def tick_telemetry(
    tick: int,
    player_resource: float,
    enemy_resource: float,
    player_units: dict[str, int],
    enemy_units: dict[str, int],
    scoring_config: GamePerformanceConfig,
) -> MatchTickTelemetry:
    player_combat = unit_value(player_units, COMBAT_TYPES)
    enemy_combat = unit_value(enemy_units, COMBAT_TYPES)
    player_building = unit_value(player_units, BUILDING_TYPES)
    enemy_building = unit_value(enemy_units, BUILDING_TYPES)
    player_total = unit_value(player_units, set(UNIT_COSTS))
    enemy_total = unit_value(enemy_units, set(UNIT_COSTS))
    army_diff = player_combat - enemy_combat
    building_diff = player_building - enemy_building
    resource_diff = player_resource - enemy_resource
    state_score = (
        scoring_config.army_weight * army_diff
        + scoring_config.building_weight * building_diff
        + scoring_config.resource_weight * resource_diff
    )
    return MatchTickTelemetry(
        tick=tick,
        player_resource=player_resource,
        enemy_resource=enemy_resource,
        player_units_by_type=dict(sorted(player_units.items())),
        enemy_units_by_type=dict(sorted(enemy_units.items())),
        player_unit_count=sum(player_units.values()),
        enemy_unit_count=sum(enemy_units.values()),
        player_combat_value=player_combat,
        enemy_combat_value=enemy_combat,
        player_building_value=player_building,
        enemy_building_value=enemy_building,
        player_total_unit_value=player_total,
        enemy_total_unit_value=enemy_total,
        army_value_diff=army_diff,
        building_value_diff=building_diff,
        resource_diff=resource_diff,
        state_score=state_score,
    )


def compute_performance_breakdown(
    *,
    result: str,
    winner: Any,
    end_tick: int,
    max_tick: int,
    ticks: list[MatchTickTelemetry],
    scoring_config: GamePerformanceConfig,
    player_index: int = 0,
) -> GamePerformanceBreakdown:
    result_score = score_result(result=result, winner=winner, player_index=player_index, scoring_config=scoring_config)
    average_state_score = sum(tick.state_score for tick in ticks) / len(ticks) if ticks else 0.0
    survival_ratio = end_tick / max(1, max_tick)
    survival_score = scoring_config.survival_weight * survival_ratio
    final_tick = ticks[-1] if ticks else None
    final_resource_diff = 0.0 if final_tick is None else scoring_config.final_resource_weight * final_tick.resource_diff
    total = result_score + average_state_score + survival_score + final_resource_diff
    return GamePerformanceBreakdown(
        result_score=result_score,
        average_state_score=average_state_score,
        survival_score=survival_score,
        final_resource_diff=final_resource_diff,
        total_performance=total,
    )


def score_result(
    *,
    result: str,
    winner: Any,
    player_index: int,
    scoring_config: GamePerformanceConfig,
) -> float:
    winner_int = int_or_none(winner)
    if winner_int == player_index:
        return scoring_config.result_win_score
    if winner_int in (0, 1):
        return scoring_config.result_loss_score
    return scoring_config.result_draw_score


def telemetry_summary(telemetry: MatchTelemetry, telemetry_path: str, summary_path: str) -> dict[str, Any]:
    performance = telemetry.performance or GamePerformanceBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)
    final_tick = telemetry.ticks[-1] if telemetry.ticks else None
    return {
        "result": telemetry.result,
        "end_tick": telemetry.end_tick,
        "max_tick": telemetry.max_tick,
        "result_score": performance.result_score,
        "average_state_score": performance.average_state_score,
        "survival_score": performance.survival_score,
        "final_resource_diff": performance.final_resource_diff,
        "performance": performance.total_performance,
        "replay_path": telemetry.replay_path,
        "telemetry_path": telemetry_path,
        "summary_path": summary_path,
        "final_player_resource": telemetry.final_player_resource,
        "final_enemy_resource": telemetry.final_enemy_resource,
        "final_player_units_by_type": {} if final_tick is None else final_tick.player_units_by_type,
        "final_enemy_units_by_type": {} if final_tick is None else final_tick.enemy_units_by_type,
    }


def telemetry_temporal_summary(telemetry: MatchTelemetry) -> dict[str, Any]:
    return {
        "army_value_diff": summarize_series([(tick.tick, tick.army_value_diff) for tick in telemetry.ticks]),
        "resource_diff": summarize_series([(tick.tick, tick.resource_diff) for tick in telemetry.ticks]),
    }


def summarize_series(values: list[tuple[int, float]]) -> dict[str, float | int | None]:
    if not values:
        return {"average": None, "minimum": None, "minimum_tick": None, "maximum": None, "maximum_tick": None}
    minimum = min(values, key=lambda item: item[1])
    maximum = max(values, key=lambda item: item[1])
    return {
        "average": sum(value for _, value in values) / len(values),
        "minimum": minimum[1],
        "minimum_tick": minimum[0],
        "maximum": maximum[1],
        "maximum_tick": maximum[0],
    }


def tick_from_result(
    raw_result: dict[str, Any],
    *,
    tick: int,
    player_index: int,
    scoring_config: GamePerformanceConfig,
) -> MatchTickTelemetry:
    players = raw_result.get("players") or {}
    p0 = players.get("p0") or {}
    p1 = players.get("p1") or {}
    p0_resource = float_or_default(p0.get("resource_total", p0.get("player_resources")), 0.0)
    p1_resource = float_or_default(p1.get("resource_total", p1.get("player_resources")), 0.0)
    p0_units = {str(key): int(value) for key, value in (p0.get("unit_types") or {}).items()}
    p1_units = {str(key): int(value) for key, value in (p1.get("unit_types") or {}).items()}
    if player_index == 0:
        return tick_telemetry(tick, p0_resource, p1_resource, p0_units, p1_units, scoring_config)
    return tick_telemetry(tick, p1_resource, p0_resource, p1_units, p0_units, scoring_config)


def write_telemetry_json(path: Path, telemetry: MatchTelemetry) -> None:
    path.write_text(json.dumps(telemetry.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def result_from_winner(winner: Any, tick_timeout: Any) -> str:
    winner_int = int_or_none(winner)
    if winner_int == 0:
        return "p0_win"
    if winner_int == 1:
        return "p1_win"
    return "timeout_draw" if bool(tick_timeout) else "draw"


def unit_value(units_by_type: dict[str, int], included_types: set[str]) -> float:
    return sum(UNIT_COSTS.get(unit_type, 0.0) * count for unit_type, count in units_by_type.items() if unit_type in included_types)


def float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def int_or_default(value: Any, default: int) -> int:
    parsed = int_or_none(value)
    return default if parsed is None else parsed


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

# Phase 4 replaces the legacy unbounded scorer above while preserving this
# public module path for callers and historical artifact readers.
from .canonical_game_performance import *  # noqa: E402,F401,F403
from .canonical_game_performance import DEFAULT_UNIT_VALUES as UNIT_COSTS  # noqa: E402,F401
