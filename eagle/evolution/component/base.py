"""
Base class for evolutionary algorithms.
"""

from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, List

from eagle.config import EAConfig, clone_config
from eagle.core.result import EvaluationResult, ensure_evaluation_result
from eagle.objectives.aggregation import aggregate_fitness
from eagle.objectives.aggressiveness.runtime import maybe_add_aggressiveness_metrics
from eagle.operators.mutation import support as mutation_support
from eagle.operators.registry import get_operator
from eagle.prompt.example_memory import ExampleMemory
from eagle.project import EAGLE_LOGS_DIR, PROJECT_ROOT
from eagle.utils.checkpoint import CheckpointManager, deserialize_individual, serialize_individual
from eagle.utils.component_pool import ComponentPool
from eagle.utils.experiment_logs import resolve_experiment_log_dir
from eagle.utils.match_score_recorder import MatchScoreRecorder
from eagle.utils.profiler import RunTimingRecorder

from .individual import Individual


@dataclass(frozen=True)
class EvaluationBatchRequest:
    """Parameters for one fail-fast individual evaluation batch.

    Args:
        individuals: Individuals that need evaluation. Individuals with identical
            rendered prompts are deduplicated inside the batch.
        generation: Zero-based generation index, or -1 for initial population.
        stage: Stable machine-readable phase label used by timing/profile output.
        label: Human-readable label printed to the live run log.

    Call flow:
        `EA._evaluate_initial_population()` or `EA._evaluate_offspring()` builds this
        request, `EvaluationBatchRunner.evaluate()` groups by rendered prompt,
        evaluates one leader per group, then copies the leader result to followers.
    """

    individuals: list[Individual]
    generation: int | None
    stage: str
    label: str


