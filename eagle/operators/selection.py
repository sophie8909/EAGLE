"""Seeded parent selection and ``(mu + lambda)`` replacement."""
from __future__ import annotations

import math
import random
from typing import Any, Literal

from eagle.candidate import Candidate, has_completed_evaluation
from eagle.opponent_cases import FAILED_OPPONENT_SCORE, LEXICASE_CASES
from eagle.semantic_distances import (
    SemanticSummary,
    semantic_distance as _semantic_distance,
    semantic_summary as _semantic_summary,
)


LEXICASE_SELECTION = "lexicase"
GAME_PERFORMANCE_SELECTION = "game_performance_semantic_tiebreak"
GAME_PERFORMANCE_TIE_TOLERANCE = 1.0
SelectionMode = Literal["lexicase", "game_performance_semantic_tiebreak"]

def lexicase_select(
    population: list[Candidate],
    rng: random.Random,
    *,
    cases: tuple[str, ...] | None = None,
) -> Candidate:
    """Select one candidate by filtering on a seeded random case order."""

    if not population:
        raise ValueError("Cannot select from an empty population.")
    cases = cases or _fitness_cases(population)
    survivors = sorted(population, key=lambda candidate: candidate.id)
    for case in rng.sample(list(cases), len(cases)):
        best = max(_case_score(candidate, case) for candidate in survivors)
        survivors = [candidate for candidate in survivors if _case_score(candidate, case) == best]
        if len(survivors) <= 1:
            break
    return rng.choice(survivors)


def select_parent(
    population: list[Candidate],
    rng: random.Random,
    *,
    selection_mode: SelectionMode = LEXICASE_SELECTION,
    fitness_tolerance: float = GAME_PERFORMANCE_TIE_TOLERANCE,
    semantic_reference: Candidate | None = None,
) -> Candidate:
    """Select one parent under the requested seeded selection contract.

    Self-play selects the first parent from the top Game Performance tier.
    The second parent is the nearest behavioral match across the population,
    excluding the first parent when another candidate exists.
    """

    if selection_mode == LEXICASE_SELECTION:
        return lexicase_select(population, rng)
    _validate_selection_mode(selection_mode)
    if not population:
        raise ValueError("Cannot select from an empty population.")

    if semantic_reference is None:
        _validate_fitness_tolerance(fitness_tolerance)
        tier = _top_score_tier(population, tolerance=fitness_tolerance)
        return _choose_by_semantic_distance(tier, [], rng, prefer_nearest=True)
    mates = [candidate for candidate in population if candidate.id != semantic_reference.id]
    return _choose_by_semantic_distance(
        mates or population, [semantic_reference], rng, prefer_nearest=True
    )


def select_next_generation(
    population: list[Candidate],
    offspring: list[Candidate],
    *,
    population_size: int,
    rng: random.Random,
    selection_mode: SelectionMode = LEXICASE_SELECTION,
) -> list[Candidate]:
    """Select a fixed-size generation from parents and offspring jointly.

    Self-play reserves up to two seats for behaviorally distant candidates
    after filling the other seats by Game Performance.
    """

    if population_size < 0:
        raise ValueError("population_size must be non-negative.")
    _validate_selection_mode(selection_mode)

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

    completed = [candidate for candidate in available if has_completed_evaluation(candidate)]
    if len(completed) < population_size:
        if not completed:
            reason = "every parent and offspring candidate failed evaluation"
        else:
            reason = (
                f"only {len(completed)} parent/offspring candidates completed "
                "evaluation"
            )
        raise ValueError(
            "Cannot select a fixed-size next generation: "
            f"{reason}; requested {population_size} survivors."
        )

    # Failed candidates remain in the joint input for diagnostics, but cannot
    # displace a valid parent when completed candidates can fill the generation.
    available = sorted(completed, key=lambda candidate: candidate.id)

    if selection_mode == GAME_PERFORMANCE_SELECTION:
        return _select_scalar_survivors(
            available,
            population_size=population_size,
            rng=rng,
        )

    selected: list[Candidate] = []
    while len(selected) < population_size:
        chosen = lexicase_select(available, rng)
        selected.append(chosen)
        available = [candidate for candidate in available if candidate.id != chosen.id]
    return selected


def best_candidate(population: list[Candidate]) -> Candidate | None:
    """Return the convenient aggregate-performance representative."""

    runnable = [candidate for candidate in population if has_completed_evaluation(candidate)]
    if not runnable:
        return None
    return max(
        runnable,
        key=lambda candidate: (
            _reporting_game_performance(candidate),
            candidate.id,
        ),
    )


def population_signature(
    population: list[Candidate],
    *,
    selection_mode: SelectionMode = LEXICASE_SELECTION,
) -> tuple[tuple[Any, ...], ...]:
    """Return the active selection-state signature for stagnation checks."""

    if selection_mode == GAME_PERFORMANCE_SELECTION:
        return tuple(sorted(
            (
                _game_performance(candidate),
                _semantic_global_hash(candidate),
            )
            for candidate in population
        ))
    _validate_selection_mode(selection_mode)

    return tuple(sorted(candidate.objective_vector() for candidate in population))


