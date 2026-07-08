"""MicroRTS match metric parsing and game-performance objective helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

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
    win_bonus = sum(item["win_score"] for item in summaries) / len(summaries)
    score = sum(float(result.score) for result in successful) / len(successful)
    objective = weighted_resource_diff + win_bonus + score
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
                    "weighted_resource_difference": item["weighted_resource_difference"],
                    "unit_stockpiles": item["unit_stockpiles"],
                    "winner": item["winner"],
                    "final_cycle": item["final_cycle"],
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
    p0_resources = result.player0_resource
    if p0_resources is None:
        p0_resources = _float_or_default(scoreboard.get("p0_resources", scoreboard.get("p0_eval")), result.score)
    p1_resources = result.player1_resource
    if p1_resources is None:
        p1_resources = _float_or_default(scoreboard.get("p1_resources", scoreboard.get("p1_eval")), 0.0)
    weighted_resource_difference = result.weighted_resource_difference
    if weighted_resource_difference is None:
        weighted_resource_difference = p0_resources - p1_resources
    winner = result.winner if result.winner is not None else payload.get("winner")
    win_score = 1.0 if winner == 0 else -1.0 if winner == 1 else 0.0
    return {
        # Player 0 is always the generated candidate during EA evaluation.
        "player0_resource": p0_resources,
        "player1_resource": p1_resources,
        "weighted_resource_difference": weighted_resource_difference,
        "player_resource": p0_resources,
        "enemy_resource": p1_resources,
        "resource_difference": weighted_resource_difference,
        "win_score": win_score,
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
        "raw_result": result.raw_result,
    }


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
