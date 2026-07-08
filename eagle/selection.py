"""NSGA-II parent and survivor selection helpers."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .candidate import Candidate


@dataclass(frozen=True)
class SelectionContext:
    rng: random.Random


class Selection:
    """Select candidates using one configured selection method."""

    def __init__(self, *, method: str = "binary_tournament") -> None:
        self.method = method

    def select(self, population: list[Candidate], k: int, context: SelectionContext) -> list[Candidate]:
        if self.method == "binary_tournament":
            return [tournament_select(population, context.rng) for _ in range(k)]
        raise ValueError(f"Unknown selection method: {self.method}")


def tournament_select(population: list[Candidate], rng: random.Random) -> Candidate:
    """Pick a parent by comparing two random candidates."""

    # Tournament selection uses the better of two random candidates as a parent.
    if len(population) == 1:
        return population[0]
    first, second = rng.sample(population, 2)
    return better_candidate(first, second, rng)


def better_candidate(first: Candidate, second: Candidate, rng: random.Random) -> Candidate:
    rank_a = getattr(first, "pareto_rank", float("inf"))
    rank_b = getattr(second, "pareto_rank", float("inf"))
    if rank_a != rank_b:
        return first if rank_a < rank_b else second
    crowd_a = getattr(first, "crowding_distance", 0.0)
    crowd_b = getattr(second, "crowding_distance", 0.0)
    if crowd_a != crowd_b:
        return first if crowd_a > crowd_b else second
    if dominates(first, second):
        return first
    if dominates(second, first):
        return second
    return rng.choice([first, second])


def select_next_generation(
    population: list[Candidate],
    offspring: list[Candidate],
    *,
    population_size: int,
) -> list[Candidate]:
    combined = population + offspring
    fronts = non_dominated_sort(combined)
    next_generation: list[Candidate] = []
    for rank, front in enumerate(fronts):
        crowding_distance(front)
        for candidate in front:
            object.__setattr__(candidate, "metadata", {**candidate.metadata, "pareto_rank": rank})
        if len(next_generation) + len(front) <= population_size:
            next_generation.extend(front)
            continue
        remaining = population_size - len(next_generation)
        sorted_front = sorted(front, key=lambda item: getattr(item, "crowding_distance", 0.0), reverse=True)
        next_generation.extend(sorted_front[:remaining])
        break
    return next_generation


def assign_rank_and_crowding(population: list[Candidate]) -> list[list[Candidate]]:
    fronts = non_dominated_sort(population)
    for rank, front in enumerate(fronts):
        crowding_distance(front)
        for candidate in front:
            object.__setattr__(candidate, "metadata", {**candidate.metadata, "pareto_rank": rank})
            object.__setattr__(candidate, "pareto_rank", rank)
    return fronts


def dominates(first: Candidate, second: Candidate) -> bool:
    first_values = first.objective_vector()
    second_values = second.objective_vector()
    no_worse = all(a >= b for a, b in zip(first_values, second_values))
    better_once = any(a > b for a, b in zip(first_values, second_values))
    return no_worse and better_once


def non_dominated_sort(population: list[Candidate]) -> list[list[Candidate]]:
    """Group candidates into Pareto fronts, best front first."""

    # Pareto sorting puts non-dominated candidates in the first front.
    if not population:
        return []
    domination_count = [0] * len(population)
    dominated_solutions: list[list[int]] = [[] for _ in population]
    fronts: list[list[Candidate]] = []
    for i in range(len(population)):
        for j in range(i + 1, len(population)):
            if dominates(population[i], population[j]):
                dominated_solutions[i].append(j)
                domination_count[j] += 1
            elif dominates(population[j], population[i]):
                dominated_solutions[j].append(i)
                domination_count[i] += 1
    current_front = [i for i, count in enumerate(domination_count) if count == 0]
    while current_front:
        fronts.append([population[i] for i in current_front])
        next_front: list[int] = []
        for i in current_front:
            for j in dominated_solutions[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        current_front = next_front
    return fronts


def crowding_distance(front: list[Candidate]) -> list[float]:
    """Score how isolated each candidate is within one Pareto front."""

    # Crowding distance preserves spread along each objective.
    if not front:
        return []
    if len(front) <= 2:
        for candidate in front:
            object.__setattr__(candidate, "crowding_distance", float("inf"))
        return [float("inf")] * len(front)

    distances = {candidate.id: 0.0 for candidate in front}
    objective_count = len(front[0].objective_vector())
    for objective_index in range(objective_count):
        sorted_front = sorted(front, key=lambda item: item.objective_vector()[objective_index])
        distances[sorted_front[0].id] = float("inf")
        distances[sorted_front[-1].id] = float("inf")
        min_value = sorted_front[0].objective_vector()[objective_index]
        max_value = sorted_front[-1].objective_vector()[objective_index]
        denominator = max_value - min_value
        if denominator == 0:
            continue
        for index in range(1, len(sorted_front) - 1):
            candidate = sorted_front[index]
            if math.isinf(distances[candidate.id]):
                continue
            previous_value = sorted_front[index - 1].objective_vector()[objective_index]
            next_value = sorted_front[index + 1].objective_vector()[objective_index]
            distances[candidate.id] += (next_value - previous_value) / denominator

    for candidate in front:
        object.__setattr__(candidate, "crowding_distance", distances[candidate.id])
    return [distances[candidate.id] for candidate in front]


def best_candidate(population: list[Candidate]) -> Candidate | None:
    if not population:
        return None
    assign_rank_and_crowding(population)
    return sorted(
        population,
        key=lambda item: (
            getattr(item, "pareto_rank", float("inf")),
            -sum(item.objective_vector()),
            -getattr(item, "crowding_distance", 0.0),
        ),
    )[0]
