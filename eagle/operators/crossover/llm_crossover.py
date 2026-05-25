"""LLM semantic crossover plugin."""

from __future__ import annotations

import random

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseCrossover
from eagle.operators.crossover import support


class LLMCrossover(BaseCrossover):
    """Merge parent components at the semantic text level using an LLM."""

    name = "llm_crossover"

    def __call__(self, component_pool, parent1, parent2, config) -> Individual:
        """Return one child whose evolving components are semantic parent merges."""
        child = Individual()
        child.game_rule = int(getattr(parent1, "game_rule", 0))
        total_llm_time = 0.0
        merged_components: list[str] = []

        for component_key in component_pool.component_keys:
            if component_key in getattr(component_pool, "CODE_MANAGED_COMPONENT_KEYS", set()):
                continue
            if component_key in component_pool.non_evolving_component_keys:
                child.set_component_index(component_key, 0)
                child.set_component_enabled(component_key, 1)
                continue

            if (
                component_key in getattr(parent1, "component_indices", {})
                and component_key in getattr(parent2, "component_indices", {})
            ):
                merged_index, elapsed = support.combine_parent_component(
                    component_pool,
                    component_key,
                    parent1,
                    parent2,
                )
                total_llm_time += elapsed
                merged_components.append(component_key)
            elif component_key in getattr(parent1, "component_indices", {}):
                merged_index = parent1.get_component_index(component_key)
            elif component_key in getattr(parent2, "component_indices", {}):
                merged_index = parent2.get_component_index(component_key)
            else:
                merged_index = component_pool.get_random_component_index(component_key)

            child.set_component_index(component_key, merged_index)
            enabled = random.choice(
                [
                    parent1.is_component_enabled(component_key),
                    parent2.is_component_enabled(component_key),
                ]
            )
            child.set_component_enabled(component_key, enabled)

        child._sync_component_indices()
        child.training_examples = support.uniform_crossover_training_examples(
            component_pool,
            parent1,
            parent2,
            config,
        )
        child.ea_llm_call_time = total_llm_time
        child.crossover_metadata = {
            "crossover_mode": "llm_crossover",
            "merged_components": merged_components,
        }
        return support.average_parent_fitness(child, parent1, parent2)
