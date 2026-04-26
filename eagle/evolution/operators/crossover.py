"""Crossover methods for the genetic algorithm."""

from __future__ import annotations

from ...utils.component_pool import ComponentPool
from ...utils.individual import Individual


class Crossover:
    """Crossover operators that recombine flattened component indices."""

    @staticmethod
    def uniform_crossover(component_pool: ComponentPool, parent1: Individual, parent2: Individual) -> Individual:
        """Pick each evolving component slot independently from either parent."""
        import random
        child = Individual()
        child.game_rule = parent1.game_rule
        child.component_indices = {}
        child.static_components = {}
        child.strategy = {}

        p1_indices = dict(getattr(parent1, "component_indices", {}) or getattr(parent1, "static_components", {}) or {})
        p2_indices = dict(getattr(parent2, "component_indices", {}) or getattr(parent2, "static_components", {}) or {})
        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                selected_value = 0
            elif category in p1_indices and category in p2_indices:
                selected_value = random.choice([p1_indices[category], p2_indices[category]])
            elif category in p1_indices:
                selected_value = p1_indices[category]
            elif category in p2_indices:
                selected_value = p2_indices[category]
            else:
                selected_value = component_pool.get_random_component_index(category)
            child.set_component_index(category, selected_value)
        return child
    
