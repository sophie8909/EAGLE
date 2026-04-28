"""Crossover methods for the genetic algorithm."""

from __future__ import annotations

import random

from eagle.utils.component_pool import ComponentPool
from .individual import Individual


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
        child.static_components = {}
        child.strategy = {}

        p1_indices = dict(getattr(parent1, "component_indices", {}) or {})
        p2_indices = dict(getattr(parent2, "component_indices", {}) or {})

        if not p1_indices:
            p1_indices = dict(getattr(parent1, "static_components", {}) or {})
        if not p2_indices:
            p2_indices = dict(getattr(parent2, "static_components", {}) or {})

        for category in component_pool.component_keys:
            if category in component_pool.non_evolving_component_keys:
                selected_value = 0
            elif category in p1_indices and category in p2_indices:
                selected_value = random.choice(
                    [int(p1_indices[category]), int(p2_indices[category])]
                )
            elif category in p1_indices:
                selected_value = int(p1_indices[category])
            elif category in p2_indices:
                selected_value = int(p2_indices[category])
            else:
                selected_value = component_pool.get_random_component_index(category)

            child.set_component_index(category, selected_value)

        child._sync_component_indices()
        return child