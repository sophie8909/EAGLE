"""Crossover methods for the genetic algorithm."""

from __future__ import annotations

from ...utils.component_pool import ComponentPool
from ...utils.individual import Individual


class Crossover:
    """Crossover operators that recombine parent strategy indices into children."""

    @staticmethod
    def uniform_crossover(component_pool: ComponentPool, parent1: Individual, parent2: Individual) -> Individual:
        """Pick each strategy slot independently from either parent."""
        import random
        child = Individual()
        p1_strategy = parent1.strategy or {}
        p2_strategy = parent2.strategy or {}
        child.game_rule = parent1.game_rule
        child.legacy_components = {}

        static_keys = sorted(
            set((parent1.legacy_components or {}).keys()) | set((parent2.legacy_components or {}).keys())
        )
        for category in static_keys:
            p1_has = category in (parent1.legacy_components or {})
            p2_has = category in (parent2.legacy_components or {})
            if p1_has and p2_has:
                selected_value = random.choice(
                    [parent1.legacy_components[category], parent2.legacy_components[category]]
                )
            elif p1_has:
                selected_value = parent1.legacy_components[category]
            elif p2_has:
                selected_value = parent2.legacy_components[category]
            else:
                selected_value = component_pool.get_random_component_index(category)
            child.set_component_index(category, selected_value)

        child.strategy = {}
        for strategy_key in component_pool.strategy_keys:
            if strategy_key in p1_strategy and strategy_key in p2_strategy:
                child.strategy[strategy_key] = random.choice(
                    [p1_strategy[strategy_key], p2_strategy[strategy_key]]
                )
            elif strategy_key in p1_strategy:
                child.strategy[strategy_key] = p1_strategy[strategy_key]
            elif strategy_key in p2_strategy:
                child.strategy[strategy_key] = p2_strategy[strategy_key]
            else:
                child.strategy[strategy_key] = component_pool.get_random_strategy_component_index(strategy_key)
        return child
    
    @staticmethod
    def llm_crossover(component_pool: ComponentPool, parent1: Individual, parent2: Individual) -> Individual:
        """Temporary placeholder that falls back to uniform crossover until implemented."""
        # TODO: Implement an LLM-based crossover that writes merged strategy
        # components back into the component pool and stores valid component
        # indices on the child. For now we explicitly fall back to the stable
        # uniform crossover path so this unfinished method cannot corrupt
        # offspring strategy values.
        return Crossover.uniform_crossover(component_pool, parent1, parent2)


