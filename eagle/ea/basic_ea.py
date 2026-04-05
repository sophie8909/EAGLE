"""
Base class for evolutionary algorithms.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import List

from .config import EAConfig
from .component_pool import ComponentPool
from .individual import Individual
from .evaluate import Evaluator
from .parent_selection import ParentSelection
from .crossover import Crossover
from .mutation import Mutation
from .environment_selection import EnvironmentSelection
from .fitness_recorder import FitnessRecorder
from .fitness_utils import normalize_fitness
from .final_evaluation import run_final_test_suite

class EA:
    def __init__(self, config: EAConfig, component_pool: ComponentPool, opponent_list: List[str]):
        self.config = config
        self.component_pool = component_pool
        self.opponent_list = opponent_list
        self.population = self.initialize_population()
        self.current_log_dir: Path | None = None
        self.fitness_recorder: FitnessRecorder | None = None
        self.current_generation = 0


    def save_config(self, log_dir: str):
        import json
        config_file = f"{log_dir}/config.json"
        with open(config_file, "w") as f:
            json.dump(self.config.__dict__, f, indent=4)

    def initialize_population(self) -> List[Individual]:
        # Initialize a population of random solutions based on the component pool
        individuals = []
        for _ in range(self.config.population_size):
            individual = Individual() 
            individual.initialize_randomly(self.component_pool)
            individuals.append(individual)
        return individuals
    
    def create_log_folder(self) -> str:
        # Reuse the existing run directory when initialization has already happened
        # before `run()`, so config and generation logs stay under the same folder.
        if self.current_log_dir is not None:
            return str(self.current_log_dir)

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = f"logs/{timestamp}"
        import os
        os.makedirs(log_dir, exist_ok=True)
        self.current_log_dir = Path(log_dir)
        self.fitness_recorder = FitnessRecorder(self.current_log_dir, self.config)
        return log_dir

    def get_profile_log_path(self) -> Path:
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")
        return self.current_log_dir / "profiles.jsonl"

    def get_generation_profile_log_path(self) -> Path:
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")
        return self.current_log_dir / "generation_profiles.jsonl"
    
    
    def log_single_objective_generation(self, log_dir: str, generation: int, best_individual: Individual):
        # Log the population and their fitnesses for the current generation
        log_path = f"{log_dir}/generation_{generation+1}.txt"
        with open(log_path, "w") as f:
                f.write(f"Generation {generation+1}\n")
                f.write(f"Best Individual: {best_individual}\n")
                f.write(f"Prompt:\n{Evaluator(self.component_pool, self.config).construct_prompt(best_individual)}\n")
                f.write(f"Fitness: {best_individual.fitness}\n")
                f.write("\nPopulation:\n")
                for ind in self.population:
                    f.write(f"{ind} - Fitness: {ind.fitness}\n")

    def log_multi_objective_generation(self, log_dir: str, generation: int, pareto_fronts: List[List[Individual]]):
        # Log the Pareto fronts and their fitnesses for the current generation
        log_path = f"{log_dir}/generation_{generation+1}_mo.txt"
        with open(log_path, "w") as f:
            f.write(f"Generation {generation+1} - Multi-objective Optimization\n")
            for i, front in enumerate(pareto_fronts):
                f.write(f"\nPareto Front {i+1}:\n")
                for ind in front:
                    f.write(f"{ind} - Fitness: {ind.fitness}\n")
                    f.write(f"Prompt:\n{Evaluator(self.component_pool, self.config).construct_prompt(ind)}\n")
            
    def save_component_pool(self, log_dir: str):
        import json
        components_file = f"{log_dir}/component_pool.json"
        with open(components_file, "w") as f:
            json.dump(self.component_pool.components, f, indent=4)


    def select_parents(self) -> List[Individual]:
        # Select parents from the population using the configured selection method (e.g., binary tournament)
        if self.config.selection_method == "random":
            idx1 = ParentSelection.random_selection(self.population)
            idx2 = ParentSelection.random_selection(self.population)
            return self.population[idx1], self.population[idx2]

        if self.config.selection_method == "tournament":
            fitnesses = [normalize_fitness(ind.fitness) for ind in self.population]
            idx1 = ParentSelection.tournament_selection(
                self.population,
                fitnesses,
                min(self.config.tournament_size, len(self.population)),
            )
            idx2 = ParentSelection.tournament_selection(
                self.population,
                fitnesses,
                min(self.config.tournament_size, len(self.population)),
            )
            return self.population[idx1], self.population[idx2]

        raise ValueError(f"Unsupported selection_method: {self.config.selection_method}")

    def crossover(self, parent1: Individual, parent2: Individual) -> Individual:
        # Perform crossover between two parents to produce an offspring solution (e.g., uniform crossover)
        if self.config.crossover_method == "uniform":
            offspring = Crossover.uniform_crossover(self.component_pool, parent1, parent2)
            # assign fitness init with parent fitness to save time for surrogate evaluation. 
            # the real fitness will be assigned after real evaluation.
            print(parent1.fitness, parent2.fitness)
            offspring.fitness = [
                (left + right) / 2
                for left, right in zip(parent1.fitness, parent2.fitness)
            ]
            return offspring
        raise ValueError(f"Unsupported crossover_method: {self.config.crossover_method}")
    
    def mutate(self, individual: Individual) -> Individual:
        # Apply mutation to a solution with the configured mutation rate (e.g., mutate_solution function)
        if self.config.mutation_rate > 0:
            if random.random() < 0.5:
                mutated_individual = Mutation.mutate_component_from_pool(individual, self.component_pool, self.config.mutation_rate)
            else:
                mutated_individual = Mutation.mutate_component_with_llm(individual, self.component_pool, self.config.mutation_rate)
    
            return mutated_individual
        return individual   
    
    def real_evaluation(self, individual: Individual, opponent: str, generation: int | None = None):
        # Evaluate the fitness of a solution by running it in MicroRTS and measuring performance
        evaluator = Evaluator(self.component_pool, self.config)
        evaluator.evaluate(
            individual,
            use_real_evaluation=True,
            opponent=opponent,
            profile_output_path=self.get_profile_log_path(),
            generation=generation,
            fitness_recorder=self.fitness_recorder,
        )

    
    def surrogate_evaluation(self, individual: Individual, generation: int | None = None):
        evaluator = Evaluator(self.component_pool, self.config)
        evaluator.evaluate(
            individual,
            use_real_evaluation=False,
            opponent=None,
            profile_output_path=self.get_profile_log_path(),
            generation=generation,
            fitness_recorder=self.fitness_recorder,
        )

    
    def run_final_test(self):
        # get the last generation log file
        # Test the best evolved solution against a set of opponents and log the results
        run_final_test_suite(self.current_log_dir, self.current_generation)
