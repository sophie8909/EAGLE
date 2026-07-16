"""Canonical bounded MicroRTS game-performance formula (phase4-v1)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


RESULT_WIN_SCORE = 100.0
RESULT_DRAW_SCORE = 0.0
RESULT_LOSS_SCORE = -100.0
DEFAULT_UNIT_VALUES = {
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
    material_scale: float = 10.0
    resource_scale: float = 10.0
    unit_values: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_UNIT_VALUES))
    shaping_min: float = -10.0
    shaping_max: float = 10.0

    def __post_init__(self) -> None:
        if self.material_scale <= 0 or self.resource_scale <= 0:
            raise ValueError("material_scale and resource_scale must be greater than zero.")
        if self.shaping_min != -10.0 or self.shaping_max != 10.0:
            raise ValueError("canonical shaping bounds are exactly [-10, 10].")

    def to_json_dict(self) -> dict[str, Any]:
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
    unit_material_score: float
    final_resource_score: float
    survival_score: float
    shaping_score: float
    match_score: float
    mean_material_difference: float
    final_resource_difference: float
    survival_ratio: float

    @property
    def average_state_score(self) -> float:
        return self.unit_material_score

    @property
    def final_resource_diff(self) -> float:
        return self.final_resource_score

    @property
    def total_performance(self) -> float:
        return self.match_score

    def to_json_dict(self) -> dict[str, float]:
        payload = asdict(self)
        payload.update({
            "average_state_score": self.unit_material_score,
            "final_resource_diff": self.final_resource_score,
            "total_performance": self.match_score,
        })
        return payload


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


def build_match_telemetry(*, raw_result: dict[str, Any], round_state_dir: Path, max_tick: int, player_index: int = 0, opponent_index: int = 1, replay_path: str | None = None, scoring_config: GamePerformanceConfig | None = None) -> MatchTelemetry:
    config = scoring_config or GamePerformanceConfig()
    ticks = read_tick_telemetry(round_state_dir, player_index=player_index, scoring_config=config)
    end_tick = int_or_default(raw_result.get("final_tick"), max_tick)
    result = str(raw_result.get("result") or result_from_winner(raw_result.get("winner"), raw_result.get("tick_timeout")))
    if not ticks:
        ticks = [tick_from_result(raw_result, tick=end_tick, player_index=player_index, scoring_config=config)]
    final_tick = ticks[-1]
    performance = compute_performance_breakdown(result=result, winner=raw_result.get("winner"), end_tick=end_tick, max_tick=max_tick, ticks=ticks, scoring_config=config, player_index=player_index)
    return MatchTelemetry(player_index, opponent_index, max_tick, end_tick, result, ticks, final_tick.player_resource, final_tick.enemy_resource, replay_path, performance, config)


def read_tick_telemetry(round_state_dir: Path, *, player_index: int, scoring_config: GamePerformanceConfig) -> list[MatchTickTelemetry]:
    ticks: dict[int, MatchTickTelemetry] = {}
    for path in sorted(round_state_dir.glob("round_*.log")):
        item = parse_round_state(path.read_text(encoding="utf-8"), player_index=player_index, scoring_config=scoring_config)
        ticks[item.tick] = item
    return [ticks[key] for key in sorted(ticks)]


def parse_round_state(text: str, *, player_index: int, scoring_config: GamePerformanceConfig) -> MatchTickTelemetry:
    tick = 0
    p0_resource = p1_resource = 0.0
    p0_units: dict[str, int] = {}
    p1_units: dict[str, int] = {}
    header = re.search(r"current time\s+(\d+).*?p0 player 0\(([-\d.]+)\).*?p1 player 1\(([-\d.]+)\)", text)
    if header:
        tick, p0_resource, p1_resource = int(header.group(1)), float(header.group(2)), float(header.group(3))
    for line in text.splitlines():
        parsed = parse_unit_line(line)
        if parsed is None:
            continue
        owner, unit_type = parsed
        target = p0_units if owner == 0 else p1_units
        target[unit_type] = target.get(unit_type, 0) + 1
    if player_index == 0:
        return tick_telemetry(tick, p0_resource, p1_resource, p0_units, p1_units, scoring_config)
    return tick_telemetry(tick, p1_resource, p0_resource, p1_units, p0_units, scoring_config)


def parse_unit_line(line: str) -> tuple[int, str] | None:
    match = re.search(r"\)\s+(Ally|Enemy)\s+(.+?) Unit\s+\{", line)
    return None if not match else (0 if match.group(1) == "Ally" else 1, match.group(2).strip())


def tick_telemetry(tick: int, player_resource: float, enemy_resource: float, player_units: dict[str, int], enemy_units: dict[str, int], scoring_config: GamePerformanceConfig) -> MatchTickTelemetry:
    costs = scoring_config.unit_values
    player_combat = unit_value(player_units, COMBAT_TYPES, costs)
    enemy_combat = unit_value(enemy_units, COMBAT_TYPES, costs)
    player_building = unit_value(player_units, BUILDING_TYPES, costs)
    enemy_building = unit_value(enemy_units, BUILDING_TYPES, costs)
    player_total = unit_value(player_units, set(costs), costs)
    enemy_total = unit_value(enemy_units, set(costs), costs)
    return MatchTickTelemetry(
        tick, player_resource, enemy_resource, dict(sorted(player_units.items())), dict(sorted(enemy_units.items())),
        sum(player_units.values()), sum(enemy_units.values()), player_combat, enemy_combat, player_building, enemy_building,
        player_total, enemy_total, player_combat - enemy_combat, player_building - enemy_building,
        player_resource - enemy_resource, player_total - enemy_total,
    )


def compute_performance_breakdown(*, result: str, winner: Any, end_tick: int, max_tick: int, ticks: list[MatchTickTelemetry], scoring_config: GamePerformanceConfig, player_index: int = 0) -> GamePerformanceBreakdown:
    result_score = score_result(result=result, winner=winner, player_index=player_index, scoring_config=scoring_config)
    mean_material_difference = sum(tick.player_total_unit_value - tick.enemy_total_unit_value for tick in ticks) / len(ticks) if ticks else 0.0
    unit_material_score = 5.0 * math.tanh(mean_material_difference / scoring_config.material_scale)
    final_tick = ticks[-1] if ticks else None
    final_resource_difference = 0.0 if final_tick is None else final_tick.resource_diff
    final_resource_score = 3.0 * math.tanh(final_resource_difference / scoring_config.resource_scale)
    survival_ratio = min(1.0, max(0.0, end_tick / max(1, max_tick)))
    survival_score = 2.0 * survival_ratio if result_score < 0 else 2.0 * (1.0 - survival_ratio) if result_score > 0 else 0.0
    raw_shaping = unit_material_score + final_resource_score + survival_score
    shaping_score = min(scoring_config.shaping_max, max(scoring_config.shaping_min, raw_shaping))
    return GamePerformanceBreakdown(
        round(result_score, 6), round(unit_material_score, 6), round(final_resource_score, 6),
        round(survival_score, 6), round(shaping_score, 6), round(result_score + shaping_score, 6),
        round(mean_material_difference, 6), round(final_resource_difference, 6), round(survival_ratio, 6),
    )


def score_result(*, result: str, winner: Any, player_index: int, scoring_config: GamePerformanceConfig) -> float:
    winner_int = int_or_none(winner)
    if winner_int == player_index:
        return scoring_config.result_win_score
    if winner_int in (0, 1):
        return scoring_config.result_loss_score
    return scoring_config.result_draw_score


def telemetry_summary(telemetry: MatchTelemetry, telemetry_path: str, summary_path: str) -> dict[str, Any]:
    performance = telemetry.performance
    return {
        "result": telemetry.result, "end_tick": telemetry.end_tick, "max_tick": telemetry.max_tick,
        "result_score": None if performance is None else performance.result_score,
        "unit_material_score": None if performance is None else performance.unit_material_score,
        "final_resource_score": None if performance is None else performance.final_resource_score,
        "survival_score": None if performance is None else performance.survival_score,
        "shaping_score": None if performance is None else performance.shaping_score,
        "match_score": None if performance is None else performance.match_score,
        "replay_path": telemetry.replay_path, "telemetry_path": telemetry_path, "summary_path": summary_path,
        "final_player_resource": telemetry.final_player_resource, "final_enemy_resource": telemetry.final_enemy_resource,
    }


def telemetry_temporal_summary(telemetry: MatchTelemetry) -> dict[str, Any]:
    return {
        "material_difference": summarize_series([(tick.tick, tick.player_total_unit_value - tick.enemy_total_unit_value) for tick in telemetry.ticks]),
        "resource_difference": summarize_series([(tick.tick, tick.resource_diff) for tick in telemetry.ticks]),
    }


def summarize_series(values: list[tuple[int, float]]) -> dict[str, float | int | None]:
    if not values:
        return {"average": None, "minimum": None, "minimum_tick": None, "maximum": None, "maximum_tick": None}
    minimum, maximum = min(values, key=lambda item: item[1]), max(values, key=lambda item: item[1])
    return {"average": sum(value for _, value in values) / len(values), "minimum": minimum[1], "minimum_tick": minimum[0], "maximum": maximum[1], "maximum_tick": maximum[0]}


def tick_from_result(raw_result: dict[str, Any], *, tick: int, player_index: int, scoring_config: GamePerformanceConfig) -> MatchTickTelemetry:
    players = raw_result.get("players") or {}
    p0, p1 = players.get("p0") or {}, players.get("p1") or {}
    p0_resource, p1_resource = float_or_default(p0.get("resource_total"), 0.0), float_or_default(p1.get("resource_total"), 0.0)
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
    return "p0_win" if winner_int == 0 else "p1_win" if winner_int == 1 else "timeout_draw" if bool(tick_timeout) else "draw"


def unit_value(units_by_type: dict[str, int], included_types: set[str], costs: dict[str, float]) -> float:
    return sum(costs.get(unit_type, 0.0) * count for unit_type, count in units_by_type.items() if unit_type in included_types)


def float_or_default(value: Any, default: float) -> float:
    parsed = float_or_none(value)
    return default if parsed is None else parsed


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def int_or_default(value: Any, default: int) -> int:
    parsed = int_or_none(value)
    return default if parsed is None else parsed


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
