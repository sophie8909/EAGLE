"""Uniform component crossover plugin."""

from __future__ import annotations

import random

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseCrossover
from eagle.operators.crossover import support


class UniformCrossover(BaseCrossover):
    """Recombine each component independently from either parent."""

    name = "uniform"

    def __call__(self, component_pool, parent1, parent2, config) -> Individual:
        """Return one crossover child with optional strategy repair."""
        offspring = Individual()
        offspring.game_rule = int(getattr(parent1, "game_rule", 0))

        parent1_indices = dict(getattr(parent1, "component_indices", {}) or {})
        parent2_indices = dict(getattr(parent2, "component_indices", {}) or {})

        for component_key in component_pool.component_keys:
            if component_key in component_pool.non_evolving_component_keys:
                selected_value = 0
            elif component_key in parent1_indices and component_key in parent2_indices:
                selected_value = random.choice(
                    [
                        parent1.get_component_index(component_key),
                        parent2.get_component_index(component_key),
                    ]
                )
            elif component_key in parent1_indices:
                selected_value = parent1.get_component_index(component_key)
            elif component_key in parent2_indices:
                selected_value = parent2.get_component_index(component_key)
            else:
                selected_value = component_pool.get_random_component_index(component_key)

            offspring.set_component_index(component_key, selected_value)
            parent1_enabled = (
                parent1.is_component_enabled(component_key)
                if component_key in parent1_indices
                else 1
            )
            parent2_enabled = (
                parent2.is_component_enabled(component_key)
                if component_key in parent2_indices
                else 1
            )
            offspring.set_component_enabled(
                component_key,
                random.choice([parent1_enabled, parent2_enabled]),
            )

        offspring._sync_component_indices()
        if getattr(config, "crossover_repair_enabled", False):
            offspring = Individual.from_existing(
                support.repair_after_crossover(
                    offspring,
                    component_pool,
                )
            )
        return support.average_parent_fitness(offspring, parent1, parent2)
