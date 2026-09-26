"""Seeded parent selection and ``(mu + lambda)`` replacement."""
from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import Any, Literal

from .candidate import Candidate
from .opponent_cases import FAILED_OPPONENT_SCORE, LEXICASE_CASES


LEXICASE_SELECTION = "lexicase"
GAME_PERFORMANCE_SELECTION = "game_performance_semantic_tiebreak"
GAME_PERFORMANCE_TIE_TOLERANCE = 1.0
SelectionMode = Literal["lexicase", "game_performance_semantic_tiebreak"]

# dataset ID, ordered probe IDs, ordered action hashes, global hash
SemanticSummary = tuple[str, tuple[str, ...], tuple[str, ...], str]


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
    survivors = list(population)
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

    Scalar selection considers only the top non-chained Game Performance tier.
    A second-parent request may supply the first parent as a semantic reference;
    complete compatible action signatures then break the fitness tie by maximum
    distance. Missing or incompatible signatures remain fallback candidates.
    """

    if selection_mode == LEXICASE_SELECTION:
        return lexicase_select(population, rng)
    _validate_selection_mode(selection_mode)
    _validate_fitness_tolerance(fitness_tolerance)
    if not population:
        raise ValueError("Cannot select from an empty population.")

    tier = _top_score_tier(population, tolerance=fitness_tolerance)
    references = [] if semantic_reference is None else [semantic_reference]
    return _choose_semantically_novel(tier, references, rng)


def select_next_generation(
    population: list[Candidate],
    offspring: list[Candidate],
    *,
    population_size: int,
    rng: random.Random,
    selection_mode: SelectionMode = LEXICASE_SELECTION,
    fitness_tolerance: float = GAME_PERFORMANCE_TIE_TOLERANCE,
) -> list[Candidate]:
    """Select a fixed-size generation from parents and offspring jointly.

    Lexicase remains the default fixed-roster behavior. Scalar selection keeps
    complete score tiers in descending order. If the population boundary cuts
    through a tier, seeded farthest-first semantic novelty chooses only within
    that tier; semantics can never promote a candidate from a worse tier.
    """

    if population_size < 0:
        raise ValueError("population_size must be non-negative.")
    _validate_selection_mode(selection_mode)
    if selection_mode == GAME_PERFORMANCE_SELECTION:
        _validate_fitness_tolerance(fitness_tolerance)

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

    if selection_mode == GAME_PERFORMANCE_SELECTION:
        return _select_scalar_survivors(
            available,
            population_size=population_size,
            rng=rng,
            tolerance=fitness_tolerance,
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
    tolerance: float,
) -> list[Candidate]:
    """Fill survivors from non-chained scalar-fitness tiers."""

    selected: list[Candidate] = []
    remaining = list(available)
    while len(selected) < population_size:
        tier = _top_score_tier(remaining, tolerance=tolerance)
        open_slots = population_size - len(selected)
        if len(tier) <= open_slots:
            # Preserve stable parent-then-offspring input order when the whole
            # tier survives. Semantic evidence is unnecessary because no tied
            # candidate is being discarded.
            selected.extend(tier)
            tier_ids = {candidate.id for candidate in tier}
            remaining = [candidate for candidate in remaining if candidate.id not in tier_ids]
            continue
        selected.extend(
            _semantic_subset(
                tier,
                count=open_slots,
                references=selected,
                rng=rng,
            )
        )
    return selected


def _top_score_tier(
    candidates: list[Candidate],
    *,
    tolerance: float,
) -> list[Candidate]:
    """Return one tier anchored at the current maximum, without score chaining."""

    maximum = max(_game_performance(candidate) for candidate in candidates)
    return [
        candidate
        for candidate in candidates
        if maximum - _game_performance(candidate) <= tolerance
    ]


def _semantic_subset(
    candidates: list[Candidate],
    *,
    count: int,
    references: list[Candidate],
    rng: random.Random,
) -> list[Candidate]:
    """Choose a seeded max-min semantic subset from one fitness tier."""

    chosen: list[Candidate] = []
    remaining = list(candidates)
    while len(chosen) < count:
        candidate = _choose_semantically_novel(
            remaining,
            [*references, *chosen],
            rng,
        )
        chosen.append(candidate)
        remaining = [item for item in remaining if item.id != candidate.id]
    return chosen


def _choose_semantically_novel(
    candidates: list[Candidate],
    references: list[Candidate],
    rng: random.Random,
) -> Candidate:
    """Choose maximum min-distance, falling back when comparison is unavailable."""

    if not candidates:
        raise ValueError("Cannot select from an empty candidate tier.")

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
        best_distance = max(distance for _, distance in scored)
        best = [candidate for candidate, distance in scored if distance == best_distance]
        return rng.choice(best)

    # With no comparable reference, seed farthest-first selection from a
    # complete summary. Missing/incompatible summaries are fallback only.
    complete = [candidate for candidate in candidates if _semantic_summary(candidate) is not None]
    return rng.choice(complete or candidates)


def _semantic_summary(candidate: Candidate) -> SemanticSummary | None:
    value = getattr(candidate, "semantic_signature", None)
    if not isinstance(value, Mapping) or value.get("status") != "complete":
        return None
    dataset_id = value.get("dataset_id")
    probe_ids = value.get("probe_ids")
    action_hashes = value.get("action_hashes")
    global_hash = value.get("global_hash")
    if not isinstance(dataset_id, str) or not dataset_id:
        return None
    if not isinstance(global_hash, str) or not global_hash:
        return None
    if not isinstance(probe_ids, (list, tuple)) or not isinstance(action_hashes, (list, tuple)):
        return None
    if not probe_ids or len(probe_ids) != len(action_hashes):
        return None
    if any(not isinstance(item, str) or not item for item in probe_ids):
        return None
    if any(not isinstance(item, str) or not item for item in action_hashes):
        return None
    ordered_probes = tuple(probe_ids)
    if len(set(ordered_probes)) != len(ordered_probes):
        return None
    return dataset_id, ordered_probes, tuple(action_hashes), global_hash


def _semantic_distance(
    left: SemanticSummary,
    right: SemanticSummary,
) -> float | None:
    left_dataset, left_probes, left_actions, _ = left
    right_dataset, right_probes, right_actions, _ = right
    if left_dataset != right_dataset or left_probes != right_probes:
        return None
    mismatches = sum(a != b for a, b in zip(left_actions, right_actions, strict=True))
    return mismatches / len(left_actions)


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
    from .opponent_cases import aggregate_game_performance
    return aggregate_game_performance(candidate.fitness_objectives)