class EvaluationBatchRunner:
    """Evaluate prompt-equivalent individuals once per batch.

    The runner owns the evaluation hot path that is shared by initial population
    evaluation, offspring evaluation, and gameplay refreshes. It deliberately
    depends on the parent `EA` object instead of duplicating evaluator construction
    or fitness aggregation, so algorithm-specific behavior remains in subclasses.
    """

    def __init__(self, algorithm: "EA") -> None:
        """Bind the batch runner to one algorithm instance.

        Args:
            algorithm: Active EA instance. The runner calls its evaluator, timing,
                prompt rendering, and prompt-cache copy hooks.
        """
        self.algorithm = algorithm

    def evaluate(self, request: EvaluationBatchRequest) -> None:
        """Evaluate one batch sequentially with prompt deduplication.

        Args:
            request: Batch metadata and individuals to evaluate.

        Raises:
            Any exception raised by prompt rendering, evaluator execution, or
            fitness aggregation. The project policy is fail-fast for these paths.
        """
        individuals = list(request.individuals)
        if not individuals:
            return

        prompt_groups = self.group_by_prompt(individuals)
        leaders = [group[0] for group in prompt_groups]
        duplicate_count = len(individuals) - len(leaders)
        print(
            "[Individual Eval Queue] "
            f"label={request.label} generation={request.generation} stage={request.stage} "
            f"individuals={len(individuals)} unique_prompts={len(leaders)} "
            f"prompt_cache_hits={duplicate_count}",
            flush=True,
        )

        self._evaluate_serial(prompt_groups, request)

    def group_by_prompt(self, individuals: list[Individual]) -> list[list[Individual]]:
        """Group individuals by the exact rendered prompt used for evaluation.

        Args:
            individuals: Candidate individuals in evaluation order.

        Returns:
            Groups where the first individual is the evaluation leader and later
            individuals are prompt-cache followers.
        """
        groups_by_prompt: dict[str, list[Individual]] = {}
        for individual in individuals:
            prompt = self.render_prompt_cache_key(individual)
            groups_by_prompt.setdefault(prompt, []).append(individual)
        return list(groups_by_prompt.values())

    def render_prompt_cache_key(self, individual: Individual) -> str:
        """Render the exact prompt text used as the prompt-cache key.

        Args:
            individual: Individual whose component indices define a prompt.

        Returns:
            Newline-joined prompt text. Rendering errors propagate and stop the run.
        """
        prompt_lines = self.algorithm.component_pool.render_prompt_lines(
            individual.component_indices,
            include_identity_component=self.algorithm.config.include_strategy_identity_in_prompt,
            selected_training_examples=getattr(individual, "training_examples", None),
            use_few_shot_examples=getattr(self.algorithm.config, "use_few_shot_examples", True),
            min_examples=getattr(self.algorithm.config, "min_examples", 0),
            max_examples=getattr(self.algorithm.config, "max_examples", 3),
        )
        return "\n".join(prompt_lines)

    def apply_prompt_cache_followers(
        self,
        group: list[Individual],
        leader: Individual,
        eval_result: dict[str, Any] | EvaluationResult | None,
    ) -> None:
        """Copy the leader's completed evaluation to all same-prompt followers.

        Args:
            group: Prompt-equivalent individuals, with `leader` at index 0.
            leader: Evaluated individual that owns the source result.
            eval_result: Raw evaluator payload returned for the leader.
        """
        if len(group) <= 1:
            return
        for follower in group[1:]:
            self.copy_prompt_cached_evaluation(
                target=follower,
                source=leader,
                eval_result=eval_result,
            )
            print(
                "[Individual Eval Queue] prompt cache hit "
                f"source_id={getattr(leader, 'id', None)} target_id={getattr(follower, 'id', None)} "
                f"fitness={self.algorithm._display_fitness(follower)}",
                flush=True,
            )

    def copy_prompt_cached_evaluation(
        self,
        *,
        target: Individual,
        source: Individual,
        eval_result: dict[str, Any] | EvaluationResult | None,
    ) -> None:
        """Copy evaluation state from a same-prompt source individual.

        Args:
            target: Follower receiving copied evaluation data.
            source: Evaluated leader individual.
            eval_result: Raw evaluator payload used to annotate cache metadata.
        """
        target.fitness = deepcopy(getattr(source, "fitness", None))
        target.rendered_prompt = getattr(source, "rendered_prompt", "")
        target.evaluation_mode = "prompt_cache"
        for score_attr in ("surrogate_score", "gameplay_score"):
            if hasattr(source, score_attr):
                setattr(target, score_attr, deepcopy(getattr(source, score_attr)))
        for attr in ("last_round_evaluation", "last_surrogate_evaluation", "last_gameplay_evaluation"):
            if hasattr(source, attr):
                copied = deepcopy(getattr(source, attr))
                if isinstance(copied, dict):
                    copied["prompt_cache_source_id"] = getattr(source, "id", None)
                    copied["prompt_cache_target_id"] = getattr(target, "id", None)
                setattr(target, attr, copied)
        if isinstance(eval_result, dict):
            cached_eval = deepcopy(eval_result)
            cached_eval["evaluation_mode"] = "prompt_cache"
            cached_eval["prompt_cache_source_id"] = getattr(source, "id", None)
            cached_eval["prompt_cache_target_id"] = getattr(target, "id", None)
            if cached_eval.get("eval_mode") == "round":
                target.last_round_evaluation = {"eval_result": cached_eval}
            elif cached_eval.get("eval_mode") in {"full_game", "java_surrogate"}:
                target.last_gameplay_evaluation = {"eval_result": cached_eval}

    def _evaluate_serial(
        self,
        prompt_groups: list[list[Individual]],
        request: EvaluationBatchRequest,
    ) -> None:
        """Evaluate leader groups one at a time.

        Args:
            prompt_groups: Groups returned by `group_by_prompt()`.
            request: Batch metadata for timing and logging labels.
        """
        for index, group in enumerate(prompt_groups, start=1):
            individual = group[0]
            print(
                f"[{request.label}] evaluating prompt {index}/{len(prompt_groups)} "
                f"leader_id={individual.id} shared_by={len(group)}",
                flush=True,
            )
            eval_result = self.algorithm._evaluate_individual_with_timing(
                individual,
                generation=request.generation,
                stage=request.stage,
            )
            self.apply_prompt_cache_followers(group, individual, eval_result)

