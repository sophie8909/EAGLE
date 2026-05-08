"""Uniform component crossover plugin."""

from __future__ import annotations

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseCrossover
from eagle.operators.component.crossover import Crossover
from eagle.operators.component.mutation import Mutation


class UniformCrossover(BaseCrossover):
    """Recombine each component independently from either parent."""

    name = "uniform"

    def __call__(self, component_pool, parent1, parent2, config) -> Individual:
        """Return one crossover child with optional strategy repair."""
        offspring = Individual.from_existing(
            Crossover.uniform_crossover(component_pool, parent1, parent2)
        )
        if getattr(config, "crossover_repair_enabled", False):
            offspring = Individual.from_existing(
                Mutation.repair_strategy_after_crossover(
                    offspring,
                    component_pool,
                )
            )
        offspring.fitness = [
            (left + right) / 2
            for left, right in zip(parent1.fitness, parent2.fitness)
        ]
        return offspring
