"""Single-objective GA implementation for component prompt evolution."""

from __future__ import annotations

import random
from typing import List

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool

from .base import EA
from .individual import Individual


def _normalize_single_objective_fitness(fitness) -> list[float]:
    """Normalize any fitness payload into a fixed-width single-objective vector."""
    if fitness is None:
        return [0.0]
    if isinstance(fitness, (int, float)):
        return [float(fitness)]
    if isinstance(fitness, dict):
        iterable = list(fitness.values())
        if not iterable:
            return [0.0]
        try:
            return [float(iterable[0])]
        except (TypeError, ValueError):
            return [0.0]
    try:
        iterable = list(fitness)
    except TypeError:
        return [0.0]
    if not iterable:
        return [0.0]
    try:
        return [float(iterable[0])]
    except (TypeError, ValueError):
        return [0.0]


class GA(EA):
    """Single-objective GA using score-only selection and survival."""

    default_parent_selection_operator_name = "ga_fitness_tournament"
    default_env_selection_operator_name = "ga_fitness_elitism"

    def __init__(
        self,
        config: EAConfig,
        component_pool: ComponentPool,
        opponent_list: List[str],
    ):
        super().__init__(config, component_pool, opponent_list)

    def _fitness0(self, individual: Individual) -> float:
        return _normalize_single_objective_fitness(individual.fitness)[0]

    def _better_parent(self, ind1: Individual, ind2: Individual) -> Individual:
        """Binary tournament winner by fitness[0], ties broken randomly."""
        f1 = self._fitness0(ind1)
        f2 = self._fitness0(ind2)
        if f1 > f2:
            return ind1
        if f2 > f1:
            return ind2
        return random.choice([ind1, ind2])

    def _mutation_parent_snapshot(self, parent: Individual) -> float:
        """Capture the parent score used by GA mutation feedback."""
        return self._fitness0(parent)

    def _mutation_improved(self, child: Individual, parent_snapshot) -> bool:
        """Return whether a mutation child improved on fitness[0]."""
        return self._fitness0(child) > float(parent_snapshot)

    def _log_generation(
        self,
        generation: int,
        offspring: List[Individual],
        generation_context,
        log_dir: str,
    ) -> None:
        """Write the GA generation snapshot."""
        best_individual = max(self.population, key=self._fitness0)
        self.log_single_objective_generation(log_dir, generation, best_individual)
        self.save_component_pool(log_dir)
        self.current_generation = generation
