"""Seeded lexicase parent selection and ``(mu + lambda)`` replacement."""
from __future__ import annotations

import random

from .candidate import Candidate
from .opponent_cases import FAILED_OPPONENT_SCORE, LEXICASE_CASES


def lexicase_select(
    population: list[Candidate],
    rng: random.Random,
    *,
    cases: tuple[str, ...] = LEXICASE_CASES,
) -> Candidate:
    """Select one candidate by filtering on a seeded random case order."""

    if not population:
        raise ValueError("Cannot select from an empty population.")
    survivors = list(population)
    for case in rng.sample(list(cases), len(cases)):
        best = max(_case_score(candidate, case) for candidate in survivors)
        survivors = [candidate for candidate in survivors if _case_score(candidate, case) == best]
        if len(survivors) <= 1:
            break
    return rng.choice(survivors)


def select_parent(population: list[Candidate], rng: random.Random) -> Candidate:
    """Use lexicase for every parent request, including crossover."""

    return lexicase_select(population, rng)


def select_next_generation(
    population: list[Candidate],
    offspring: list[Candidate],
    *,
    population_size: int,
    rng: random.Random,
) -> list[Candidate]:
    """Select a fixed-size generation from parents and offspring jointly.

    Seeded opponent-wise lexicase is applied without replacement to the unique
    ``(mu + lambda)`` candidate pool. Aggregate Game Performance is
    reporting-only; code quality is never consulted.
    """

    if population_size < 0:
        raise ValueError("population_size must be non-negative.")

    available: list[Candidate] = []
    available_ids: set[str] = set()
    for candidate in [*population, *offspring]:
        if candidate.id not in available_ids:
            available.append(candidate)
            available_ids.add(candidate.id)
    if len(available) < population_size:
        raise ValueError(
            "Cannot select a fixed-size generation without replacement: "
            f"requested {population_size}, found {len(available)} unique candidates."
        )

    selected: list[Candidate] = []
    while len(selected) < population_size:
        chosen = lexicase_select(available, rng)
        selected.append(chosen)
        available = [candidate for candidate in available if candidate.id != chosen.id]
    return selected


def best_candidate(population: list[Candidate]) -> Candidate | None:
    """Return the convenient aggregate-performance representative."""

    runnable = [candidate for candidate in population if candidate.status != "failed"]
    if not runnable:
        return None
    return max(
        runnable,
        key=lambda candidate: (
            _reporting_game_performance(candidate),
            candidate.id,
        ),
    )


def population_signature(population: list[Candidate]) -> tuple[tuple[float, ...], ...]:
    """Return a stable case-vector signature for optional stagnation checks."""

    return tuple(sorted(candidate.objective_vector() for candidate in population))


def _case_score(candidate: Candidate, case: str) -> float:
    return float(candidate.fitness_objectives.get(case, FAILED_OPPONENT_SCORE))


def _reporting_game_performance(candidate: Candidate) -> float:
    value = (candidate.game_eval_result or {}).get("game_performance")
    if value is not None:
        return float(value)
    from .opponent_cases import aggregate_game_performance
    return aggregate_game_performance(candidate.fitness_objectives)
