"""
Base class for evolutionary algorithms.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, ClassVar, List

from eagle.config import EAConfig
from eagle.objectives.aggregation import aggregate_fitness
from eagle.operators.registry import get_operator
from eagle.project import EAGLE_LOGS_DIR
from eagle.utils.checkpoint import CheckpointManager, deserialize_individual, serialize_individual
from eagle.utils.component_pool import ComponentPool
from eagle.utils.match_score_recorder import MatchScoreRecorder
from eagle.utils.profiler import RunTimingRecorder

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
    default_mutation_operator_name: ClassVar[str] = "mix"
    default_crossover_operator_name: ClassVar[str] = "uniform"
    default_parent_selection_operator_name: ClassVar[str | None] = None
    default_env_selection_operator_name: ClassVar[str] = "pool_replacement"

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
        self.timing_recorder: RunTimingRecorder | None = None
        self.current_generation = 0
        self.mutation_operator = get_operator(
            "mutation",
            self._operator_name("mutation", self.default_mutation_operator_name),
        )
        self.crossover_operator = get_operator(
            "crossover",
            self._operator_name("crossover", self.default_crossover_operator_name),
        )
        self.parent_selection_operator = get_operator(
            "parent_selection",
            self._operator_name(
                "parent_selection",
                self.default_parent_selection_operator_name or self.config.selection_method,
            ),
        )
        self.env_selection_operator = get_operator(
            "env_selection",
            self._operator_name("env_selection", self.default_env_selection_operator_name),
        )

    def _operator_name(self, operator_type: str, default_name: str) -> str:
        """Return a configured operator name or the algorithm default."""
        explicit_name = getattr(self.config, f"{operator_type}_operator", None)
        if explicit_name:
            return str(explicit_name)
        if operator_type == "crossover":
            return str(getattr(self.config, "crossover_operator", None) or getattr(self.config, "crossover", default_name) or default_name)
        return default_name


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
        """Evaluate the starting population before the generational loop begins."""
        for index, individual in enumerate(self.population):
            print(
                f"[Initial Population] evaluating individual {index + 1}/{len(self.population)}",
                flush=True,
            )
            if self.timing_recorder is None:
                self._evaluate_individual(evaluator, individual, generation=-1)
            else:
                with self.timing_recorder.phase(
                    "evaluate_individual",
                    generation=-1,
                    metadata={"individual_id": getattr(individual, "id", None), "stage": "initial"},
                ):
                    self._evaluate_individual(evaluator, individual, generation=-1)

        print("[Initial Population] complete", flush=True)
        self.print_population_snapshot("initial population")
        self._log_initial_population_snapshot()

    def _sample_reproduction_operator(self) -> str:
        """Sample crossover, mutation, or reflection from configured weights."""
        weights = self.config.reproduction_operator_weights()
        if not weights:
            return "mutation"
        operators = list(weights.keys())
        probabilities = [weights[operator] for operator in operators]
        return random.choices(operators, weights=probabilities, k=1)[0]

    def _mutation_parent_snapshot(self, parent: Individual) -> Any:
        """Return algorithm-specific parent fitness data used for feedback."""
        return None

    def _mutation_improved(self, child: Individual, parent_snapshot: Any) -> bool:
        """Return whether a mutation child improved over its parent."""
        return False

    def _update_mutation_component_feedback(self, child: Individual) -> None:
        """Feed mutation-mode success/failure back to adaptive mutation operators."""
        if getattr(child, "_reproduction_operator", None) != "mutation":
            return

        metadata = dict(getattr(child, "mutation_metadata", {}) or {})
        mutation_mode = metadata.get("mutation_mode")
        parent_snapshot = getattr(child, "_mutation_parent_snapshot", None)
        if parent_snapshot is None:
            return

        update_feedback = getattr(self.mutation_operator, "update_feedback", None)
        if update_feedback is not None:
            update_feedback(mutation_mode, self._mutation_improved(child, parent_snapshot))

    def _generate_offspring(self, generation: int) -> List[Individual]:
        """Create one full offspring population without evaluating it yet."""
        offspring: List[Individual] = []
        target_count = self.config.population_size

        while len(offspring) < target_count:
            operator = self._sample_reproduction_operator()
            if operator == "crossover":
                parent1, parent2 = self.select_parents()
                child = self.crossover(parent1, parent2)
            elif operator == "mutation":
                parent = self.select_parent()
                print(
                    f"[Generation {generation + 1}] selected parent for mutation: "
                    f"id={parent.id} {parent}",
                    flush=True,
                )
                child = self.mutate(parent)
                setattr(child, "_mutation_parent_snapshot", self._mutation_parent_snapshot(parent))
                print(
                    f"[Generation {generation + 1}] created child from mutation: "
                    f"id={child.id} {child}",
                    flush=True,
                )
            elif operator == "reflection":
                child = self.reflect(self.select_parent())
            else:
                raise ValueError(f"Unsupported reproduction operator: {operator}")

            setattr(child, "_reproduction_operator", operator)
            offspring.append(child)
            print(
                f"[Generation {generation + 1}] generated offspring "
                f"{len(offspring)}/{target_count} via {operator}",
                flush=True,
            )

        return offspring[:target_count]

    def _evaluate_offspring(self, evaluator: Any, offspring: List[Individual], generation: int) -> None:
        """Evaluate every generated child and update operator feedback."""
        evaluator_label = getattr(self, "evaluator_name", None) or getattr(self.config, "evaluator", "evaluation")
        for index, child in enumerate(offspring):
            print(
                f"[Generation {generation + 1}] {evaluator_label} evaluation "
                f"{index + 1}/{len(offspring)} id={child.id}",
                flush=True,
            )
            if self.timing_recorder is None:
                self._evaluate_individual(evaluator, child, generation=generation)
            else:
                with self.timing_recorder.phase(
                    "evaluate_individual",
                    generation=generation,
                    metadata={"individual_id": getattr(child, "id", None), "stage": "offspring"},
                ):
                    self._evaluate_individual(evaluator, child, generation=generation)
            print(
                f"[Generation {generation + 1}] {evaluator_label} result "
                f"id={child.id} fitness={child.fitness}",
                flush=True,
            )
            self._update_mutation_component_feedback(child)

    def _evaluate_individual(self, evaluator: Any, individual: Individual, *, generation: int | None) -> dict[str, Any]:
        """Run the evaluator and aggregate raw metrics into individual fitness."""
        eval_result = evaluator.evaluate(
            individual,
            generation=generation,
            profile_output_path=self.get_profile_log_path(),
            match_score_recorder=self.match_score_recorder,
        )
        fitness = aggregate_fitness(eval_result, self.config)
        individual.fitness = fitness
        individual.rendered_prompt = eval_result.get("prompt", getattr(individual, "rendered_prompt", ""))
        individual.evaluation_mode = str(eval_result.get("evaluation_mode") or eval_result.get("eval_mode") or "")
        if eval_result.get("eval_mode") == "round":
            existing = getattr(individual, "last_round_evaluation", None)
            if isinstance(existing, dict) and existing:
                existing.setdefault("eval_result", dict(eval_result))
            else:
                individual.last_round_evaluation = {"eval_result": dict(eval_result)}
        elif eval_result.get("eval_mode") in {"full_game", "java_surrogate"}:
            existing = getattr(individual, "last_gameplay_evaluation", None)
            if isinstance(existing, dict) and existing:
                existing.setdefault("eval_result", dict(eval_result))
            else:
                individual.last_gameplay_evaluation = {"eval_result": dict(eval_result)}
        return eval_result

    def _new_run_state(self) -> Any:
        """Return algorithm-specific state carried across generations."""
        return None

    def _before_survivor_selection(self, generation: int, offspring: List[Individual]) -> Any:
        """Return algorithm-specific context computed before replacement."""
        return None

    def _log_generation(
        self,
        generation: int,
        offspring: List[Individual],
        generation_context: Any,
        log_dir: str,
    ) -> None:
        """Persist one generation snapshot."""
        best_individual = max(self.population, key=lambda ind: ind.fitness or [])
        self.log_single_objective_generation(log_dir, generation, best_individual)
        self.save_component_pool(log_dir)
        self.current_generation = generation

    def _after_generation(
        self,
        generation: int,
        offspring: List[Individual],
        generation_context: Any,
        run_state: Any,
    ) -> bool:
        """Return True when the shared loop should stop early."""
        return False

    def _checkpoint_extra_state(self) -> dict[str, Any]:
        """Return subclass-specific JSON-safe state for resume."""
        return {}

    def _restore_checkpoint_extra_state(self, state: dict[str, Any]) -> None:
        """Restore subclass-specific state after population has been loaded."""
        return None

    def _restore_run_state(self, run_state: Any) -> Any:
        """Normalize checkpointed run state after JSON deserialization."""
        return run_state

    def _checkpoint_state(
        self,
        *,
        generation: int,
        phase: str,
        run_state: Any,
    ) -> dict[str, Any]:
        """Build a restartable checkpoint payload for the current algorithm state."""
        return {
            "phase": phase,
            "algorithm": getattr(self.config, "algorithm", type(self).__name__),
            "generation": generation,
            "population": [serialize_individual(individual) for individual in self.population],
            "run_state": run_state,
            "extra_state": self._checkpoint_extra_state(),
        }

    def _save_checkpoint(
        self,
        checkpoint_manager: CheckpointManager,
        *,
        generation: int,
        phase: str,
        run_state: Any,
    ) -> None:
        """Persist a restartable checkpoint and append the checkpoint event log."""
        checkpoint_manager.save_state(
            self._checkpoint_state(
                generation=generation,
                phase=phase,
                run_state=run_state,
            )
        )

    def _restore_checkpoint(self, checkpoint_manager: CheckpointManager) -> tuple[int, Any] | None:
        """Restore population and return the next generation index plus run state."""
        state = checkpoint_manager.load_state()
        if not state or not state.get("population"):
            return None

        self.population = [
            deserialize_individual(payload)
            for payload in list(state.get("population") or [])
            if isinstance(payload, dict)
        ]
        generation = int(state.get("generation", -1))
        self.current_generation = generation
        run_state = state.get("run_state")
        if run_state is None:
            run_state = self._new_run_state()
        run_state = self._restore_run_state(run_state)
        extra_state = state.get("extra_state")
        if isinstance(extra_state, dict):
            self._restore_checkpoint_extra_state(extra_state)
        next_generation = max(0, generation + 1)
        print(
            "[Checkpoint] resumed "
            f"generation={generation} next_generation={next_generation} "
            f"population={len(self.population)}",
            flush=True,
        )
        return next_generation, run_state

    def run(self) -> list:
        """Run the shared generational EA flow."""
        log_dir = self.create_log_folder()
        checkpoint_manager = CheckpointManager(Path(log_dir))
        assert self.timing_recorder is not None
        with self.timing_recorder.phase("build_evaluator"):
            evaluator = self.build_evaluator()

        with self.timing_recorder.phase("restore_checkpoint"):
            restored = self._restore_checkpoint(checkpoint_manager)
        if restored is None:
            with self.timing_recorder.phase("evaluate_initial_population", generation=-1):
                self._evaluate_initial_population(evaluator)
            run_state = self._new_run_state()
            with self.timing_recorder.phase("save_checkpoint", generation=-1):
                self._save_checkpoint(
                    checkpoint_manager,
                    generation=-1,
                    phase="initial_population_complete",
                    run_state=run_state,
                )
            start_generation = 0
        else:
            start_generation, run_state = restored

        try:
            for generation in range(start_generation, self.config.num_generations):
                with self.timing_recorder.phase("generation_total", generation=generation):
                    print(
                        f"[Generation {generation + 1}/{self.config.num_generations}] start",
                        flush=True,
                    )

                    with self.timing_recorder.phase("generate_offspring", generation=generation):
                        offspring = self._generate_offspring(generation)
                    print(
                        f"[Generation {generation + 1}] generated offspring ready: {len(offspring)}",
                        flush=True,
                    )

                    with self.timing_recorder.phase("evaluate_offspring", generation=generation):
                        self._evaluate_offspring(evaluator, offspring, generation)
                    with self.timing_recorder.phase("before_survivor_selection", generation=generation):
                        generation_context = self._before_survivor_selection(generation, offspring)

                    print(
                        f"[Generation {generation + 1}] selecting survivors",
                        flush=True,
                    )
                    with self.timing_recorder.phase("select_survivors", generation=generation):
                        self.population = self.select_next_generation(self.population, offspring)

                    with self.timing_recorder.phase("log_generation", generation=generation):
                        self._log_generation(generation, offspring, generation_context, log_dir)
                        self.print_generation_fitness_summary(generation)
                    print(
                        f"[Generation {generation + 1}] logged",
                        flush=True,
                    )

                    with self.timing_recorder.phase("after_generation", generation=generation):
                        should_stop = self._after_generation(generation, offspring, generation_context, run_state)
                    with self.timing_recorder.phase("save_checkpoint", generation=generation):
                        self._save_checkpoint(
                            checkpoint_manager,
                            generation=generation,
                            phase="generation_complete",
                            run_state=run_state,
                        )

                    self.timing_recorder.write_summary(status="running")
                    if should_stop:
                        print(
                            f"[Generation {generation + 1}] convergence reached; stopping early",
                            flush=True,
                        )
                        break
        finally:
            self.timing_recorder.write_summary(status="complete")

        return self.population
       
    def _log_initial_population_snapshot(self) -> None:
        """Persist one generation-0 snapshot after initial gameplay evaluation."""
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
        self.timing_recorder = RunTimingRecorder(self.current_log_dir)
        return str(log_dir)

    def attach_log_dir(self, log_dir: str | Path) -> str:
        """Bind this EA instance to an existing log directory."""
        self.current_log_dir = Path(log_dir)
        self.current_log_dir.mkdir(parents=True, exist_ok=True)
        self.match_score_recorder = MatchScoreRecorder(self.current_log_dir, self.config)
        self.timing_recorder = RunTimingRecorder(self.current_log_dir)
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

    def print_generation_fitness_summary(
        self,
        generation: int,
        population: List[Individual] | None = None,
    ) -> None:
        """Print a clear end-of-generation fitness summary for every individual."""
        snapshot = list(population if population is not None else self.population)
        display_generation = generation + 1
        print(
            "[Generation Fitness Summary] "
            f"generation={display_generation}/{self.config.num_generations} "
            f"phase=end population={len(snapshot)}",
            flush=True,
        )
        for index, individual in enumerate(snapshot, start=1):
            evaluation_mode = getattr(individual, "evaluation_mode", None) or "unknown"
            print(
                "[Generation Fitness Summary] "
                f"generation={display_generation} index={index} "
                f"id={getattr(individual, 'id', None)} "
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
        return self.parent_selection_operator(self, count=2)

    def select_parent(self) -> Individual:
        """Choose exactly one parent according to the configured selection rule."""
        return self.parent_selection_operator(self, count=1)

    def crossover(self, parent1: Individual, parent2: Individual) -> Individual:
        """Create one child and seed its fitness with the parents' average values."""
        parent1, parent2 = self._crossover_seed_parents(parent1, parent2)
        return self.crossover_operator(
            self.component_pool,
            parent1,
            parent2,
            self.config,
        )

    @staticmethod
    def _crossover_seed_parents(parent1: Individual, parent2: Individual) -> tuple[Individual, Individual]:
        """Adapt scalar GA fitness to the existing crossover seeding contract."""
        if not isinstance(parent1.fitness, (int, float)) and not isinstance(parent2.fitness, (int, float)):
            return parent1, parent2
        left = parent1.copy()
        right = parent2.copy()
        left.fitness = [float(parent1.fitness)] if isinstance(parent1.fitness, (int, float)) else parent1.fitness
        right.fitness = [float(parent2.fitness)] if isinstance(parent2.fitness, (int, float)) else parent2.fitness
        return left, right
    
    def mutate(self, individual: Individual) -> Individual:
        """Apply one of the configured mutation strategies to a copied child."""
        return self.mutation_operator(
            individual,
            self.component_pool,
            self.config,
        )

    def select_next_generation(
        self,
        population: List[Individual],
        offspring: List[Individual],
    ) -> List[Individual]:
        """Create the next population through the configured replacement operator."""
        return self.env_selection_operator(self, population, offspring)

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
        evaluator_name = str(
            getattr(self, "evaluator_name", None) or getattr(self.config, "evaluator", "")
        ).strip()
        if evaluator_name:
            from eagle.core.registry import EVALUATORS

            evaluator_cls = EVALUATORS.get(evaluator_name)
            return evaluator_cls(self.component_pool, self.config)
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
        from eagle.eval.microrts.final_test_runner import run_final_test_suite

        run_final_test_suite(self.current_log_dir, self.current_generation, self.config)
