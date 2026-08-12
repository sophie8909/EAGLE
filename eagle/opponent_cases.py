"""Canonical evolutionary cases and reporting weights."""
from __future__ import annotations

from typing import Mapping


LEXICASE_CASES = (
    "passive",
    "random",
    "randombias",
    "lightrush",
    "heavyrush",
    "workerrush",
    "allinbot",
    "mayari",
    "coac",
    "tma",
)

OPPONENT_WEIGHTS = {
    "passive": 0.5,
    "random": 0.5,
    "randombias": 0.5,
    "lightrush": 1.0,
    "heavyrush": 1.0,
    "workerrush": 1.0,
    "allinbot": 2.0,
    "mayari": 2.0,
    "coac": 2.0,
    "tma": 2.0,
}

FAILED_OPPONENT_SCORE = -1000.0
OPPONENT_WEIGHT_SUM = sum(OPPONENT_WEIGHTS.values())


def aggregate_game_performance(scores: Mapping[str, float]) -> float:
    """Calculate the reporting-only weighted Game Performance."""

    return round(
        sum(float(scores.get(case, FAILED_OPPONENT_SCORE)) * OPPONENT_WEIGHTS[case] for case in LEXICASE_CASES)
        / OPPONENT_WEIGHT_SUM,
        6,
    )


def opponent_score_vector(scores: Mapping[str, float], *, failed: bool = False) -> dict[str, float]:
    """Return all lexicase cases, using the canonical failure sentinel."""

    fallback = FAILED_OPPONENT_SCORE if failed else 0.0
    return {case: float(scores.get(case, fallback)) for case in LEXICASE_CASES}
