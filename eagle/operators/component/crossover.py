"""Crossover methods for the genetic algorithm."""

from __future__ import annotations

import random

from eagle.utils.component_pool import ComponentPool
from eagle.evolution.component.individual import Individual


class Crossover:
    """Crossover operators that recombine flattened component indices."""

    @staticmethod
    def uniform_crossover(
        component_pool: ComponentPool,
        parent1: Individual,
        parent2: Individual,
    ) -> Individual:
        """Pick each evolving component slot independently from either parent."""
        child = Individual()
        child.game_rule = int(getattr(parent1, "game_rule", 0))
        child.component_indices = {}

        p1_indices = dict(getattr(parent1, "component_indices", {}) or {})
        p2_indices = dict(getattr(parent2, "component_indices", {}) or {})

        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                selected_value = 0
            elif category in p1_indices and category in p2_indices:
                selected_value = random.choice(
                    [parent1.get_component_index(category), parent2.get_component_index(category)]
                )
            elif category in p1_indices:
                selected_value = parent1.get_component_index(category)
            elif category in p2_indices:
                selected_value = parent2.get_component_index(category)
            else:
                selected_value = component_pool.get_random_component_index(category)

            child.set_component_index(category, selected_value)
            p1_enabled = parent1.is_component_enabled(category) if category in p1_indices else 1
            p2_enabled = parent2.is_component_enabled(category) if category in p2_indices else 1
            child.set_component_enabled(category, random.choice([p1_enabled, p2_enabled]))

        child._sync_component_indices()
        return child
