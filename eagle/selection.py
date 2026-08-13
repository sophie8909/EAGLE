"""Seeded lexicase parent selection and lightweight generational replacement."""
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
    """Select a fixed-size generation using opponent-wise lexicase only.

    Offspring are preferred, with the previous population used only when the
    offspring list is too small. Aggregate Game Performance is reporting-only;
    code quality is never consulted.
    """

    if not offspring:
        return list(population[:population_size])
    selected: list[Candidate] = []
    available = list(offspring)
    while len(selected) < population_size and available:
        chosen = lexicase_select(available, rng)
        selected.append(chosen)
        available = [candidate for candidate in available if candidate.id != chosen.id]
    if len(selected) < population_size:
        remaining = [candidate for candidate in population if candidate.id not in {item.id for item in selected}]
        while len(selected) < population_size and remaining:
            chosen = lexicase_select(remaining, rng)
            selected.append(chosen)
            remaining = [candidate for candidate in remaining if candidate.id != chosen.id]
    return selected[:population_size]


def best_candidate(population: list[Candidate]) -> Candidate | None:
    """Return the convenient aggregate-performance representative."""

    if not population:
        return None
    return max(
        population,
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
