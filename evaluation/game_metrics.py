"""Ten-match aggregation for the canonical game-performance objective."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from .game_performance import (
    GamePerformanceBreakdown,
    GamePerformanceConfig,
    compute_performance_breakdown,
    telemetry_temporal_summary,
    tick_from_result,
)
from .microrts_runner import MatchResult


FAILED_GAME_PERFORMANCE = -1000.0
OBJECTIVE_FORMULA_VERSION = "eagle-objectives-phase4-v1"


@dataclass(frozen=True)
class OpponentResult:
    """Lossless one-match summary used by artifacts and Strategy Reflection."""

    opponent_id: str
    opponent_name: str
    score: float
    wins: int
    draws: int
    losses: int
    match_count: int
    player_resource: float
    enemy_resource: float
    player_units: int
    enemy_units: int
    status: str
    failure: dict[str, str] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    wins: int = 0
    draws: int = 0
    losses: int = 0
    win_rate: float = 0.0
    mean_result_score: float = 0.0
    mean_material_score: float = 0.0
    mean_final_resource_score: float = 0.0
    mean_survival_score: float = 0.0
    score_stddev: float = 0.0
    minimum_match_score: float | None = None
    maximum_match_score: float | None = None
    completed_match_count: int = 0
    objective_formula_version: str = OBJECTIVE_FORMULA_VERSION
    final_player_resources: tuple[float, ...] = ()
    final_enemy_resources: tuple[float, ...] = ()
    unit_material_statistics: dict[str, Any] = field(default_factory=dict)
    survival_statistics: dict[str, Any] = field(default_factory=dict)
    behavior_summary: dict[str, Any] = field(default_factory=dict)
    opponent_results: list[OpponentResult] = field(default_factory=list)
    opponent_scores: list[float] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["opponent_results"] = [item.to_json_dict() for item in self.opponent_results]
        payload["match_results"] = self.match_summaries
        return payload


def compute_game_metrics(match_results: list[MatchResult]) -> GameMetrics:
    completed = [
        result
        for result in match_results
        if result.ok
    ]
    summaries = [summarize_match(result) for result in completed]
    opponent_results = [summarize_opponent_result(result, index=index) for index, result in enumerate(match_results)]
    opponent_scores = [item.score for item in opponent_results]
    breakdowns = [fallback_performance_breakdown(result, result.raw_result) for result in completed]
    scores = [item.match_score for item in breakdowns]
    wins = sum(_winner(result) == 0 for result in completed)
    losses = sum(_winner(result) == 1 for result in completed)
    draws = len(completed) - wins - losses
    objective = (
        sum(scores) / 10.0
        if len(completed) == 10 and len(match_results) == 10
        else FAILED_GAME_PERFORMANCE
    )
    player_resources = tuple(_player_values(result)[0] for result in completed)
    enemy_resources = tuple(_player_values(result)[1] for result in completed)
    weighted_differences = [
        _player_values(result)[2] for result in completed
    ]
    material_differences = [item.mean_material_difference for item in breakdowns]
    survival_ratios = [item.survival_ratio for item in breakdowns]
    mean_player = _mean(player_resources)
    mean_enemy = _mean(enemy_resources)
    mean_weighted = _mean(weighted_differences)
    return GameMetrics(
        resource_difference=mean_weighted,
        objective=round(objective, 6),
        player0_resource=mean_player,
        player1_resource=mean_enemy,
        weighted_resource_difference=mean_weighted,
        winner=_winner(completed[-1]) if completed else None,
        final_cycle=completed[-1].final_cycle if completed else None,
        player_resource=mean_player,
        enemy_resource=mean_enemy,
        resource_breakdown={
            "player_resource": mean_player,
            "player0_resource": mean_player,
            "player1_resource": mean_enemy,
            "enemy_resource": mean_enemy,
            "weighted_resource_difference": mean_weighted,
            "matches": summaries,
        },
        raw_metrics={"matches": [match_to_dict(result) for result in match_results]},
        match_summaries=summaries,
        performance_breakdown={
            "mean_result_score": _mean([item.result_score for item in breakdowns]),
            "mean_material_score": _mean([item.unit_material_score for item in breakdowns]),
            "mean_final_resource_score": _mean([item.final_resource_score for item in breakdowns]),
            "mean_survival_score": _mean([item.survival_score for item in breakdowns]),
            "mean_shaping_score": _mean([item.shaping_score for item in breakdowns]),
            "mean_match_score": _mean(scores),
            "result_score": _mean([item.result_score for item in breakdowns]),
            "unit_material_score": _mean([item.unit_material_score for item in breakdowns]),
            "final_resource_score": _mean([item.final_resource_score for item in breakdowns]),
            "survival_score": _mean([item.survival_score for item in breakdowns]),
            "shaping_score": _mean([item.shaping_score for item in breakdowns]),
            "total_performance": _mean(scores),
        },
        temporal_summary={
            "matches": [
                telemetry_temporal_summary(result.telemetry)
                for result in completed
                if result.telemetry is not None
            ]
        },
        wins=wins,
        draws=draws,
        losses=losses,
        win_rate=round(wins / 10.0, 6) if len(completed) == 10 else 0.0,
        mean_result_score=_mean([item.result_score for item in breakdowns]),
        mean_material_score=_mean([item.unit_material_score for item in breakdowns]),
        mean_final_resource_score=_mean([item.final_resource_score for item in breakdowns]),
        mean_survival_score=_mean([item.survival_score for item in breakdowns]),
        score_stddev=round(statistics.pstdev(opponent_scores), 6) if len(opponent_scores) > 1 else 0.0,
        minimum_match_score=min(opponent_scores) if opponent_scores else None,
        maximum_match_score=max(opponent_scores) if opponent_scores else None,
        completed_match_count=len(completed),
        final_player_resources=player_resources,
        final_enemy_resources=enemy_resources,
        unit_material_statistics=_series_statistics(material_differences),
        survival_statistics=_series_statistics(survival_ratios),
        behavior_summary={
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "mean_final_resource_difference": _mean(
                [player - enemy for player, enemy in zip(player_resources, enemy_resources)]
            ),
            "mean_material_difference": _mean(material_differences),
            "mean_survival_ratio": _mean(survival_ratios),
        },
        opponent_results=opponent_results,
        opponent_scores=opponent_scores,
    )


def summarize_match(result: MatchResult) -> dict[str, Any]:
    breakdown = fallback_performance_breakdown(result, result.raw_result)
    return {
        "opponent_id": getattr(result, "opponent_id", None),
        "opponent_name": getattr(result, "opponent_name", None) or getattr(result, "opponent", None),
        "match_index": result.match_index,
        "seed": result.seed,
        "winner": _winner(result),
        "result": result.raw_result.get("result"),
        "final_cycle": result.final_cycle,
        "player_resource": result.player0_resource,
        "enemy_resource": result.player1_resource,
        "weighted_resource_difference": result.weighted_resource_difference,
        "performance": None if breakdown is None else breakdown.match_score,
        "performance_breakdown": None if breakdown is None else breakdown.to_json_dict(),
        "replay_path": result.replay_path,
        "telemetry_path": result.telemetry_path,
        "summary_path": result.summary_path,
    }


def summarize_opponent_result(result: MatchResult, *, index: int) -> OpponentResult:
    """Summarize every attempted opponent, including failed matches."""

    opponent_id = str(getattr(result, "opponent_id", None) or f"opponent_{index + 1}")
    opponent_name = str(
        getattr(result, "opponent_name", None)
        or getattr(result, "opponent", None)
        or opponent_id
    )
    player_resource, enemy_resource, _ = _player_values(result)
    players = result.raw_result.get("players") or {}
    player_units = _unit_count(players.get("p0") or {})
    enemy_units = _unit_count(players.get("p1") or {})
    if not result.ok:
        failure = {
            "category": str(getattr(result, "failure_category", None) or "runtime_match_failure"),
            "reason": str(getattr(result, "failure_reason", None) or "match failed"),
        }
        return OpponentResult(
            opponent_id=opponent_id,
            opponent_name=opponent_name,
            score=FAILED_GAME_PERFORMANCE,
            wins=0,
            draws=0,
            losses=0,
            match_count=1,
            player_resource=player_resource,
            enemy_resource=enemy_resource,
            player_units=player_units,
            enemy_units=enemy_units,
            status="failed",
            failure=failure,
        )
    breakdown = fallback_performance_breakdown(result, result.raw_result)
    winner = _winner(result)
    return OpponentResult(
        opponent_id=opponent_id,
        opponent_name=opponent_name,
        score=float(breakdown.match_score),
        wins=int(winner == 0),
        draws=int(winner not in (0, 1)),
        losses=int(winner == 1),
        match_count=1,
        player_resource=player_resource,
        enemy_resource=enemy_resource,
        player_units=player_units,
        enemy_units=enemy_units,
        status="completed",
    )


def match_to_dict(result: MatchResult) -> dict[str, Any]:
    if hasattr(result, "to_json_dict"):
        return result.to_json_dict()
    return {
        "ok": result.ok,
        "score": result.score,
        "winner": result.winner,
        "final_cycle": result.final_cycle,
        "raw_result": result.raw_result,
    }


def average_breakdowns(results: list[MatchResult]) -> dict[str, float]:
    breakdowns = [result.performance_breakdown for result in results if result.performance_breakdown]
    return {
        "result_score": _mean([item.result_score for item in breakdowns]),
        "unit_material_score": _mean([item.unit_material_score for item in breakdowns]),
        "final_resource_score": _mean([item.final_resource_score for item in breakdowns]),
        "survival_score": _mean([item.survival_score for item in breakdowns]),
        "shaping_score": _mean([item.shaping_score for item in breakdowns]),
        "match_score": _mean([item.match_score for item in breakdowns]),
    } if breakdowns else {}


def fallback_performance_breakdown(result: MatchResult, payload: dict[str, Any]) -> GamePerformanceBreakdown:
    if result.performance_breakdown is not None:
        return result.performance_breakdown
    winner = _winner(result)
    end_tick = result.final_cycle or int(payload.get("final_tick") or 1)
    max_tick = int(payload.get("max_cycles") or end_tick or 1)
    config = GamePerformanceConfig()
    tick = tick_from_result(payload, tick=end_tick, player_index=0, scoring_config=config)
    return compute_performance_breakdown(
        result=str(payload.get("result") or ""),
        winner=winner,
        end_tick=end_tick,
        max_tick=max_tick,
        ticks=[tick],
        scoring_config=config,
        player_index=0,
    )


def _winner(result: MatchResult) -> int | None:
    value = result.winner if result.winner is not None else result.raw_result.get("winner")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _player_values(result: MatchResult) -> tuple[float, float, float]:
    players = result.raw_result.get("players") or {}
    p0 = players.get("p0") or {}
    p1 = players.get("p1") or {}
    player = float(result.player0_resource if result.player0_resource is not None else p0.get("resource_total") or 0.0)
    enemy = float(result.player1_resource if result.player1_resource is not None else p1.get("resource_total") or 0.0)
    player_material = float(p0.get("material_total") or 0.0)
    enemy_material = float(p1.get("material_total") or 0.0)
    weighted = result.weighted_resource_difference
    if weighted is None:
        weighted = (player + player_material) - (enemy + enemy_material)
    return player, enemy, float(weighted)


def _unit_count(player: dict[str, Any]) -> int:
    value = player.get("unit_count")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    unit_types = player.get("unit_types") or {}
    return sum(int(value) for value in unit_types.values() if isinstance(value, (int, float)))


def _mean(values: list[float] | tuple[float, ...]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _series_statistics(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": _mean(values),
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "stddev": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
    }
