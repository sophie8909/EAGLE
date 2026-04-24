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
from ..evaluation.final_test_runner import run_final_test_suite
from ..utils.profiler import build_base_record, timer, write_jsonl

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
        self.checkpoint = None


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
        evolving_static_keys = self.component_pool.resolve_evolving_static_keys(
            self.config.evolving_prompt_components
        )
        initial_population_seeds = list(getattr(self.config, "initial_population_seeds", []) or [])
        if len(initial_population_seeds) > self.config.population_size:
            raise ValueError(
                "initial_population_seeds cannot exceed population_size: "
                f"{len(initial_population_seeds)} > {self.config.population_size}"
            )

        for index in range(self.config.population_size):
            seed = initial_population_seeds[index] if index < len(initial_population_seeds) else None
            individual = Individual(id=seed.get("id") if isinstance(seed, dict) else None)
            if seed is not None:
                individual.initialize_from_seed(
                    self.component_pool,
                    seed,
                    static_component_keys=evolving_static_keys,
                )
            else:
                individual.initialize_randomly(
                    self.component_pool,
                    static_component_keys=evolving_static_keys,
                )
            individuals.append(individual)
        return individuals
    
    def _evaluate_initial_population(
        self,
        evaluator: Evaluator,
        checkpoint: dict[str, Any] | None = None,
    ):
        self.checkpoint = checkpoint
        # Phase 0: restore runtime state if a checkpoint exists.
        if self.checkpoint:
            self.population = self.deserialize_population(self.checkpoint.get("population"))
            self.current_generation = self.checkpoint.get("generation", 0)

            # Phase 0a: recover an interrupted initial-population evaluation.
            if self.checkpoint.get("phase") == "initial_population":
                start_initial = self.checkpoint.get("meta", {}).get("evaluated_initial_count", 0)
                with timer("initial_population_evaluation_time", {}):
                    for index in range(start_initial, len(self.population)):
                        individual = self.population[index]
                        print(
                            f"[Initial Population] evaluating individual {index + 1}/{len(self.population)}",
                            flush=True,
                        )
                        evaluator.evaluate(
                            individual,
                            generation=-1,
                            profile_output_path=self.get_profile_log_path(),
                            fitness_recorder=self.fitness_recorder,
                            allow_history_reuse=True,
                        )
                        self.save_checkpoint(
                            self.build_checkpoint_state(
                                phase="initial_population",
                                generation=-1,
                                meta={"evaluated_initial_count": index + 1},
                            )
                        )
        else:
            # Phase 0b: fresh run; fully evaluate generation -1 before evolution starts.
            with timer("initial_population_evaluation_time", {}):
                for index, individual in enumerate(self.population):
                    print(
                        f"[Initial Population] evaluating individual {index + 1}/{len(self.population)}",
                        flush=True,
                    )
                    evaluator.evaluate(
                        individual,
                        generation=-1,
                        profile_output_path=self.get_profile_log_path(),
                        fitness_recorder=self.fitness_recorder,
                        allow_history_reuse=True,
                    )
                    # Checkpoint meaning:
                    # - phase="initial_population" means generation -1 is still
                    #   being evaluated
                    # - evaluated_initial_count tells resume() how many individuals
                    #   were already fully real-evaluated
                    self.save_checkpoint(
                        self.build_checkpoint_state(
                            phase="initial_population",
                            generation=-1,
                            meta={"evaluated_initial_count": index + 1},
                        )
                    )
        
        
        self.checkpoint = self.build_checkpoint_state(
            phase="generation_complete",
            generation=-1,
            meta={"completed_generation": -1},
        )
        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()
        self.save_checkpoint(self.checkpoint)
       
    def _log_initial_population_snapshot(self) -> None:
        """Persist one `generation_0_mo.txt` snapshot after initial real evaluation."""
        if self.current_log_dir is None:
            return
        if not hasattr(self, "_assign_rank_and_crowding"):
            return

        snapshot_path = self.current_log_dir / "generation_0_mo.txt"
        if snapshot_path.exists():
            return

        pareto_fronts = self._assign_rank_and_crowding(self.population)
        self.log_multi_objective_generation(str(self.current_log_dir), -1, pareto_fronts)
        self.save_component_pool(str(self.current_log_dir))


    
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
                f.write(f"Prompt:\n{self._safe_construct_prompt(best_individual)}\n")
                f.write(f"Fitness: {self._display_fitness(best_individual)}\n")
                f.write("\nPopulation:\n")
                for ind in self.population:
                    f.write(f"{ind} - Fitness: {self._display_fitness(ind)}\n")

    def log_multi_objective_generation(self, log_dir: str, generation: int, pareto_fronts: List[List[Individual]]):
        """Write a human-readable Pareto-front snapshot for the NSGA-II workflow."""
        log_path = f"{log_dir}/generation_{generation+1}_mo.txt"
        with open(log_path, "w") as f:
            f.write(f"Generation {generation+1} - Multi-objective Optimization\n")
            for i, front in enumerate(pareto_fronts):
                f.write(f"\nPareto Front {i+1}:\n")
                for ind in front:
                    evaluation_mode = getattr(ind, "evaluation_mode", None) or "unknown"
                    f.write(
                        f"{ind} - Fitness: {self._display_fitness(ind)} - EvalMode: {evaluation_mode}\n"
                    )
                    f.write(f"Prompt:\n{self._safe_construct_prompt(ind)}\n")
            f.write("\nPopulation Snapshot:\n")
            for ind in self.population:
                evaluation_mode = getattr(ind, "evaluation_mode", None) or "unknown"
                f.write(
                    f"{ind} - Fitness: {self._display_fitness(ind)} - EvalMode: {evaluation_mode}\n"
                )

    def _display_fitness(self, individual: Individual) -> list[float] | Any:
        """Return the most current full fitness for human-readable experiment logs."""
        fitness = getattr(individual, "fitness", None)
        if fitness is not None:
            return fitness
        return []

    def print_population_snapshot(
        self,
        label: str,
        population: List[Individual] | None = None,
    ) -> None:
        """Print every individual's current fitness to stdout for live debugging."""
        snapshot = list(population if population is not None else self.population)
        print(f"[Population] {label} ({len(snapshot)} individuals)", flush=True)
        for index, individual in enumerate(snapshot, start=1):
            evaluation_mode = getattr(individual, "evaluation_mode", None) or "unknown"
            print(
                f"  [{index}] id={getattr(individual, 'id', None)} "
                f"fitness={self._display_fitness(individual)} "
                f"eval_mode={evaluation_mode}",
                flush=True,
            )

    def _safe_construct_prompt(self, individual: Individual) -> str:
        """Render prompts for logs without breaking on legacy invalid component indices."""
        evaluator = Evaluator(self.component_pool, self.config)
        try:
            return evaluator._construct_prompt(individual)
        except Exception as exc:
            return (
                "[Prompt unavailable: failed to render with current component pool]\n"
                f"Reason: {type(exc).__name__}: {exc}\n"
                f"Individual: {individual}"
            )
            
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
            fitnesses = [list(ind.fitness) if ind.fitness is not None else [0.0, 0.0] for ind in self.population]
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
            fitnesses = [list(ind.fitness) if ind.fitness is not None else [0.0, 0.0] for ind in self.population]
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
        mutated_individual = Mutation.mutate_individual(
            individual,
            self.component_pool,
            self.config,
        )
        return mutated_individual

    def run_final_test(self):
        """Replay the last saved generation against the configured final-test opponents."""
        if self.config.final_test_max_front is not None and int(self.config.final_test_max_front) < 1:
            print("[Final Test] skipped because final_test_max_front=0", flush=True)
            return
        run_final_test_suite(self.current_log_dir, self.current_generation, self.config)
