"""
Genetic Algorithm implementation for evolving prompt components.
This module defines the GA class, which implements a genetic algorithm to optimize prompt components for guiding agent behavior in MicroRTS. The GA class initializes a population of candidate solutions, evaluates their fitness based on performance in MicroRTS, and applies selection, crossover, and mutation operations to evolve better solutions over multiple generations. The GA can be configured with various parameters such as population size, number of generations, mutation rate, and selection method.
"""

from __future__ import annotations

import random
from typing import List

from .basic_ea import EA
from .component_pool import ComponentPool
from .individual import Individual
from .config import EAConfig
from .environment_selection import EnvironmentSelection
from .fitness_utils import fitness_key
from .profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl


class GA(EA):
    """Single-objective evolutionary loop using lexicographic fitness ordering."""

    def __init__(self, config: EAConfig, component_pool: ComponentPool, opponent_list: List[str]):
        """Initialize the GA with the shared EA base state."""
        super().__init__(config, component_pool, opponent_list)

    def environment_selection(self, current_population: List[Individual], new_population: List[Individual]) -> List[Individual]:
        """Choose survivors for the next generation using the configured policy."""
        if self.config.environment_selection_method == "elitism":
            selected_population = EnvironmentSelection.elitism_selection(current_population, new_population, self.config.population_size)
            return selected_population
        raise ValueError(
            f"Unsupported environment_selection_method: {self.config.environment_selection_method}"
        )

    def run(self):
        """Run the standard GA loop from initialization through early stopping."""
        log_dir = self.create_log_folder()

        last_5_fitness = []

        with timer("initial_population_evaluation_time", {}):
            for individual in self.population:
                self.real_evaluation(individual, random.choice(self.opponent_list), generation=0)

        for generation in range(self.config.num_generations):
            generation_stats: dict[str, float] = {}
            new_population = []

            with timer("offspring_generation_time", generation_stats):
                for _ in range(self.config.population_size):
                    with timer("parent_selection_time", generation_stats):
                        parent1, parent2 = self.select_parents()

                    offspring_stats: dict[str, float] = {}
                    with timer("crossover_time", offspring_stats):
                        offspring = self.crossover(parent1, parent2)
                    with timer("mutation_time", offspring_stats):
                        mutated_offspring = self.mutate(offspring)

                    mutated_offspring.operator_profile = {
                        "crossover_time": offspring_stats.get("crossover_time", 0.0),
                        "mutation_time": offspring_stats.get("mutation_time", 0.0),
                        "EA_operator_time": offspring_stats.get("crossover_time", 0.0) + offspring_stats.get("mutation_time", 0.0),
                        "ea_llm_call_time": getattr(mutated_offspring, "ea_llm_call_time", 0.0),
                    }
                    new_population.append(mutated_offspring)

            with timer("offspring_evaluation_time", generation_stats):
                for individual in new_population:
                    if random.random() < 0.5:
                        random_opponent = random.choice(self.opponent_list)
                        self.real_evaluation(individual, random_opponent, generation=generation)
                    else:
                        self.surrogate_evaluation(individual, generation=generation)

            with timer("survivor_selection_time", generation_stats):
                self.population = self.environment_selection(self.population, new_population)

            summarize_total_eval_time(generation_stats)
            generation_record = build_base_record(
                generation=generation,
                individual_id=None,
                record_type="generation",
            )
            generation_record.update(
                {
                    "generation_time": (
                        generation_stats.get("parent_selection_time", 0.0)
                        + generation_stats.get("offspring_generation_time", 0.0)
                        + generation_stats.get("offspring_evaluation_time", 0.0)
                        + generation_stats.get("survivor_selection_time", 0.0)
                    ),
                    "parent_selection_time": generation_stats.get("parent_selection_time", 0.0),
                    "offspring_generation_time": generation_stats.get("offspring_generation_time", 0.0),
                    "offspring_evaluation_time": generation_stats.get("offspring_evaluation_time", 0.0),
                    "survivor_selection_time": generation_stats.get("survivor_selection_time", 0.0),
                    "population_size": len(self.population),
                    "offspring_count": len(new_population),
                    "log_dir": log_dir,
                }
            )
            write_jsonl(generation_record, self.get_generation_profile_log_path())

            # Save the best solution of the current generation
            best_individual = max(self.population, key=lambda ind: fitness_key(ind.fitness))

            self.log_single_objective_generation(log_dir, generation, best_individual)

            last_5_fitness.append(best_individual.fitness)
            if len(last_5_fitness) > 5:
                last_5_fitness.pop(0)
            if len(last_5_fitness) == 5 and all(fitness == last_5_fitness[0] for fitness in last_5_fitness):
                print(f"Early stopping at generation {generation+1} due to no improvement in fitness.")
                break

        # Store the components_pool in a file for later analysis
        self.save_component_pool(log_dir)
