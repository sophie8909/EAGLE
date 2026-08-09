"""Reusable schedules and deterministic champion selection for search opponents."""

from __future__ import annotations

from typing import Iterable

from eagle.candidate import Candidate


EAGLE_OPPONENT_ID = "eagle_previous_best"


def eagle_opponent_weight(
    generation: int,
    total_generations: int,
    *,
    enabled: bool = True,
    min_weight: float = 0.5,
    max_weight: float = 4.0,
) -> float:
    """Return the quadratic previous-generation champion weight."""

    if not enabled or generation <= 0:
        return 0.0
    progress = (generation - 1) / max(total_generations - 2, 1)
    progress = min(1.0, max(0.0, progress))
    return round(min_weight + (max_weight - min_weight) * progress**2, 6)


def select_previous_generation_champion(population: Iterable[Candidate]) -> Candidate:
    """Select the persisted best candidate with deterministic tie-breaking."""

    candidates = tuple(population)
    if not candidates:
        raise ValueError("Cannot select an EAGLE opponent from an empty population.")
    best_game = max(float(item.fitness_objectives.get("game_performance", -1000.0)) for item in candidates)
    game_tied = tuple(
        item for item in candidates
        if float(item.fitness_objectives.get("game_performance", -1000.0)) == best_game
    )
    best_quality = max(float(item.fitness_objectives.get("code_quality", -1000.0)) for item in game_tied)
    return min(
        (item for item in game_tied
         if float(item.fitness_objectives.get("code_quality", -1000.0)) == best_quality),
        key=lambda item: item.id,
    )
