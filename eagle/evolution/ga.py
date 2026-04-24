"""
Genetic Algorithm implementation for evolving prompt components.
This module defines the GA class, which implements a genetic algorithm to optimize prompt components for guiding agent behavior in MicroRTS. The GA class initializes a population of candidate solutions, evaluates their fitness based on performance in MicroRTS, and applies selection, crossover, and mutation operations to evolve better solutions over multiple generations. The GA can be configured with various parameters such as population size, number of generations, mutation rate, and selection method.
"""

from __future__ import annotations

import random
from typing import List

from .basic_ea import EA
from ..utils.component_pool import ComponentPool
from ..utils.individual import Individual
from ..config import EAConfig
from ..evolution.operators.environment_selection import EnvironmentSelection
from ..utils.fitness_utils import fitness_key
from ..utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl


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
        checkpoint = self.load_checkpoint()

        last_5_fitness = []

        self._evaluate_initial_population(checkpoint)

        start_generation = checkpoint.get("generation", 0) + (1 if checkpoint.get("phase") == "generation_complete" else 0)

        for generation in range(start_generation, self.config.num_generations):
            generation_stats: dict[str, float] = {}
            new_population = self.deserialize_population(checkpoint.get("offspring")) if checkpoint.get("generation") == generation else []

            with timer("offspring_generation_time", generation_stats):
                for _ in range(len(new_population), self.config.population_size):
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
                    self.save_checkpoint(
                        self.build_checkpoint_state(
                            phase="generation_generation",
                            generation=generation,
                            offspring=new_population,
                            meta={"generated_offspring_count": len(new_population)},
                        )
                    )

            with timer("offspring_evaluation_time", generation_stats):
                start_idx = checkpoint.get("meta", {}).get("evaluated_offspring_count", 0) if checkpoint.get("generation") == generation else 0
                for index in range(start_idx, len(new_population)):
                    individual = new_population[index]
                    if random.random() < 0.5:
                        random_opponent = random.choice(self.opponent_list)
                        self.real_evaluation(individual, random_opponent, generation=generation)
                    else:
                        self.surrogate_evaluation(individual, generation=generation)
                    self.save_checkpoint(
                        self.build_checkpoint_state(
                            phase="generation_evaluation",
                            generation=generation,
                            offspring=new_population,
                            meta={"evaluated_offspring_count": index + 1},
                        )
                    )

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
            self.current_generation = generation
            self.print_population_snapshot(f"generation {generation + 1} survivors")
            self.save_checkpoint(
                self.build_checkpoint_state(
                    phase="generation_complete",
                    generation=generation,
                    meta={"best_individual_id": getattr(best_individual, "id", None)},
                )
            )

            last_5_fitness.append(best_individual.fitness)
            if len(last_5_fitness) > 5:
                last_5_fitness.pop(0)
            if len(last_5_fitness) == 5 and all(fitness == last_5_fitness[0] for fitness in last_5_fitness):
                print(f"Early stopping at generation {generation+1} due to no improvement in fitness.")
                break

            checkpoint = self.build_checkpoint_state(
                phase="generation_complete",
                generation=generation,
                meta={"best_individual_id": getattr(best_individual, "id", None)},
            )

        # Store the components_pool in a file for later analysis
        self.save_component_pool(log_dir)