def _select_scalar_survivors(
    available: list[Candidate],
    *,
    population_size: int,
    rng: random.Random,
) -> list[Candidate]:
    """Keep score leaders and rank diversity against those fixed references."""

    if population_size == 0:
        return []
    diversity_seats = min(2, population_size - 1)
    elite_count = population_size - diversity_seats
    ranked = sorted(available, key=_game_performance, reverse=True)
    elites = ranked[:elite_count]
    remaining = ranked[elite_count:]
    selected = list(elites)
    for _ in range(diversity_seats):
        chosen = _choose_by_semantic_distance(remaining, elites, rng)
        selected.append(chosen)
        remaining = [candidate for candidate in remaining if candidate.id != chosen.id]
    return selected


def _top_score_tier(
    candidates: list[Candidate],
    *,
    tolerance: float,
) -> list[Candidate]:
    """Return one tier anchored at the current maximum, without score chaining."""

    candidates = sorted(candidates, key=lambda candidate: candidate.id)
    maximum = max(_game_performance(candidate) for candidate in candidates)
    return [
        candidate
        for candidate in candidates
        if maximum - _game_performance(candidate) <= tolerance
    ]


def _choose_by_semantic_distance(
    candidates: list[Candidate],
    references: list[Candidate],
    rng: random.Random,
    *,
    prefer_nearest: bool = False,
) -> Candidate:
    """Choose nearest mates or max-min survivors, with seeded fallback."""

    if not candidates:
        raise ValueError("Cannot select from an empty candidate tier.")

    candidates = sorted(candidates, key=lambda candidate: candidate.id)
    reference_summaries = [
        summary
        for reference in references
        if (summary := _semantic_summary(reference)) is not None
    ]
    scored: list[tuple[Candidate, float]] = []
    for candidate in candidates:
        summary = _semantic_summary(candidate)
        if summary is None:
            continue
        distances = [
            distance
            for reference in reference_summaries
            if (distance := _semantic_distance(summary, reference)) is not None
        ]
        if distances:
            scored.append((candidate, min(distances)))

    if scored:
        optimum = min if prefer_nearest else max
        best_distance = optimum(distance for _, distance in scored)
        best = [candidate for candidate, distance in scored if distance == best_distance]
        return rng.choice(best)

    # With no comparable reference, seed selection from a complete summary.
    # Missing/incompatible summaries are fallback only.
    complete = [candidate for candidate in candidates if _semantic_summary(candidate) is not None]
    return rng.choice(complete or candidates)


def _semantic_global_hash(candidate: Candidate) -> str:
    summary = _semantic_summary(candidate)
    return "" if summary is None else summary[3]


def _game_performance(candidate: Candidate) -> float:
    value = (candidate.game_eval_result or {}).get("game_performance")
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Candidate {candidate.id!r} has no scalar game_performance fitness."
        ) from exc
    if not math.isfinite(score):
        raise ValueError(
            f"Candidate {candidate.id!r} has non-finite game_performance fitness."
        )
    return score


def _validate_selection_mode(selection_mode: str) -> None:
    if selection_mode not in {LEXICASE_SELECTION, GAME_PERFORMANCE_SELECTION}:
        raise ValueError(f"Unsupported selection mode: {selection_mode!r}.")


def _validate_fitness_tolerance(tolerance: float) -> None:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("fitness_tolerance must be finite and non-negative.")


def _case_score(candidate: Candidate, case: str) -> float:
    return float(candidate.fitness_objectives.get(case, FAILED_OPPONENT_SCORE))


def _fitness_cases(population: list[Candidate]) -> tuple[str, ...]:
    annotated = [
        tuple(candidate.game_eval_result.get("fitness_case_ids") or ())
        for candidate in population
    ]
    if all(cases in {(), LEXICASE_CASES} for cases in annotated):
        # Fixed-roster checkpoints predate explicit fitness_case_ids. Mixing a
        # legacy fixed-roster parent with a current fixed-roster offspring is
        # safe because the schema itself is immutable.
        return LEXICASE_CASES
    if any(not cases for cases in annotated) or len(set(annotated)) != 1:
        raise ValueError("Lexicase candidates do not share one fitness case schema.")
    cases = annotated[0]
    if any(set(candidate.fitness_objectives) != set(cases) for candidate in population):
        raise ValueError("Lexicase candidate objectives do not match their fitness case schema.")
    return cases


def _reporting_game_performance(candidate: Candidate) -> float:
    value = (candidate.game_eval_result or {}).get("game_performance")
    if value is not None:
        return float(value)
    from eagle.opponent_cases import aggregate_game_performance
    return aggregate_game_performance(candidate.fitness_objectives)
