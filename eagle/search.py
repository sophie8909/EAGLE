"""Canonical evolutionary search for prompt-generated Java MicroRTS agents.

This module owns experiment lifecycle, offspring orchestration, and population
updates. Evaluation owns the shared child pipeline. The canonical entrypoint
is ``run_search``.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from generation.backend import InitialJavaSeedBackend

from .aos import (
    OPERATOR_TO_MUTATION,
    ReflectionOperatorController,
    STRATEGY_REFLECTION,
)
from .artifacts import (
    write_run_config,
    write_summary,
)
from .run_artifacts import (
    finalize_run,
    initialize_run_manifest,
    mark_run_failed,
    mark_run_interrupted,
    record_error_memory,
    record_generation,
)
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import CrossoverContext, crossover
from .evaluation import evaluate_population, preflight_evaluation_opponents
from .mutation import ReflectionContext
from .reflection_context import build_reflection_context
from .timing import Stopwatch, append_event, build_generation_event, utc_now
from .prompts import normalize_prompt
from .rewrite import PromptRewriteMutation
from .strategy_reflection import cleanup_retired_match_traces, select_strategy_mutation_intent
from .search_runtime import build_search_runtime
from .strategy_diversity import (
    archive_niches,
    diversity_console_summary,
    ensure_strategy_archive,
    generation_diversity_metrics,
    update_strategy_archive,
)
from .opponent_archive import ensure_opponent_archive, update_opponent_archive
from .selection import (
    select_parent,
    best_candidate,
    population_signature,
    select_next_generation,
)


@dataclass(frozen=True)
class SearchResult:
    run_dir: Path
    final_population: list[Candidate]
    best_candidate: Candidate | None
    completed_generation: int = 0
    stop_reason: str | None = None


def run_search(
    config: ExperimentConfig,
    *,
    config_path: Path | None = None,
    mock: bool = False,
    run_id: str | None = None,
    on_run_created: Callable[[Path], None] | None = None,
) -> SearchResult:
    """Run the EA and preserve the last completed generation on Ctrl-C."""

    active_run: list[Path | None] = [None]

    def remember_run(path: Path) -> None:
        active_run[0] = path
        if on_run_created is not None:
            on_run_created(path)

    try:
        return _run_search_impl(
            config,
            config_path=config_path,
            mock=mock,
            run_id=run_id,
            on_run_created=remember_run,
        )
    except KeyboardInterrupt:
        if active_run[0] is not None:
            mark_run_interrupted(active_run[0])
        raise
    except Exception as exc:
        if active_run[0] is not None:
            mark_run_failed(active_run[0], exc)
        raise


def _run_search_impl(
    config: ExperimentConfig,
    *,
    config_path: Path | None,
    mock: bool = False,
    run_id: str | None = None,
    on_run_created: Callable[[Path], None] | None = None,
) -> SearchResult:
    """Run the EA lifecycle: initialize, evaluate, select, repeat, and finalize.

    Operators create only candidate genotypes. The evaluation module owns the
    child boundary where generated Java, diagnostics, objectives, and compact
    artifacts are produced; this function owns population-level orchestration.
    """
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    rng = random.Random(config.random_seed)
    active_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = config.runs_dir / active_run_id
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    run_dir.mkdir(parents=True, exist_ok=False)
    candidates_dir.mkdir()
    generated_agents_dir.mkdir()
    classes_dir.mkdir()
    initialize_run_manifest(run_dir, config=config)
    if on_run_created is not None:
        on_run_created(run_dir)
    write_run_config(run_dir, config, mock=mock)
    ensure_strategy_archive(run_dir)
    ensure_opponent_archive(run_dir)

    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
    )
    generation_backend = runtime.generation_backend
    shared_client = runtime.client
    operator_controller = runtime.operator_controller
    # Initialization is followed by the same evaluation boundary used for
    # every later offspring generation.
    population = initialize_population(config)
    # Generation zero enters the same evaluation boundary as every offspring so objective and failure records have one shape.
    generation_span = Stopwatch.start()
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=(
            generation_backend
            if config.candidate_java_mode == "inherited_genotype"
            else InitialJavaSeedBackend(config.initial_java_seed_path)
        ),
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        llm_client=shared_client,
    )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, evaluated_population)
    update_opponent_archive(run_dir, evaluated_population)
    append_event(run_dir / "timing.jsonl", build_generation_event(
        run_id=active_run_id,
        generation=0,
        candidates=evaluated_population,
        span=generation_span.finish(),
    ))
    generation_diversity = generation_diversity_metrics(evaluated_population, previous_archive_niches=archive_before)
    record_generation(
        run_dir,
        0,
        evaluated_population,
        diversity=generation_diversity,
        aos=operator_controller.initial_generation_record(),
    )
    print(diversity_console_summary(0, generation_diversity), flush=True)
    error_memory = record_error_memory(run_dir, evaluated_population)

    population_state_signature = population_signature(evaluated_population)
    stagnation_count = 0
    completed_generation = 0
    stop_reason: str | None = None

    # One fixed EA step per iteration: select parents -> create offspring ->
    # evaluate offspring -> select survivors.
    # Generation 0 is initialization only; ``generations`` counts evolutionary
    # offspring generations, so generations=20 runs gen1 through gen20.
    for generation in range(1, config.generations + 1):
        # Operators produce only child genotypes; evaluation starts at the shared boundary below.
        offspring = create_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            mutations=runtime.mutations,
            operator_controller=operator_controller,
            artifact_root=candidates_dir,
            error_memory=error_memory,
        )
        generation_span = Stopwatch.start()
        # Validation, compilation, runtime evaluation, objectives, and candidate artifacts stay centralized in evaluation.
        evaluated_offspring = evaluate_population(
            offspring,
            generation=generation,
            config=config,
            backend=generation_backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock,
            llm_client=shared_client,
        )
        evaluated_offspring, rewards = operator_controller.collect_rewards(
            evaluated_population,
            evaluated_offspring,
            config=config,
            candidates_dir=candidates_dir,
            classes_dir=classes_dir,
            mock=mock,
        )
        aos_record = operator_controller.update_generation(rewards)
        evaluated_offspring = operator_controller.persist_reward_outcomes(
            evaluated_offspring,
            rewards,
            record=aos_record,
            candidates_dir=candidates_dir,
        )
        archive_before = archive_niches(run_dir)
        update_strategy_archive(run_dir, evaluated_offspring)
        update_opponent_archive(run_dir, evaluated_offspring)
        error_memory = record_error_memory(run_dir, evaluated_offspring)
        append_event(run_dir / "timing.jsonl", build_generation_event(
            run_id=active_run_id,
            generation=generation,
            candidates=evaluated_offspring,
            span=generation_span.finish(),
        ))
        # Survival selection is the only population update boundary and consumes
        # the objectives already persisted by evaluate_population.
        selection_candidates = [*evaluated_population, *evaluated_offspring]
        evaluated_population = select_next_generation(
            evaluated_population,
            evaluated_offspring,
            population_size=config.population_size,
            rng=rng,
        )
        current_population_signature = population_signature(evaluated_population)
        if current_population_signature == population_state_signature:
            stagnation_count += 1
        else:
            population_state_signature = current_population_signature
            stagnation_count = 0
        generation_diversity = generation_diversity_metrics(evaluated_population, previous_archive_niches=archive_before)
        record_generation(
            run_dir,
            generation,
            evaluated_population,
            diversity=generation_diversity,
            aos=aos_record,
        )
        cleanup_retired_match_traces(
            candidates_dir,
            selection_candidates,
            surviving_candidate_ids={candidate.id for candidate in evaluated_population},
        )
        print(diversity_console_summary(generation, generation_diversity), flush=True)
        completed_generation = generation
        if (
            config.stagnation_generations > 0
            and stagnation_count >= config.stagnation_generations
        ):
            stop_reason = f"stagnation_{config.stagnation_generations}_generations"
            break

    best = best_candidate(evaluated_population)
    write_summary(
        run_dir,
        config=config,
        final_population=evaluated_population,
        best_candidate=best,
        mock=mock,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    finalize_run(run_dir, evaluated_population, stop_reason=stop_reason)
    return SearchResult(
        run_dir=run_dir,
        final_population=evaluated_population,
        best_candidate=best,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )


def initialize_population(config: ExperimentConfig) -> list[Candidate]:
    # The inherited mode deliberately replicates one policy/Java genotype so
    # generation zero makes one independent decoder call per population slot.
    # The default mode preserves the one-seed-file/one-candidate contract.
    seed_prompts = config.seed_prompts
    if config.candidate_java_mode == "inherited_genotype" and len(seed_prompts) == 1:
        seed_prompts = tuple(seed_prompts[0] for _ in range(config.population_size))
    inherited_java = (
        config.initial_java_seed_path.read_text(encoding="utf-8")
        if config.candidate_java_mode == "inherited_genotype"
        else ""
    )
    population = [
        Candidate(
            generation=0,
            strategy_prompt=prompt,
            generation_prompt=config.generation_prompt,
            inherited_java=inherited_java,
            operator="seed",
            metadata={
                "seed_index": 0 if config.candidate_java_mode == "inherited_genotype" else index,
                **(
                    {"replicate_index": index}
                    if config.candidate_java_mode == "inherited_genotype"
                    else {}
                ),
            },
        )
        for index, prompt in enumerate(seed_prompts)
    ]
    return population[: config.population_size]


def create_offspring(
    population: list[Candidate], *, config: ExperimentConfig, generation: int,
    rng: random.Random, mutations: dict[str, PromptRewriteMutation],
    operator_controller: ReflectionOperatorController, artifact_root: Path | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
) -> list[Candidate]:
    """Create the next generation's genotypes without evaluating them.

    Parent selection, optional component-wise crossover, and optional prompt
    mutation happen here. Java generation, compilation, matches, and objective
    calculation remain in :func:`evaluate_population`.
    """
    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        context_index = len(offspring)
        parent_selection_started = time.monotonic()
        parent_a = select_parent(population, rng)
        parent_b = select_parent(population, rng)
        parent_selection_duration = max(0.0, time.monotonic() - parent_selection_started)
        if len(population) > 1 and rng.random() < config.crossover_rate:
            crossover_started_at = utc_now()
            crossover_started = time.monotonic()
            child = crossover(parent_a, parent_b, CrossoverContext(
                generation=generation,
                index=context_index,
                rng=rng,
                inherit_java=config.candidate_java_mode == "inherited_genotype",
            ))
            crossover_duration = max(0.0, time.monotonic() - crossover_started)
            child = replace(child, timing={
                **child.timing,
                "crossover": {
                    "operation_type": "crossover",
                    "started_at": crossover_started_at,
                    "finished_at": utc_now(),
                    "generation_only_duration_seconds": crossover_duration,
                    "parent_selection_duration_seconds": parent_selection_duration,
                    "status": "success",
                    "error": None,
                },
            })
        else:
            child = Candidate(
                generation=generation,
                parent_ids=(parent_a.id,),
                strategy_prompt=normalize_prompt(parent_a.strategy_prompt, max_chars=config.max_prompt_chars, max_lines=config.max_prompt_lines),
                strategy_signature=dict(parent_a.strategy_signature),
                strategy_niche=parent_a.strategy_niche,
                generation_prompt=parent_a.generation_prompt,
                operator="copy",
                strategy_parent_id=parent_a.id,
                generation_prompt_parent_id=parent_a.id,
                inherited_java=(
                    parent_a.generated_java or parent_a.inherited_java
                    if config.candidate_java_mode == "inherited_genotype" else ""
                ),
                java_parent_id=(
                    parent_a.id
                    if config.candidate_java_mode == "inherited_genotype" else None
                ),
                source_candidate_ids=(parent_a.id,),
            )
        progress_prefix = (
            f"[gen {generation} cand {context_index + 1}/{config.population_size}] "
            f"{child.id}"
        )
        if rng.random() < config.mutation_rate:
            code_feedback_parent_id = (
                child.java_parent_id
                if config.candidate_java_mode == "inherited_genotype"
                else child.generation_prompt_parent_id
            )
            code_feedback_parent = parent_for_component(
                code_feedback_parent_id,
                (parent_a, parent_b),
            )
            eligible_operators = (
                (STRATEGY_REFLECTION,)
                if not (
                    child.strategy_prompt.strip()
                    if config.candidate_java_mode == "inherited_genotype"
                    else code_feedback_parent.strategy_prompt.strip()
                )
                else config.reflection_operator_settings.enabled_operators
            )
            operator_used = operator_controller.select_operator(
                rng,
                eligible=eligible_operators,
            )
            mutation_name = OPERATOR_TO_MUTATION[operator_used]
            mutation = mutations[mutation_name]
            print(
                f"{progress_prefix} stage=mutation status=started operator={mutation_name}",
                flush=True,
            )
            # Reflection evidence must describe the evaluated source of the
            # gene being mutated.  This avoids reviewing one parent's Java as
            # if it had been produced by the other parent's translation gene.
            feedback_parent = mutation_evidence_parent(
                child,
                mutation_name=mutation_name,
                candidate_java_mode=config.candidate_java_mode,
                parents=(parent_a, parent_b),
            )
            mutation_intent = None
            if mutation_name == "strategy":
                mutation_intent = select_strategy_mutation_intent(rng=rng)
                child = replace(child, mutation_intent=mutation_intent, parent_strategy_niche=feedback_parent.strategy_niche)
            mutation_started_at = utc_now()
            mutation_started = time.monotonic()
            parent_objectives = {
                parent.id: dict(parent.fitness_objectives)
                for parent in (parent_a, parent_b)
            }
            generation_best = max(
                (item for item in population if item.game_eval_result),
                key=lambda item: float((item.game_eval_result or {}).get("game_performance", float("-inf"))),
                default=None,
            )
            reference_candidates = {parent.id: parent for parent in (parent_a, parent_b)}
            if generation_best is not None:
                reference_candidates["generation_best"] = generation_best
            mutation_context = mutation_context_from_candidate(
                feedback_parent,
                generation=generation,
                index=context_index,
                reflection_type=mutation_name,
                error_memory=error_memory,
                evolution_candidate=child,
                parent_objectives=parent_objectives,
                reference_candidates=reference_candidates,
            )
            if mutation_name == "strategy":
                child = mutation.mutate(
                    child,
                    mutation_context,
                    artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
                    mutation_intent=mutation_intent,
                )
            else:
                child = mutation.mutate(
                    child,
                    mutation_context,
                    artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
                )
            mutation_record = child.metadata.get("mutation") or {}
            mutation_applied = bool(mutation_record.get("applied"))
            mutation_error = mutation_record.get("reflection_error") or mutation_record.get("rewrite_error")
            child = replace(child, timing={
                **child.timing,
                "mutation": {
                    "operation_type": "mutation",
                    "started_at": mutation_started_at,
                    "finished_at": utc_now(),
                    "generation_only_duration_seconds": max(0.0, time.monotonic() - mutation_started),
                    "parent_selection_duration_seconds": parent_selection_duration,
                    "status": "success" if mutation_applied else "failed",
                    "error": mutation_error,
                },
            })
            child = replace(child, metadata={
                **child.metadata,
                "aos": {
                    "generation": generation,
                    # Credit the operator against the same evaluated parent
                    # whose component/evidence drove the mutation. Crossover
                    # may source that parent from either direct-parent slot.
                    "comparison_parent_id": feedback_parent.id,
                    "offspring_id": child.id,
                    "operator": OPERATOR_TO_MUTATION[operator_used],
                    "operator_id": operator_used,
                    "mode": operator_controller.mode.value,
                    "probability_before": operator_controller.probability(operator_used),
                    "eligible_operator_ids": list(eligible_operators),
                },
            })
            mutation_status = "completed" if mutation_applied else "failed"
            mutation_error_detail = (
                f" error={str(mutation_error).replace(chr(10), ' ')[:300]}"
                if mutation_error
                else ""
            )
            print(
                f"{progress_prefix} stage=mutation status={mutation_status} "
                f"operator={mutation_name} applied={str(mutation_applied).lower()}"
                f"{mutation_error_detail}",
                flush=True,
            )
        else:
            print(
                f"{progress_prefix} stage=mutation status=skipped operator=none",
                flush=True,
            )
        offspring.append(child)
    return offspring


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


def mutation_evidence_parent(
    child: Candidate,
    *,
    mutation_name: str,
    candidate_java_mode: str,
    parents: tuple[Candidate, Candidate],
) -> Candidate:
    """Resolve the evaluated parent that owns one mutation's evidence."""

    if mutation_name == "strategy":
        parent_id = child.strategy_parent_id
    elif mutation_name in {"code", "balance"}:
        parent_id = (
            child.java_parent_id
            if candidate_java_mode == "inherited_genotype"
            else child.generation_prompt_parent_id
        )
    else:
        raise ValueError(f"Unknown mutation name: {mutation_name!r}.")
    return parent_for_component(parent_id, parents)


def mutation_context_from_candidate(
    candidate: Candidate,
    *,
    generation: int,
    index: int,
    reflection_type: str | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
    evolution_candidate: Candidate | None = None,
    parent_objectives: dict[str, dict[str, float]] | None = None,
    reference_candidates: dict[str, Candidate] | None = None,
) -> ReflectionContext:
    return build_reflection_context(
        candidate,
        generation=generation,
        index=index,
        reflection_type=reflection_type,
        error_memory=error_memory,
        evolution_candidate=evolution_candidate,
        parent_objectives=parent_objectives,
        reference_candidates=reference_candidates,
    )
