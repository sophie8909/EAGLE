"""Mutation methods for the genetic algorithm.
"""

from __future__ import annotations
import time
from .individual import Individual
from .component_pool import ComponentPool
from .llm import LLM

class Mutation:
    
    @staticmethod
    def mutate_component_from_pool(individual: Individual, component_pool: ComponentPool, mutation_rate: float) -> Individual:
        import random
        base_strategy = dict(individual.strategy or {})
        mutated_individual = individual.copy()
        mutated_individual.strategy = base_strategy.copy()

        for strategy_key in component_pool.strategy_keys:
            if random.random() < mutation_rate:
                # add or replace strategy component
                if random.random() < 0.5:
                    mutated_individual.strategy[strategy_key] = component_pool.get_random_strategy_component_index(strategy_key)
                # remove strategy component
                else:
                    if strategy_key in mutated_individual.strategy:
                        del mutated_individual.strategy[strategy_key]

        return mutated_individual
    
    @staticmethod
    def rewrite_component_with_llm(component: str, rewrite_instruction: str) -> tuple[str, float]:
        start = time.perf_counter()
        rewritten_role_component = LLM.ollama_rewrite_component(
            original_text=component,
            instruction=rewrite_instruction,
            model="llama3.1:8b",
        )
        elapsed = time.perf_counter() - start
        return rewritten_role_component, elapsed



    @staticmethod
    def mutate_component_with_llm(individual: Individual, component_pool: ComponentPool, mutation_rate: float) -> Individual:
        # using LLM rewrite

        import random
        base_strategy = dict(individual.strategy or {})
        mutated_individual = individual.copy()
        mutated_individual.strategy = base_strategy.copy()
        mutated_individual.ea_llm_call_time = 0.0

        rewrite_stragey_list = [
            "Rewrite this strategy",
            "Make this strategy more aggressive",
            "Make this strategy more defensive",
        ]

        # Strategy components mutation with LLM rewrite
        for i, strategy_key in enumerate(component_pool.strategy_keys):
            if random.random() < mutation_rate:
                rewrite_instruction = random.choice(rewrite_stragey_list)
                if strategy_key in base_strategy:
                    original_strategy_component_str = "\n".join(
                        component_pool.get_strategy_component(strategy_key, base_strategy[strategy_key])
                    )
                    rewritten_strategy_component_str, elapsed = Mutation.rewrite_component_with_llm(original_strategy_component_str, rewrite_instruction)
                    mutated_individual.ea_llm_call_time += elapsed
                    rewritten_strategy_component = component_pool.parse_component_str(rewritten_strategy_component_str)
                    new_strategy_index = component_pool.add_strategy_component(strategy_key, rewritten_strategy_component)
                    mutated_individual.strategy[strategy_key] = new_strategy_index

        return mutated_individual
