"""Ten-match aggregation for the canonical game-performance objective."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
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
    """Opponent-level summary over the complete map/round/side matrix."""

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
    weight: float = 1.0
    raw_match_score: float | None = None
    weighted_contribution: float | None = None
    expected_match_count: int = 1
    completed_match_count: int = 0
    missing_match_count: int = 0
    p0_average: float = 0.0
    p1_average: float = 0.0
    map_averages: dict[str, float] = field(default_factory=dict)
    match_scores: tuple[float, ...] = ()

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
    missing_match_count: int = 0
    objective_formula_version: str = OBJECTIVE_FORMULA_VERSION
    final_player_resources: tuple[float, ...] = ()
    final_enemy_resources: tuple[float, ...] = ()
    unit_material_statistics: dict[str, Any] = field(default_factory=dict)
    survival_statistics: dict[str, Any] = field(default_factory=dict)
    behavior_summary: dict[str, Any] = field(default_factory=dict)
    opponent_results: list[OpponentResult] = field(default_factory=list)
    opponent_scores: list[float] = field(default_factory=list)
    fixed_weight_sum: float = 12.5
    total_weight: float = 12.5
    weighted_numerator: float = 0.0
    expected_match_count: int = 10
    evaluation_maps: tuple[str, ...] = ()
    rounds_per_map: int = 3
    swap_player_sides: bool = True

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Raw process output and telemetry are canonical per-match artifacts.
        # Candidate/game summaries retain only the bounded match summaries used
        # by fitness, analysis, and the next mutation Reflection.
        payload.pop("raw_metrics", None)
        payload["opponent_results"] = [item.to_json_dict() for item in self.opponent_results]
        payload["opponent_scores"] = {
            item.opponent_id: float(item.score)
            for item in self.opponent_results
        }
        payload["game_performance"] = self.objective
        payload["match_results"] = self.match_summaries
        return payload


def _legacy_compute_game_metrics(
    match_results: list[MatchResult],
    *,
    fixed_opponent_weights: dict[str, float] | None = None,
    expected_match_count: int = 10,
) -> GameMetrics:
    fixed_weights = fixed_opponent_weights or {}
    fixed_weight_sum = sum(fixed_weights.values()) if fixed_weights else float(expected_match_count)
    total_weight = fixed_weight_sum
    completed = [
        result
        for result in match_results
        if result.ok
    ]
    summaries = [summarize_match(result) for result in completed]
    opponent_results = [
        summarize_opponent_result(
            result,
            index=index,
            weight=fixed_weights.get(getattr(result, "opponent_id", None), 1.0),
        )
        for index, result in enumerate(match_results)
    ]
    opponent_scores = [item.score for item in opponent_results]
    weighted_numerator = sum(float(item.weighted_contribution or 0.0) for item in opponent_results)
    breakdowns = [fallback_performance_breakdown(result, result.raw_result) for result in completed]
    scores = [item.match_score for item in breakdowns]
    wins = sum(_winner(result) == 0 for result in completed)
    losses = sum(_winner(result) == 1 for result in completed)
    draws = len(completed) - wins - losses
    objective = (
        weighted_numerator / total_weight
        if total_weight > 0 and len(completed) == expected_match_count and len(match_results) == expected_match_count
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
        },
        raw_metrics={},
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
        win_rate=round(wins / expected_match_count, 6) if len(completed) == expected_match_count else 0.0,
        mean_result_score=_mean([item.result_score for item in breakdowns]),
        mean_material_score=_mean([item.unit_material_score for item in breakdowns]),
        mean_final_resource_score=_mean([item.final_resource_score for item in breakdowns]),
        mean_survival_score=_mean([item.survival_score for item in breakdowns]),
        score_stddev=round(statistics.pstdev(opponent_scores), 6) if len(opponent_scores) > 1 else 0.0,
        minimum_match_score=min(opponent_scores) if opponent_scores else None,
        maximum_match_score=max(opponent_scores) if opponent_scores else None,
        completed_match_count=len(completed),
        missing_match_count=max(0, expected_match_count - len(completed)),
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
        fixed_weight_sum=round(fixed_weight_sum, 6),
        total_weight=round(total_weight, 6),
        weighted_numerator=round(weighted_numerator, 6),
    )


def compute_game_metrics(
    match_results: list[MatchResult],
    *,
    fixed_opponent_weights: dict[str, float] | None = None,
    expected_match_count: int = 10,
    expected_matches_per_opponent: int | None = None,
    evaluation_maps: tuple[str, ...] = (),
    rounds_per_map: int = 3,
    swap_player_sides: bool = True,
) -> GameMetrics:
    """Aggregate match scores by opponent, then apply opponent weights.

    The canonical evaluator supplies 18 results per opponent. Keeping the
    grouping here prevents an opponent's weight from being multiplied by the
    number of map/round/side conditions.
    """

    # Preserve the historical single-list API for callers/tests that do not
    # provide opponent identities. The canonical evaluator always supplies
    # IDs and therefore takes the matrix-aware path below.
    if fixed_opponent_weights is None and not any(getattr(item, "opponent_id", None) for item in match_results):
        return _legacy_compute_game_metrics(
            match_results,
            expected_match_count=expected_match_count,
        )
    if fixed_opponent_weights is None:
        inferred_ids = tuple(dict.fromkeys(str(getattr(item, "opponent_id", "unknown")) for item in match_results))
        fixed_weights = {item: 1.0 for item in inferred_ids}
    else:
        fixed_weights = fixed_opponent_weights
    active_ids = list(fixed_weights)
    grouped: dict[str, list[MatchResult]] = {item: [] for item in active_ids}
    for result in match_results:
        grouped.setdefault(str(getattr(result, "opponent_id", None) or "unknown"), []).append(result)
    active_count = max(1, len(active_ids))
    expected_per_opponent = expected_matches_per_opponent or (
        1 if fixed_opponent_weights is None and expected_match_count == len(match_results) else max(1, expected_match_count // active_count)
    )
    fixed_weight_sum = sum(fixed_weights.values()) if fixed_weights else float(expected_match_count)
    total_weight = fixed_weight_sum
    opponent_results: list[OpponentResult] = []
    for opponent_id in active_ids:
        weight = float(fixed_weights.get(opponent_id, 1.0))
        opponent_results.append(
            _summarize_opponent_group(
                opponent_id,
                grouped.get(opponent_id, []),
                weight=weight,
                expected_match_count=expected_per_opponent,
            )
        )
    # Preserve unexpected IDs in partial/failure artifacts rather than dropping evidence.
    for opponent_id, results in grouped.items():
        if opponent_id not in active_ids:
            opponent_results.append(
                _summarize_opponent_group(
                    opponent_id, results, weight=1.0, expected_match_count=expected_per_opponent
                )
            )
    completed = [result for result in match_results if result.ok]
    breakdowns = [fallback_performance_breakdown(result, result.raw_result) for result in completed]
    scores = [item.match_score for item in breakdowns]
    opponent_scores = [item.score for item in opponent_results]
    weighted_numerator = sum(float(item.weighted_contribution or 0.0) for item in opponent_results if item.opponent_id in active_ids)
    complete = len(match_results) == expected_match_count and len(completed) == expected_match_count
    objective = weighted_numerator / total_weight if complete and total_weight > 0 else FAILED_GAME_PERFORMANCE
    wins = sum(_winner(result) == result.candidate_player for result in completed)
    losses = sum(_winner(result) == 1 - result.candidate_player for result in completed)
    draws = len(completed) - wins - losses
    player_resources = tuple(_player_values(result)[0] for result in completed)
    enemy_resources = tuple(_player_values(result)[1] for result in completed)
    weighted_differences = [_player_values(result)[2] for result in completed]
    material_differences = [item.mean_material_difference for item in breakdowns]
    survival_ratios = [item.survival_ratio for item in breakdowns]
    summaries = [summarize_match(result) for result in completed]
    return GameMetrics(
        resource_difference=_mean(weighted_differences),
        objective=round(objective, 6),
        player0_resource=_mean(list(player_resources)),
        player1_resource=_mean(list(enemy_resources)),
        weighted_resource_difference=_mean(weighted_differences),
        winner=_winner(completed[-1]) if completed else None,
        final_cycle=completed[-1].final_cycle if completed else None,
        player_resource=_mean(list(player_resources)),
        enemy_resource=_mean(list(enemy_resources)),
        resource_breakdown={
            "player_resource": _mean(list(player_resources)),
            "player0_resource": _mean(list(player_resources)),
            "player1_resource": _mean(list(enemy_resources)),
            "enemy_resource": _mean(list(enemy_resources)),
            "weighted_resource_difference": _mean(weighted_differences),
        },
        raw_metrics={},
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
        temporal_summary={"matches": [telemetry_temporal_summary(result.telemetry) for result in completed if result.telemetry is not None]},
        wins=wins,
        draws=draws,
        losses=losses,
        win_rate=round(wins / expected_match_count, 6) if complete else 0.0,
        mean_result_score=_mean([item.result_score for item in breakdowns]),
        mean_material_score=_mean([item.unit_material_score for item in breakdowns]),
        mean_final_resource_score=_mean([item.final_resource_score for item in breakdowns]),
        mean_survival_score=_mean([item.survival_score for item in breakdowns]),
        score_stddev=round(statistics.pstdev(opponent_scores), 6) if len(opponent_scores) > 1 else 0.0,
        minimum_match_score=min(opponent_scores) if opponent_scores else None,
        maximum_match_score=max(opponent_scores) if opponent_scores else None,
        completed_match_count=len(completed),
        missing_match_count=max(0, expected_match_count - len(completed)),
        objective_formula_version=OBJECTIVE_FORMULA_VERSION,
        final_player_resources=player_resources,
        final_enemy_resources=enemy_resources,
        unit_material_statistics=_series_statistics(material_differences),
        survival_statistics=_series_statistics(survival_ratios),
        behavior_summary={
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "opponents": [item.to_json_dict() for item in opponent_results],
        },
        opponent_results=opponent_results,
        opponent_scores=opponent_scores,
        fixed_weight_sum=round(fixed_weight_sum, 6),
        total_weight=round(total_weight, 6),
        weighted_numerator=round(weighted_numerator, 6),
        expected_match_count=expected_match_count,
        evaluation_maps=tuple(evaluation_maps),
        rounds_per_map=rounds_per_map,
        swap_player_sides=swap_player_sides,
    )


def _summarize_opponent_group(
    opponent_id: str,
    results: list[MatchResult],
    *,
    weight: float,
    expected_match_count: int,
) -> OpponentResult:
    completed = [item for item in results if item.ok]
    scores = [fallback_performance_breakdown(item, item.raw_result).match_score for item in completed]
    opponent_score = _mean(scores) if len(completed) == expected_match_count else FAILED_GAME_PERFORMANCE
    p0_scores = [score for item, score in zip(completed, scores) if item.candidate_player == 0]
    p1_scores = [score for item, score in zip(completed, scores) if item.candidate_player == 1]
    map_scores: dict[str, list[float]] = {}
    for item, score in zip(completed, scores):
        map_scores.setdefault(str(getattr(item, "map_id", None) or getattr(item, "map_path", "unknown")), []).append(score)
    wins = sum(_winner(item) == item.candidate_player for item in completed)
    losses = sum(_winner(item) == 1 - item.candidate_player for item in completed)
    draws = len(completed) - wins - losses
    first = results[0] if results else None
    failure = None
    if len(completed) != expected_match_count:
        failed = next((item for item in results if not item.ok), None)
        failure = {
            "category": str(getattr(failed, "failure_category", None) or "partial_evaluation"),
            "reason": str(getattr(failed, "failure_reason", None) or f"completed {len(completed)} of {expected_match_count}"),
        }
    return OpponentResult(
        opponent_id=opponent_id,
        opponent_name=str(getattr(first, "opponent_name", None) or getattr(first, "opponent", None) or opponent_id),
        score=opponent_score,
        wins=wins,
        draws=draws,
        losses=losses,
        match_count=len(results),
        player_resource=_mean([_player_values(item)[0] for item in completed]),
        enemy_resource=_mean([_player_values(item)[1] for item in completed]),
        player_units=_mean([_unit_count((item.raw_result.get("players") or {}).get("p0") or {}) for item in completed]),
        enemy_units=_mean([_unit_count((item.raw_result.get("players") or {}).get("p1") or {}) for item in completed]),
        status="completed" if len(completed) == expected_match_count else "failed",
        failure=failure,
        weight=weight,
        raw_match_score=opponent_score,
        weighted_contribution=opponent_score * weight,
        expected_match_count=expected_match_count,
        completed_match_count=len(completed),
        missing_match_count=max(0, expected_match_count - len(completed)),
        p0_average=_mean(p0_scores),
        p1_average=_mean(p1_scores),
        map_averages={key: _mean(value) for key, value in map_scores.items()},
        match_scores=tuple(scores),
    )


def summarize_match(result: MatchResult) -> dict[str, Any]:
    breakdown = fallback_performance_breakdown(result, result.raw_result)
    match_dir = getattr(result, "match_dir", None)
    match_id = None if match_dir is None else Path(str(match_dir)).name
    return {
        "opponent_id": getattr(result, "opponent_id", None),
        "opponent_name": getattr(result, "opponent_name", None) or getattr(result, "opponent", None),
        "match_index": result.match_index,
        "candidate_player": result.candidate_player,
        "map": result.map_path,
        "map_id": getattr(result, "map_id", None),
        "round_index": getattr(result, "round_index", None),
        "match_id": match_id,
        "candidate_id": getattr(result, "candidate_id", None),
        "candidate_side": "p0" if getattr(result, "candidate_player", 0) == 0 else "p1",
        "seed": result.seed,
        "opponent_weight": getattr(result, "opponent_weight", 1.0),
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
        "match_trace_path": getattr(result, "trace_path", None),
        "match_trace_integrity_path": getattr(result, "trace_integrity_path", None),
        "match_commentary_path": (
            None if getattr(result, "match_dir", None) is None else f"{result.match_dir}/commentary/match_commentary.json"
        ),
        "match_log_path": getattr(result, "match_log_path", None),
    }


def summarize_opponent_result(result: MatchResult, *, index: int, weight: float = 1.0) -> OpponentResult:
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
            weight=weight,
            raw_match_score=FAILED_GAME_PERFORMANCE,
            weighted_contribution=FAILED_GAME_PERFORMANCE * weight,
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
        weight=weight,
        raw_match_score=float(breakdown.match_score),
        weighted_contribution=float(breakdown.match_score) * weight,
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
    player_index = int(getattr(result, "candidate_player", 0))
    tick = tick_from_result(payload, tick=end_tick, player_index=player_index, scoring_config=config)
    return compute_performance_breakdown(
        result=str(payload.get("result") or ""),
        winner=winner,
        end_tick=end_tick,
        max_tick=max_tick,
        ticks=[tick],
        scoring_config=config,
        player_index=player_index,
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
