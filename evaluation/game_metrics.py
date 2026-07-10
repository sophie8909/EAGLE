"""MicroRTS match metric parsing and game-performance objective helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .game_performance import (
    GamePerformanceConfig,
    GamePerformanceBreakdown,
    compute_performance_breakdown,
    tick_from_result,
    telemetry_temporal_summary,
)
from .microrts_runner import MatchResult


@dataclass(frozen=True)
class GameMetrics:
    resource_difference: float
    objective: float
    player0_resource: float = 0.0
    player1_resource: float = 0.0
    weighted_resource_difference: float = 0.0
    winner: int | None = None
    final_cycle: int | None = None
    player_resource: float = 0.0
    enemy_resource: float = 0.0
    resource_breakdown: dict[str, Any] = field(default_factory=dict)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    match_summaries: list[dict[str, Any]] = field(default_factory=list)
    performance_breakdown: dict[str, Any] = field(default_factory=dict)
    temporal_summary: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_game_metrics(match_results: list[MatchResult]) -> GameMetrics:
    successful = [result for result in match_results if result.ok]
    if not successful:
        return GameMetrics(
            resource_difference=-1.0,
            objective=-1.0,
            player0_resource=0.0,
            player1_resource=0.0,
            weighted_resource_difference=-1.0,
            winner=None,
            final_cycle=None,
            player_resource=0.0,
            enemy_resource=0.0,
            resource_breakdown={},
            raw_metrics={"matches": [match_to_dict(result) for result in match_results]},
            match_summaries=[],
        )

    summaries = [summarize_match(result) for result in successful]
    weighted_resource_diff = sum(item["weighted_resource_difference"] for item in summaries) / len(summaries)
    player0_resource = sum(item["player0_resource"] for item in summaries) / len(summaries)
    player1_resource = sum(item["player1_resource"] for item in summaries) / len(summaries)
    objective = sum(item["performance"] for item in summaries) / len(summaries)
    breakdown = average_breakdowns(successful)
    temporal = {"matches": [telemetry_temporal_summary(result.telemetry) for result in successful if result.telemetry]}
    return GameMetrics(
        resource_difference=weighted_resource_diff,
        objective=objective,
        player0_resource=player0_resource,
        player1_resource=player1_resource,
        weighted_resource_difference=weighted_resource_diff,
        winner=summaries[-1]["winner"],
        final_cycle=summaries[-1]["final_cycle"],
        player_resource=player0_resource,
        enemy_resource=player1_resource,
        resource_breakdown={
            "player0_resource": player0_resource,
            "player1_resource": player1_resource,
            "weighted_resource_difference": weighted_resource_diff,
            "player_resource": player0_resource,
            "enemy_resource": player1_resource,
            "matches": [
                {
                    "player0_resource": item["player0_resource"],
                    "player1_resource": item["player1_resource"],
                    "player0_material": item["player0_material"],
                    "player1_material": item["player1_material"],
                    "weighted_resource_difference": item["weighted_resource_difference"],
                    "performance": item["performance"],
                    "performance_breakdown": item["performance_breakdown"],
                    "unit_stockpiles": item["unit_stockpiles"],
                    "winner": item["winner"],
                    "final_cycle": item["final_cycle"],
                    "replay_path": item["replay_path"],
                    "telemetry_path": item["telemetry_path"],
                    "summary_path": item["summary_path"],
                }
                for item in summaries
            ],
        },
        raw_metrics={"matches": [match_to_dict(result) for result in match_results]},
        match_summaries=summaries,
        performance_breakdown=breakdown,
        temporal_summary=temporal,
    )


def summarize_match(result: MatchResult) -> dict[str, Any]:
    payload = result.raw_result or {}
    scoreboard = payload.get("final_scoreboard") or {}
    players = payload.get("players") or {}
    p0 = players.get("p0") or {}
    p1 = players.get("p1") or {}
    p0_resources = result.player0_resource
    if p0_resources is None:
        p0_resources = _float_or_default(
            p0.get("resource_total", scoreboard.get("p0_resources", scoreboard.get("p0_eval"))),
            result.score,
        )
    p1_resources = result.player1_resource
    if p1_resources is None:
        p1_resources = _float_or_default(
            p1.get("resource_total", scoreboard.get("p1_resources", scoreboard.get("p1_eval"))),
            0.0,
        )
    p0_material = _float_or_default(p0.get("material_total", scoreboard.get("p0_material")), 0.0)
    p1_material = _float_or_default(p1.get("material_total", scoreboard.get("p1_material")), 0.0)
    weighted_resource_difference = result.weighted_resource_difference
    if weighted_resource_difference is None:
        weighted_resource_difference = (p0_resources + p0_material) - (p1_resources + p1_material)
    winner = result.winner if result.winner is not None else payload.get("winner")
    performance_breakdown = result.performance_breakdown or fallback_performance_breakdown(result, payload)
    return {
        # Player 0 is always the generated candidate during EA evaluation.
        # The resource difference counts stored resources plus unit material value.
        "player0_resource": p0_resources,
        "player1_resource": p1_resources,
        "player0_material": p0_material,
        "player1_material": p1_material,
        "weighted_resource_difference": weighted_resource_difference,
        "player_resource": p0_resources,
        "enemy_resource": p1_resources,
        "resource_difference": weighted_resource_difference,
        "performance": performance_breakdown.total_performance,
        "performance_breakdown": performance_breakdown.to_json_dict(),
        "score": result.score,
        "winner": winner,
        "final_cycle": result.final_cycle if result.final_cycle is not None else payload.get("ticks"),
        "ticks": result.final_cycle if result.final_cycle is not None else payload.get("ticks"),
        "damage_dealt": scoreboard.get("damage_dealt"),
        "units_produced": scoreboard.get("units_produced"),
        "unit_stockpiles": {
            "player": scoreboard.get("p0_units", scoreboard.get("p0_unit_count")),
            "enemy": scoreboard.get("p1_units", scoreboard.get("p1_unit_count")),
        },
        "replay_path": result.replay_path,
        "telemetry_path": result.telemetry_path,
        "summary_path": result.summary_path,
    }


def match_to_dict(result: MatchResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "score": result.score,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "player0_resource": result.player0_resource,
        "player1_resource": result.player1_resource,
        "weighted_resource_difference": result.weighted_resource_difference,
        "winner": result.winner,
        "final_cycle": result.final_cycle,
        "performance_breakdown": None if result.performance_breakdown is None else result.performance_breakdown.to_json_dict(),
        "replay_path": result.replay_path,
        "telemetry_path": result.telemetry_path,
        "summary_path": result.summary_path,
        "persistence_error": result.persistence_error,
        "raw_result": result.raw_result,
    }


def average_breakdowns(results: list[MatchResult]) -> dict[str, float]:
    breakdowns = [
        result.performance_breakdown or fallback_performance_breakdown(result, result.raw_result or {})
        for result in results
    ]
    if not breakdowns:
        return {}
    return {
        "result_score": sum(item.result_score for item in breakdowns) / len(breakdowns),
        "average_state_score": sum(item.average_state_score for item in breakdowns) / len(breakdowns),
        "survival_score": sum(item.survival_score for item in breakdowns) / len(breakdowns),
        "final_resource_diff": sum(item.final_resource_diff for item in breakdowns) / len(breakdowns),
        "total_performance": sum(item.total_performance for item in breakdowns) / len(breakdowns),
    }


def fallback_performance_breakdown(result: MatchResult, payload: dict[str, Any]) -> GamePerformanceBreakdown:
    end_tick = result.final_cycle
    if end_tick is None:
        end_tick = _int_or_default(payload.get("final_tick", payload.get("ticks")), 0)
    max_tick = max(1, _int_or_default(payload.get("max_cycles"), end_tick))
    config = GamePerformanceConfig()
    tick = tick_from_result(payload, tick=end_tick, player_index=0, scoring_config=config)
    return compute_performance_breakdown(
        result=str(payload.get("result") or ""),
        winner=result.winner if result.winner is not None else payload.get("winner"),
        end_tick=end_tick,
        max_tick=max_tick,
        ticks=[tick],
        scoring_config=config,
        player_index=0,
    )


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
