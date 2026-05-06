"""
Base class for evolutionary algorithms.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, ClassVar, List

from eagle.config import EAConfig
from eagle.eval.microrts.final_test_runner import run_final_test_suite
from .parent_selection import ParentSelection
from eagle.operators.component.crossover import Crossover
from eagle.operators.component.mutation import Mutation
from eagle.project import EAGLE_LOGS_DIR
from eagle.utils.component_pool import ComponentPool
from eagle.utils.match_score_recorder import MatchScoreRecorder

from .individual import Individual

class EA:
    """Shared scaffolding for the single- and multi-objective EA variants.

    This base class owns the common runtime state for a training run:
    population, log directory, fitness recorder, and the standard operators
    (selection, crossover, mutation, and evaluation). Concrete algorithms such
    as GA and NSGA-II provide the outer loop and survivor-selection policy.
    """

    evaluator_factory: ClassVar[Any | None] = None
    reflection_operator: ClassVar[Any | None] = None

    def __init__(self, config: EAConfig, component_pool: ComponentPool, opponent_list: List[str]):
        """Initialize shared EA state and create the initial random population."""
        self.config = config
        self.component_pool = component_pool
        self.component_pool.configure_non_evolving_keys(
            getattr(self.config, "non_evolving_prompt_components", None)
        )
        self.opponent_list = opponent_list
        self.population = self.initialize_population()
        self.current_log_dir: Path | None = None
        self.match_score_recorder: MatchScoreRecorder | None = None
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
        evolving_component_keys = self.component_pool.resolve_evolving_component_keys(
            self.config.non_evolving_prompt_components
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
                    component_keys=evolving_component_keys,
                )
            else:
                individual.initialize_randomly(
                    self.component_pool,
                    component_keys=evolving_component_keys,
                )
            individuals.append(individual)
        return individuals
    
    def _evaluate_initial_population(
        self,
        evaluator: Any,
    ):
        for index, individual in enumerate(self.population):
            print(
                f"[Initial Population] evaluating individual {index + 1}/{len(self.population)}",
                flush=True,
            )
            evaluator.evaluate(
                individual,
                generation=-1,
            )

        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()
       
    def _log_initial_population_snapshot(self) -> None:
        """Persist one generation-0 snapshot after initial real evaluation."""
        if self.current_log_dir is None:
            return

        if hasattr(self, "_assign_rank_and_crowding"):
            snapshot_path = self.current_log_dir / "generation_0_mo.txt"
            if snapshot_path.exists():
                return

            pareto_fronts = self._assign_rank_and_crowding(self.population)
            self.log_multi_objective_generation(str(self.current_log_dir), -1, pareto_fronts)
            self.save_component_pool(str(self.current_log_dir))
            return

        if hasattr(self, "_fitness0"):
            snapshot_path = self.current_log_dir / "generation_0.txt"
            if snapshot_path.exists():
                return

            best_individual = max(self.population, key=self._fitness0)
            self.log_single_objective_generation(str(self.current_log_dir), -1, best_individual)
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
        self.match_score_recorder = MatchScoreRecorder(self.current_log_dir, self.config)
        return str(log_dir)

    def attach_log_dir(self, log_dir: str | Path) -> str:
        """Bind this EA instance to an existing log directory."""
        self.current_log_dir = Path(log_dir)
        self.current_log_dir.mkdir(parents=True, exist_ok=True)
        self.match_score_recorder = MatchScoreRecorder(self.current_log_dir, self.config)
        return str(self.current_log_dir)

    def get_profile_log_path(self) -> Path:
        """Return the JSONL path used for per-individual evaluation profiles."""
        if self.current_log_dir is None:
            raise ValueError("Log directory has not been initialized yet.")
        return self.current_log_dir / "profiles.jsonl"

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
        """Render prompts for logs without breaking on invalid component indices."""
        evaluator = self.build_evaluator()
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
        payload = self.component_pool.to_component_dict()
        with open(components_file, "w") as f:
            json.dump(payload, f, indent=4)


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
            offspring = Individual.from_existing(
                Crossover.uniform_crossover(self.component_pool, parent1, parent2)
            )
            if self.config.crossover_repair_enabled:
                offspring = Individual.from_existing(
                    Mutation.repair_strategy_after_crossover(
                        offspring,
                        self.component_pool,
                    )
                )
            # Seed the child with a cheap inherited estimate; round evaluation
            # overwrites this before survivor selection.
            offspring.fitness = [
                (left + right) / 2
                for left, right in zip(parent1.fitness, parent2.fitness)
            ]
            return offspring
        raise ValueError(f"Unsupported crossover: {self.config.crossover}")
    
    def mutate(self, individual: Individual) -> Individual:
        """Apply one of the configured mutation strategies to a copied child."""
        mutated_individual = Individual.from_existing(
            Mutation.mutate_individual(
                individual,
                self.component_pool,
                self.config,
            )
        )
        return mutated_individual

    def reflect(self, individual: Individual) -> Individual:
        """Apply the configured reflection operator to one parent."""
        if self.reflection_operator is None:
            raise ValueError(
                "No reflection operator configured for this component evolution algorithm."
            )
        return self.reflection_operator.reflect_individual(
            individual,
            self.component_pool,
            self.config,
        )

    def build_evaluator(self) -> Any:
        """Create the evaluator supplied by the application layer."""
        if self.evaluator_factory is None:
            raise ValueError(
                "No evaluator_factory configured for this component evolution algorithm."
            )
        return self.evaluator_factory(self.component_pool, self.config)

    def run_final_test(self):
        """Replay the last saved generation against the configured final-test opponents."""
        if self.config.final_test_max_front is not None and int(self.config.final_test_max_front) < 1:
            print("[Final Test] skipped because final_test_max_front=0", flush=True)
            return
        run_final_test_suite(self.current_log_dir, self.current_generation, self.config)