class CheckpointFlow:
    """Small coordinator for checkpoint restore/save around `EA.run()`.

    The EA subclass still defines what extra state means. This object only keeps
    the run bootstrap sequence explicit: build manager, restore if possible,
    otherwise evaluate generation 0 and persist the initial checkpoint.
    """

    def __init__(self, algorithm: "EA") -> None:
        """Bind checkpoint operations to one algorithm instance.

        Args:
            algorithm: Active EA instance that owns population, run state hooks,
                and timing recorder.
        """
        self.algorithm = algorithm

    def begin(self, log_dir: str, evaluator: Any) -> tuple[CheckpointManager, int, Any]:
        """Create checkpoint manager and resolve the generation loop start.

        Args:
            log_dir: Active run directory.
            evaluator: Evaluator instance used for initial population evaluation
                when no checkpoint is available.

        Returns:
            Tuple of `(checkpoint_manager, start_generation, run_state)`.
        """
        checkpoint_manager = CheckpointManager(Path(log_dir))
        timing_recorder = self.algorithm._require_timing_recorder()

        with timing_recorder.phase("restore_checkpoint"):
            restored = self.algorithm._restore_checkpoint(checkpoint_manager)
        if restored is not None:
            start_generation, run_state = restored
            return checkpoint_manager, start_generation, run_state

        with timing_recorder.phase("evaluate_initial_population", generation=-1):
            self.algorithm._evaluate_initial_population(evaluator)
        run_state = self.algorithm._new_run_state()
        self.save(
            checkpoint_manager,
            generation=-1,
            phase="initial_population_complete",
            run_state=run_state,
        )
        return checkpoint_manager, 0, run_state

    def save(
        self,
        checkpoint_manager: CheckpointManager,
        *,
        generation: int,
        phase: str,
        run_state: Any,
    ) -> None:
        """Persist one checkpoint inside the timing recorder's save phase.

        Args:
            checkpoint_manager: Manager bound to the current run directory.
            generation: Internal zero-based generation, or -1 after initial eval.
            phase: Stable checkpoint phase label.
            run_state: Algorithm-specific restart state.
        """
        timing_recorder = self.algorithm._require_timing_recorder()
        with timing_recorder.phase("save_checkpoint", generation=generation):
            self.algorithm._save_checkpoint(
                checkpoint_manager,
                generation=generation,
                phase=phase,
                run_state=run_state,
            )


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
        self.example_memory = ExampleMemory(
            max_examples=getattr(
                self.config,
                "example_memory_max_examples",
                ExampleMemory.DEFAULT_MAX_EXAMPLES,
            ),
            initial_examples=getattr(self.component_pool, "initial_training_examples", []),
        )
        self.example_memory.load_from_path(self._examples_pool_path())
        self.component_pool.example_memory = self.example_memory
        self.population = self.initialize_population()
        self.current_log_dir: Path | None = None
        self.match_score_recorder: MatchScoreRecorder | None = None
        self.timing_recorder: RunTimingRecorder | None = None
        self.current_generation = 0
        self.evaluation_batches = EvaluationBatchRunner(self)
        self.checkpoints = CheckpointFlow(self)
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

    def _examples_pool_path(self) -> Path:
        """Return the configured JSONL file used to seed prompt examples."""
        configured = getattr(self.config, "examples_pool_path", "")
        if configured:
            path = Path(str(configured))
            return path if path.is_absolute() else PROJECT_ROOT / path
        component_path = Path(str(getattr(self.config, "component_pool_path", "")))
        if component_path:
            if not component_path.is_absolute():
                component_path = PROJECT_ROOT / component_path
            return component_path.with_name("examples_pool.jsonl")
        return EAGLE_LOGS_DIR / "examples_pool.jsonl"

    @staticmethod
    def _runtime_examples_pool_path(log_dir: str | Path) -> Path:
        """Return the per-run JSONL file used for evolved runtime examples."""
        return Path(log_dir) / "examples_pool.jsonl"

    def _attach_runtime_example_pool(self, log_dir: str | Path) -> None:
        """Save runtime examples under the active run log directory."""
        pool_path = self._runtime_examples_pool_path(log_dir)
        if pool_path.exists():
            self.example_memory.set_pool_path(pool_path, save=False)
            self.example_memory.load_from_path(pool_path, replace=True)
            return
        self.example_memory.set_pool_path(pool_path, save=True)

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
        self._evaluate_individual_batch(
            self.population,
            generation=-1,
            stage="initial",
            label="Initial Population",
        )

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

    def _sample_example_reproduction_operator(self) -> str:
        """Sample the independent examples reproduction operator."""
        weights = getattr(
            self.config,
            "example_reproduction_operator_probs",
            {"crossover": 0.5, "mutation": 0.5},
        )
        operators = list(weights.keys())
        probabilities = [float(weights[operator]) for operator in operators]
        return random.choices(operators, weights=probabilities, k=1)[0]

    def _sample_example_mutation_source(self, *, has_source_individual: bool) -> str:
        """Sample whether example mutation uses fresh previous-round data or the pool."""
        weights = dict(getattr(self.config, "example_mutation_source_probs", {"fresh": 0.5, "pool": 0.5}))
        if not has_source_individual:
            return "pool"
        sources = list(weights.keys())
        probabilities = [float(weights[source]) for source in sources]
        return random.choices(sources, weights=probabilities, k=1)[0]

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
                with self._llm_call_context(
                    generation=generation,
                    mode="crossover",
                    individual_id=f"{parent1.id},{parent2.id}",
                ):
                    child = self.crossover(parent1, parent2)
                self._apply_example_reproduction(child, parent1, parent2)
            elif operator == "mutation":
                parent = self.select_parent()
                print(
                    f"[Generation {generation + 1}] selected parent for mutation: "
                    f"id={parent.id} {parent}",
                    flush=True,
                )
                with self._llm_call_context(
                    generation=generation,
                    mode="mutation",
                    individual_id=str(parent.id),
                ):
                    child = self.mutate(parent)
                self._apply_example_reproduction(child, parent, None)
                setattr(child, "_mutation_parent_snapshot", self._mutation_parent_snapshot(parent))
                print(
                    f"[Generation {generation + 1}] created child from mutation: "
                    f"id={child.id} {child}",
                    flush=True,
                )
            elif operator == "reflection":
                parent = self.select_parent()
                with self._llm_call_context(
                    generation=generation,
                    mode="reflection",
                    individual_id=str(parent.id),
                ):
                    child = self.reflect(parent)
                self._apply_example_reproduction(child, parent, None)
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

    def _llm_call_context(self, *, generation: int | None, mode: str, individual_id: str = ""):
        """Return a metadata context for nested Python LLM backend calls."""
        from eagle.llm import LLM

        return LLM.call_context(
            log_dir=self.current_log_dir,
            generation="" if generation is None else generation,
            individual_id=individual_id,
            mode=mode,
        )

    def _evaluate_offspring(self, evaluator: Any, offspring: List[Individual], generation: int) -> None:
        """Evaluate every generated child and update operator feedback."""
        evaluator_label = getattr(self, "evaluator_name", None) or getattr(self.config, "evaluator", "evaluation")
        self._evaluate_individual_batch(
            offspring,
            generation=generation,
            stage="offspring",
            label=f"Generation {generation + 1} {evaluator_label}",
        )
        for child in offspring:
            print(
                f"[Generation {generation + 1}] {evaluator_label} result "
                f"id={child.id} fitness={child.fitness}",
                flush=True,
            )
            self._update_mutation_component_feedback(child)

    def _evaluate_individual_batch(
        self,
        individuals: List[Individual],
        *,
        generation: int | None,
        stage: str,
        label: str,
    ) -> None:
        """Evaluate one batch of individuals sequentially with prompt deduplication."""
        self.evaluation_batches.evaluate(
            EvaluationBatchRequest(
                individuals=list(individuals),
                generation=generation,
                stage=stage,
                label=label,
            )
        )

    def _group_individuals_by_prompt(self, individuals: List[Individual]) -> list[list[Individual]]:
        """Group one evaluation batch by rendered prompt text."""
        return self.evaluation_batches.group_by_prompt(list(individuals))

    def _render_prompt_cache_key(self, individual: Individual) -> str:
        """Render the exact prompt text used to deduplicate one batch."""
        return self.evaluation_batches.render_prompt_cache_key(individual)

    def _apply_prompt_cache_followers(
        self,
        group: list[Individual],
        leader: Individual,
        eval_result: dict[str, Any] | None,
    ) -> None:
        """Copy one leader's completed evaluation to same-prompt followers."""
        self.evaluation_batches.apply_prompt_cache_followers(group, leader, eval_result)

    def _copy_prompt_cached_evaluation(
        self,
        *,
        target: Individual,
        source: Individual,
        eval_result: dict[str, Any] | None,
    ) -> None:
        """Copy evaluation state from a same-prompt source individual."""
        self.evaluation_batches.copy_prompt_cached_evaluation(
            target=target,
            source=source,
            eval_result=eval_result,
        )

    def _evaluate_individual_with_timing(
        self,
        individual: Individual,
        *,
        generation: int | None,
        stage: str,
    ) -> EvaluationResult:
        """Evaluate one individual using a fresh evaluator instance."""
        evaluator = self.build_evaluator(config_override=clone_config(self.config))
        if self.timing_recorder is None:
            return self._evaluate_individual(evaluator, individual, generation=generation)
        with self.timing_recorder.phase(
            "evaluate_individual",
            generation=generation,
            metadata={"individual_id": getattr(individual, "id", None), "stage": stage},
        ):
            return self._evaluate_individual(evaluator, individual, generation=generation)

    def _evaluate_individual(self, evaluator: Any, individual: Individual, *, generation: int | None) -> EvaluationResult:
        """Run the evaluator and aggregate raw metrics into individual fitness."""
        eval_result = ensure_evaluation_result(evaluator.evaluate(
            individual,
            generation=generation,
            profile_output_path=self.get_profile_log_path(),
            match_score_recorder=self.match_score_recorder,
        ))
        maybe_add_aggressiveness_metrics(
            eval_result,
            individual=individual,
            config=self.config,
            run_dir=self.current_log_dir,
            generation=generation,
        )
        fitness = aggregate_fitness(eval_result, self.config)
        if isinstance(fitness, dict):
            eval_result.fitness = dict(fitness)
        else:
            eval_result.fitness = {"score": float(fitness)}
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

    def _refresh_example_memory(self, individuals: List[Individual], *, generation: int | None) -> None:
        """Refresh code-managed examples from recent round/game evaluation artifacts."""
        if not self._should_refresh_example_memory(generation):
            return
        candidates: list[dict[str, Any]] = []
        for individual in individuals:
            candidates.extend(self._collect_examples_from_individual(individual, generation=generation))
        added = self.example_memory.add_generation_examples(candidates, rng=random)
        if added <= 0:
            return
        print(
            "[Example Memory] refreshed "
            f"generation={generation} added={added} pool={len(self.example_memory.examples)}",
            flush=True,
        )

    def _should_refresh_example_memory(self, generation: int | None) -> bool:
        """Return whether the configured generation interval allows a refresh."""
        interval = int(
            getattr(
                self.config,
                "example_memory_refresh_interval",
                getattr(self.config, "gameplay_refresh_interval", 1),
            )
            or 1
        )
        if generation is None or generation < 0:
            return True
        return (int(generation) + 1) % max(1, interval) == 0

    def _collect_examples_from_individual(self, individual: Individual, *, generation: int | None) -> list[dict[str, Any]]:
        """Collect valid round and real-eval examples without mutating the pool."""
        examples = self.example_memory.collect_from_round_evaluation(
            getattr(individual, "last_round_evaluation", None)
        )
        for log_path in self._individual_game_log_paths(individual):
            for example in self.example_memory.examples_from_game_log(log_path):
                example.setdefault("generation", generation)
                examples.append(example)
        return examples

    @staticmethod
    def _individual_game_log_paths(individual: Individual) -> list[str]:
        """Return MicroRTS log paths from the individual's latest game payloads."""
        paths: list[str] = []
        payloads = [
            getattr(individual, "last_gameplay_evaluation", None),
            getattr(individual, "last_surrogate_evaluation", None),
        ]
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            eval_result = payload.get("eval_result") if isinstance(payload.get("eval_result"), dict) else payload
            scores = eval_result.get("scores") if isinstance(eval_result, dict) else None
            if not isinstance(scores, list):
                scores = [eval_result] if isinstance(eval_result, dict) else []
            for score in scores:
                if not isinstance(score, dict):
                    continue
                simulation_meta = score.get("simulation_meta")
                if isinstance(simulation_meta, dict) and simulation_meta.get("log_path"):
                    paths.append(str(simulation_meta["log_path"]))
                if score.get("log_path"):
                    paths.append(str(score["log_path"]))
        return paths

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
        log_dir = str(self.current_log_dir.resolve()) if self.current_log_dir is not None else ""
        return {
            "phase": phase,
            "algorithm": getattr(self.config, "algorithm", type(self).__name__),
            "generation": generation,
            "log_dir": log_dir,
            "run_metadata": {
                "log_dir": log_dir,
            },
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

    def _require_timing_recorder(self) -> RunTimingRecorder:
        """Return the active timing recorder or fail before entering the run loop.

        Returns:
            Run-level timing recorder created by `create_log_folder()` or `attach_log_dir()`.

        Raises:
            ValueError: If the run directory has not been initialized.
        """
        if self.timing_recorder is None:
            raise ValueError("Timing recorder has not been initialized. Call create_log_folder() first.")
        return self.timing_recorder

    def run(self) -> list:
        """Run the complete shared evolutionary lifecycle.

        Call flow:
            1. Create or reuse the run log directory.
            2. Build one evaluator for setup and shared run operations.
            3. Restore checkpoint if present; otherwise evaluate the initial population.
            4. For each generation, generate offspring, evaluate offspring, compute
               subclass context, select survivors, write logs, run subclass after-hooks,
               and checkpoint the completed generation.
            5. Always write a final timing summary before returning the population.

        Returns:
            Final survivor population after configured generations or convergence stop.
        """
        log_dir = self.create_log_folder()
        timing_recorder = self._require_timing_recorder()
        with timing_recorder.phase("build_evaluator"):
            evaluator = self.build_evaluator()

        checkpoint_manager, start_generation, run_state = self.checkpoints.begin(log_dir, evaluator)

        try:
            for generation in range(start_generation, self.config.num_generations):
                should_stop = self._run_generation(
                    generation=generation,
                    evaluator=evaluator,
                    checkpoint_manager=checkpoint_manager,
                    run_state=run_state,
                    log_dir=log_dir,
                )
                if should_stop:
                    break
        finally:
            timing_recorder.write_summary(status="complete")

        return self.population

    def _run_generation(
        self,
        *,
        generation: int,
        evaluator: Any,
        checkpoint_manager: CheckpointManager,
        run_state: Any,
        log_dir: str,
    ) -> bool:
        """Execute one full generation and persist its checkpoint.

        Args:
            generation: Zero-based generation index.
            evaluator: Shared evaluator instance used by subclass hooks.
            checkpoint_manager: Current run checkpoint manager.
            run_state: Algorithm-specific mutable state carried across generations.
            log_dir: Current run log directory.

        Returns:
            True when the subclass convergence hook requests early stop.
        """
        timing_recorder = self._require_timing_recorder()
        with timing_recorder.phase("generation_total", generation=generation):
            print(
                f"[Generation {generation + 1}/{self.config.num_generations}] start",
                flush=True,
            )

            with timing_recorder.phase("refresh_example_memory", generation=generation):
                self._refresh_example_memory(self.population, generation=generation - 1)
            with timing_recorder.phase("generate_offspring", generation=generation):
                offspring = self._generate_offspring(generation)
            print(
                f"[Generation {generation + 1}] generated offspring ready: {len(offspring)}",
                flush=True,
            )

            with timing_recorder.phase("evaluate_offspring", generation=generation):
                self._evaluate_offspring(evaluator, offspring, generation)
            with timing_recorder.phase("before_survivor_selection", generation=generation):
                generation_context = self._before_survivor_selection(generation, offspring)

            print(
                f"[Generation {generation + 1}] selecting survivors",
                flush=True,
            )
            with timing_recorder.phase("select_survivors", generation=generation):
                self.population = self.select_next_generation(self.population, offspring)

            with timing_recorder.phase("log_generation", generation=generation):
                self._log_generation(generation, offspring, generation_context, log_dir)
                self.print_generation_fitness_summary(generation)
            print(
                f"[Generation {generation + 1}] logged",
                flush=True,
            )

            with timing_recorder.phase("after_generation", generation=generation):
                should_stop = self._after_generation(generation, offspring, generation_context, run_state)
            self.checkpoints.save(
                checkpoint_manager,
                generation=generation,
                phase="generation_complete",
                run_state=run_state,
            )

            timing_recorder.write_summary(status="running")
            if should_stop:
                print(
                    f"[Generation {generation + 1}] convergence reached; stopping early",
                    flush=True,
                )
            return bool(should_stop)
       
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

        return self._initialize_log_dir(resolve_experiment_log_dir())

    def attach_log_dir(self, log_dir: str | Path) -> str:
        """Bind this EA instance to an existing log directory."""
        return self._initialize_log_dir(resolve_experiment_log_dir(log_dir))

    def _initialize_log_dir(self, log_dir: str | Path) -> str:
        """Bind runtime recorders and per-run stores to one log directory."""
        self.current_log_dir = Path(log_dir)
        self.match_score_recorder = MatchScoreRecorder(self.current_log_dir, self.config)
        self.timing_recorder = RunTimingRecorder(self.current_log_dir)
        self._attach_runtime_example_pool(self.current_log_dir)
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
        """Render prompts for logs, failing the run when prompt construction is invalid."""
        evaluator = self.build_evaluator()
        return evaluator._construct_prompt(individual)
            
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

    def _apply_example_reproduction(
        self,
        child: Individual,
        parent1: Individual,
        parent2: Individual | None,
    ) -> None:
        """Apply examples crossover or mutation independently from components."""
        example_operator = self._sample_example_reproduction_operator()
        if example_operator == "crossover":
            source_parent2 = parent2 if parent2 is not None else parent1
            child.training_examples = self._uniform_crossover_training_examples(parent1, source_parent2)
        elif example_operator == "mutation":
            child.training_examples = self._mutate_training_examples_from_memory(
                list(getattr(child, "training_examples", []) or getattr(parent1, "training_examples", []) or []),
                source_individual=parent1,
            )
        else:
            raise ValueError(f"Unsupported example reproduction operator: {example_operator}")
        child.example_reproduction_metadata = {
            "operator": example_operator,
            "example_count": len(getattr(child, "training_examples", []) or []),
        }

    def _uniform_crossover_training_examples(self, parent1: Individual, parent2: Individual) -> list[dict[str, Any]]:
        """Uniform crossover parent examples, padding the shorter parent with empty slots."""
        max_examples = max(0, int(getattr(self.config, "max_examples", 3)))
        if max_examples <= 0:
            return []
        left = [
            deepcopy(example)
            for example in list(getattr(parent1, "training_examples", []) or [])[:max_examples]
            if isinstance(example, dict)
        ]
        right = [
            deepcopy(example)
            for example in list(getattr(parent2, "training_examples", []) or [])[:max_examples]
            if isinstance(example, dict)
        ]
        empty_example: dict[str, Any] = {"_empty_example": True, "content": []}
        child_examples: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index in range(max(len(left), len(right))):
            selected = random.choice(
                [
                    left[index] if index < len(left) else empty_example,
                    right[index] if index < len(right) else empty_example,
                ]
            )
            if selected.get("_empty_example"):
                continue
            key = mutation_support.training_example_key(selected)
            if key in seen:
                continue
            child_examples.append(deepcopy(selected))
            seen.add(key)
            if len(child_examples) >= max_examples:
                break
        return child_examples

    def _mutate_training_examples_from_memory(
        self,
        current_examples: list[dict[str, Any]],
        *,
        source_individual: Individual | None = None,
    ) -> list[dict[str, Any]]:
        """Mutate examples by inserting or replacing entries from the current pool."""
        del source_individual
        max_examples = max(0, int(getattr(self.config, "max_examples", 3)))
        if max_examples <= 0:
            return []
        examples = [deepcopy(example) for example in current_examples if isinstance(example, dict)][:max_examples]
        candidate_pool = [
            deepcopy(example)
            for example in list(getattr(self.example_memory, "examples", []) or [])
            if isinstance(example, dict)
        ]
        if not candidate_pool:
            return examples
        seen = {mutation_support.training_example_key(example) for example in examples}
        candidates = [
            example
            for example in candidate_pool
            if mutation_support.training_example_key(example) not in seen
        ]
        if not candidates:
            return examples
        selected = random.choice(candidates)
        if len(examples) < max_examples:
            examples.append(selected)
        elif examples:
            examples[random.randrange(len(examples))] = selected
        return examples[:max_examples]

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

    def build_evaluator(self, config_override: EAConfig | None = None) -> Any:
        """Create the evaluator supplied by the application layer."""
        evaluator_name = str(
            getattr(self, "evaluator_name", None) or getattr(self.config, "evaluator", "")
        ).strip()
        active_config = config_override or self.config
        if evaluator_name:
            from eagle.core.registry import EVALUATORS

            evaluator_cls = EVALUATORS.get(evaluator_name)
            runtime_logs_dir = self.current_log_dir if self.current_log_dir is not None else None
            return evaluator_cls(self.component_pool, active_config, runtime_logs_dir=runtime_logs_dir)
        if self.evaluator_factory is None:
            raise ValueError(
                "No evaluator_factory configured for this component evolution algorithm."
            )
        runtime_logs_dir = self.current_log_dir if self.current_log_dir is not None else None
        return self.evaluator_factory(self.component_pool, active_config, runtime_logs_dir=runtime_logs_dir)

    def run_final_test(self):
        """Replay the last saved generation against the configured final-test opponents."""
        if self.config.final_test_max_front is not None and int(self.config.final_test_max_front) < 1:
            print("[Final Test] skipped because final_test_max_front=0", flush=True)
            return
        from eagle.eval.microrts.final_test_runner import run_final_test_suite

        run_final_test_suite(self.current_log_dir, self.current_generation, self.config)
