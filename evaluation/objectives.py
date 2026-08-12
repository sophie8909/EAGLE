"""Opponent-wise evolutionary cases and reporting metrics."""
from __future__ import annotations

from .code_quality import CodeQualityBreakdown
from .game_metrics import GameMetrics
from eagle.opponent_cases import FAILED_OPPONENT_SCORE, LEXICASE_CASES, aggregate_game_performance

FAILED_OBJECTIVES = {case: FAILED_OPPONENT_SCORE for case in LEXICASE_CASES}
OBJECTIVE_DIRECTIONS = {case: "maximize" for case in LEXICASE_CASES}


def build_objectives(
    *,
    game_metrics: GameMetrics | None,
    code_quality: CodeQualityBreakdown | None = None,
    game_failure: bool = False,
) -> dict[str, float]:
    """Return one independent evolutionary score for each fixed opponent."""

    if game_failure or game_metrics is None:
        return dict(FAILED_OBJECTIVES)
    scores = {result.opponent_id: float(result.score) for result in game_metrics.opponent_results}
    if any(case not in scores for case in LEXICASE_CASES):
        return dict(FAILED_OBJECTIVES)
    return {case: scores[case] for case in LEXICASE_CASES}


def reporting_game_performance(objectives: dict[str, float]) -> float:
    """Compute weighted aggregate Game Performance for reporting only."""

    return aggregate_game_performance(objectives)
