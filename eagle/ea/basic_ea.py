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
    """Shared scaffolding for the single- and multi-objective EA variants.

    This base class owns the common runtime state for a training run:
    population, log directory, fitness recorder, and the standard operators
    (selection, crossover, mutation, and evaluation). Concrete algorithms such
    as GA and NSGA-II provide the outer loop and survivor-selection policy.
    """

    def __init__(self, config: EAConfig, component_pool: ComponentPool, opponent_list: List[str]):
        """Initialize shared EA state and create the initial random population."""
        self.config = config
        self.component_pool = component_pool
        self.opponent_list = opponent_list
        self.population = self.initialize_population()
        self.current_log_dir: Path | None = None
        self.fitness_recorder: FitnessRecorder | None = None
        self.current_generation = 0


    def save_config(self, log_dir: str):
        """Persist the run configuration next to the generated logs."""
        import json
        config_file = f"{log_dir}/config.json"
        with open(config_file, "w") as f:
            json.dump(self.config.__dict__, f, indent=4)

    def initialize_population(self) -> List[Individual]:
        """Create the starting population by sampling strategy indices at random."""
        individuals = []
        for _ in range(self.config.population_size):
            individual = Individual() 
            individual.initialize_randomly(self.component_pool)
            individuals.append(individual)
        return individuals
    
    def create_log_folder(self) -> str:
        """Create or reuse the per-run log directory and initialize history recording."""
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
        """Return the JSONL path used for per-individual evaluation profiles."""
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")
        return self.current_log_dir / "profiles.jsonl"

    def get_generation_profile_log_path(self) -> Path:
        """Return the JSONL path used for generation-level profile summaries."""
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")
        return self.current_log_dir / "generation_profiles.jsonl"
    
    
    def log_single_objective_generation(self, log_dir: str, generation: int, best_individual: Individual):
        """Write a human-readable generation snapshot for the GA workflow."""
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
        """Write a human-readable Pareto-front snapshot for the NSGA-II workflow."""
        log_path = f"{log_dir}/generation_{generation+1}_mo.txt"
        with open(log_path, "w") as f:
            f.write(f"Generation {generation+1} - Multi-objective Optimization\n")
            for i, front in enumerate(pareto_fronts):
                f.write(f"\nPareto Front {i+1}:\n")
                for ind in front:
                    f.write(f"{ind} - Fitness: {ind.fitness}\n")
                    f.write(f"Prompt:\n{Evaluator(self.component_pool, self.config).construct_prompt(ind)}\n")
            
    def save_component_pool(self, log_dir: str):
        """Store the evolving component pool so later analysis can reproduce runs."""
        import json
        components_file = f"{log_dir}/component_pool.json"
        with open(components_file, "w") as f:
            json.dump(self.component_pool.components, f, indent=4)


    def select_parents(self) -> List[Individual]:
        """Choose two parents according to the configured parent-selection rule."""
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
        """Create one child and seed its fitness with the parents' average values."""
        if self.config.crossover_method == "uniform":
            offspring = Crossover.uniform_crossover(self.component_pool, parent1, parent2)
            # Seed surrogate evaluation with a cheap inherited estimate. Real
            # evaluation later overwrites the child with game-derived scores.
            print(parent1.fitness, parent2.fitness)
            offspring.fitness = [
                (left + right) / 2
                for left, right in zip(parent1.fitness, parent2.fitness)
            ]
            return offspring
        raise ValueError(f"Unsupported crossover_method: {self.config.crossover_method}")
    
    def mutate(self, individual: Individual) -> Individual:
        """Apply one of the configured mutation strategies to a copied child."""
        if self.config.mutation_rate > 0:
            if random.random() < 0.5:
                mutated_individual = Mutation.mutate_component_from_pool(individual, self.component_pool, self.config.mutation_rate)
            else:
                mutated_individual = Mutation.mutate_component_with_llm(individual, self.component_pool, self.config.mutation_rate)
    
            return mutated_individual
        return individual   
    
    def real_evaluation(self, individual: Individual, opponent: str, generation: int | None = None):
        """Run a full MicroRTS game and write the resulting fitness back to the individual."""
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
        """Run the configured cheap evaluator instead of a full game simulation."""
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
        """Replay the last saved generation against the configured final-test opponents."""
        run_final_test_suite(self.current_log_dir, self.current_generation)
