"""MicroRTS match metric parsing and game-performance objective helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .microrts_runner import MatchResult


@dataclass(frozen=True)
class GameMetrics:
    resource_difference: float
    objective: float
    player_resource: float = 0.0
    enemy_resource: float = 0.0
    resource_breakdown: dict[str, Any] = field(default_factory=dict)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    match_summaries: list[dict[str, Any]] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_game_metrics(match_results: list[MatchResult]) -> GameMetrics:
    successful = [result for result in match_results if result.ok]
    if not successful:
        return GameMetrics(
            resource_difference=-1.0,
            objective=-1.0,
            player_resource=0.0,
            enemy_resource=0.0,
            resource_breakdown={},
            raw_metrics={"matches": [match_to_dict(result) for result in match_results]},
            match_summaries=[],
        )

    summaries = [summarize_match(result) for result in successful]
    resource_diff = sum(item["resource_difference"] for item in summaries) / len(summaries)
    player_resource = sum(item["player_resource"] for item in summaries) / len(summaries)
    enemy_resource = sum(item["enemy_resource"] for item in summaries) / len(summaries)
    win_bonus = sum(item["win_score"] for item in summaries) / len(summaries)
    score = sum(float(result.score) for result in successful) / len(successful)
    objective = resource_diff + win_bonus + score
    return GameMetrics(
        resource_difference=resource_diff,
        objective=objective,
        player_resource=player_resource,
        enemy_resource=enemy_resource,
        resource_breakdown={
            "player_resource": player_resource,
            "enemy_resource": enemy_resource,
            "matches": [
                {
                    "player_resource": item["player_resource"],
                    "enemy_resource": item["enemy_resource"],
                    "resource_difference": item["resource_difference"],
                    "unit_stockpiles": item["unit_stockpiles"],
                }
                for item in summaries
            ],
        },
        raw_metrics={"matches": [match_to_dict(result) for result in match_results]},
        match_summaries=summaries,
    )


def summarize_match(result: MatchResult) -> dict[str, Any]:
    payload = result.raw_result or {}
    scoreboard = payload.get("final_scoreboard") or {}
    p0_resources = _float_or_default(scoreboard.get("p0_resources", scoreboard.get("p0_eval")), result.score)
    p1_resources = _float_or_default(scoreboard.get("p1_resources", scoreboard.get("p1_eval")), 0.0)
    winner = payload.get("winner")
    win_score = 1.0 if winner == 0 else -1.0 if winner == 1 else 0.0
    return {
        "player_resource": p0_resources,
        "enemy_resource": p1_resources,
        "resource_difference": p0_resources - p1_resources,
        "win_score": win_score,
        "score": result.score,
        "winner": winner,
        "ticks": payload.get("ticks"),
        "damage_dealt": scoreboard.get("damage_dealt"),
        "units_produced": scoreboard.get("units_produced"),
        "unit_stockpiles": {
            "player": scoreboard.get("p0_units", scoreboard.get("p0_unit_count")),
            "enemy": scoreboard.get("p1_units", scoreboard.get("p1_unit_count")),
        },
    }


def match_to_dict(result: MatchResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "score": result.score,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "raw_result": result.raw_result,
    }


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
