"""
Base class for evolutionary algorithms.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, List

from ..utils.checkpoint import CheckpointManager, deserialize_individual, serialize_individual
from ..config import EAConfig
from ..project import EAGLE_LOGS_DIR
from ..utils.component_pool import ComponentPool
from ..utils.individual import Individual
from ..evaluation.evaluator import Evaluator
from ..evolution.operators.parent_selection import ParentSelection
from ..evolution.operators.crossover import Crossover
from ..evolution.operators.mutation import Mutation
from ..evolution.operators.environment_selection import EnvironmentSelection
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.fitness_utils import normalize_fitness
from ..evaluation.final_test_runner import run_final_test_suite

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
        self.checkpoint_manager: CheckpointManager | None = None
        self.current_generation = 0


    def save_config(self, log_dir: str):
        """Persist the run configuration next to the generated logs."""
        import json
        config_file = f"{log_dir}/config.json"
        valid_fields = set(self.config.__dataclass_fields__.keys())
        with open(config_file, "w") as f:
            json.dump(
                {
                    key: value
                    for key, value in self.config.__dict__.items()
                    if key in valid_fields
                },
                f,
                indent=4,
            )

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
        log_dir = EAGLE_LOGS_DIR / timestamp
        log_dir.mkdir(parents=True, exist_ok=True)
        self.current_log_dir = log_dir
        self.fitness_recorder = FitnessRecorder(self.current_log_dir, self.config)
        self.checkpoint_manager = CheckpointManager(self.current_log_dir)
        return str(log_dir)

    def attach_log_dir(self, log_dir: str | Path) -> str:
        """Bind this EA instance to an existing log directory for resuming."""
        self.current_log_dir = Path(log_dir)
        self.current_log_dir.mkdir(parents=True, exist_ok=True)
        self.fitness_recorder = FitnessRecorder(self.current_log_dir, self.config)
        self.checkpoint_manager = CheckpointManager(self.current_log_dir)
        return str(self.current_log_dir)

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

    def serialize_population(self, population: List[Individual]) -> list[dict[str, Any]]:
        """Serialize a population into checkpoint-safe dictionaries."""
        return [serialize_individual(ind) for ind in population]

    def deserialize_population(self, payload: list[dict[str, Any]] | None) -> list[Individual]:
        """Restore checkpointed population entries back into runtime objects."""
        return [deserialize_individual(ind) for ind in (payload or [])]

    def save_checkpoint(self, state: dict[str, Any]) -> None:
        """Persist one checkpoint snapshot under the current run directory."""
        if self.checkpoint_manager is None:
            raise ValueError("Checkpoint manager has not been initialized yet.")
        self.checkpoint_manager.save_state(state)

    def load_checkpoint(self) -> dict[str, Any] | None:
        """Load the most recent checkpoint snapshot for this run, if present."""
        if self.checkpoint_manager is None:
            raise ValueError("Checkpoint manager has not been initialized yet.")
        return self.checkpoint_manager.load_state()

    def build_checkpoint_state(
        self,
        *,
        phase: str,
        generation: int,
        population: List[Individual] | None = None,
        offspring: List[Individual] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a JSON-serializable snapshot of the EA's current runtime state."""
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")

        return {
            "algorithm": self.config.algorithm,
            "phase": phase,
            "generation": generation,
            "log_dir": str(self.current_log_dir),
            "population": self.serialize_population(population if population is not None else self.population),
            "offspring": self.serialize_population(offspring or []),
            "meta": meta or {},
        }
    
    
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
                    evaluation_mode = getattr(ind, "evaluation_mode", None) or "unknown"
                    f.write(f"{ind} - Fitness: {ind.fitness} - EvalMode: {evaluation_mode}\n")
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

    def select_parent(self) -> Individual:
        """Choose exactly one parent according to the configured selection rule."""
        if self.config.selection_method == "random":
            return self.population[ParentSelection.random_selection(self.population)]

        if self.config.selection_method == "tournament":
            fitnesses = [normalize_fitness(ind.fitness) for ind in self.population]
            idx = ParentSelection.tournament_selection(
                self.population,
                fitnesses,
                min(self.config.tournament_size, len(self.population)),
            )
            return self.population[idx]

        raise ValueError(f"Unsupported selection_method: {self.config.selection_method}")

    def crossover(self, parent1: Individual, parent2: Individual) -> Individual:
        """Create one child and seed its fitness with the parents' average values."""
        if self.config.crossover == "uniform":
            offspring = Crossover.uniform_crossover(self.component_pool, parent1, parent2)
            if self.config.crossover_repair_enabled:
                offspring = Mutation.repair_strategy_after_crossover(
                    offspring,
                    self.component_pool,
                )
            # Seed surrogate evaluation with a cheap inherited estimate. Real
            # evaluation later overwrites the child with game-derived scores.
            offspring.fitness = [
                (left + right) / 2
                for left, right in zip(parent1.fitness, parent2.fitness)
            ]
            return offspring
        raise ValueError(f"Unsupported crossover: {self.config.crossover}")
    
    def mutate(self, individual: Individual) -> Individual:
        """Apply one of the configured mutation strategies to a copied child."""
        mutated_individual = Mutation.mutate_strategy(
            individual,
            self.component_pool,
            self.config,
        )
        return mutated_individual
    
    def real_evaluation(self, individual: Individual, opponent: str, generation: int | None = None):
        """Run a full MicroRTS game and write the resulting fitness back to the individual."""
        evaluator = Evaluator(self.component_pool, self.config)
        evaluator.evaluate(
            individual,
            use_real_evaluation=True,
            allow_history_reuse_for_real=bool(generation == -1),
            opponent=opponent,
            profile_output_path=self.get_profile_log_path(),
            generation=generation,
            fitness_recorder=self.fitness_recorder,
        )

    
    def surrogate_evaluation(self, individual: Individual, generation: int | None = None):
        """Run the configured cheap evaluator instead of a full game simulation."""
        evaluator = Evaluator(self.component_pool, self.config)
        surrogate_opponent = random.choice(self.opponent_list) if self.opponent_list else None
        evaluator.evaluate(
            individual,
            use_real_evaluation=False,
            opponent=surrogate_opponent,
            profile_output_path=self.get_profile_log_path(),
            generation=generation,
            fitness_recorder=self.fitness_recorder,
        )

    
    def run_final_test(self):
        """Replay the last saved generation against the configured final-test opponents."""
        run_final_test_suite(self.current_log_dir, self.current_generation, self.config)

