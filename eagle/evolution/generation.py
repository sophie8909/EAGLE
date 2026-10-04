"""Shared generation step for fresh and resumed evolutionary searches."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.pipeline import evaluate_population
from eagle.evolution.offspring import (
    apply_offspring_mutations,
    materialize_code_reflections,
    plan_offspring,
)
from eagle.evolution.parent_refresh import (
    build_parent_evaluation_replicas,
    build_self_play_fitness_refresh_replicas,
    write_parent_evaluation_sidecar,
    write_self_play_parent_refresh_sidecar,
)
from eagle.generation.backend import ExistingJavaPhenotypeBackend
from eagle.operators.adaptive import ReflectionOperatorController
from eagle.operators.selection import population_signature, select_next_generation
from eagle.operators.strategy import cleanup_retired_match_traces
from eagle.run_artifacts import record_error_memory, record_generation
from eagle.self_play import (
    assert_shared_self_play_context,
    is_self_play_refresh,
    population_matches_self_play_context,
    select_self_play_library_candidates,
    update_self_play_opponent_library,
    write_self_play_snapshot,
)
from eagle.strategy_diversity import (
    archive_niches,
    diversity_console_summary,
    generation_diversity_metrics,
    update_strategy_archive,
)
from eagle.timing import Stopwatch, append_event, build_generation_event


@dataclass(frozen=True)
class GenerationStepResult:
    """Persisted state produced by one shared evolutionary generation step."""

    population: list[Candidate]
    self_play_opponent_snapshot: list[Candidate] | None
    population_state_signature: Any
    stagnation_count: int
    error_memory: tuple[dict[str, object], ...]
    diversity: dict[str, Any]
    aos_record: dict[str, Any]
    stop_reason: str | None


def run_generation_step(
    *,
    generation: int,
    config: ExperimentConfig,
    run_dir: Path,
    candidates_dir: Path,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    run_id: str,
    rng: random.Random,
    population: list[Candidate],
    population_state_signature: Any,
    stagnation_count: int,
    error_memory: tuple[dict[str, object], ...],
    self_play_opponent_snapshot: list[Candidate] | None,
    generation_backend: Any,
    shared_client: Any,
    generation_client: Any,
    mutations: Any,
    operator_controller: ReflectionOperatorController,
    activate_phase: Callable[[str], None],
) -> GenerationStepResult:
    """Run one generation for both new searches and resumed searches.

    Keeping this boundary shared prevents the two entrypoints from drifting in
    refresh, mutation, evaluation, persistence, or survivor-selection order.
    The caller owns only run initialization/finalization and resume state load.
    """

    generation_span = Stopwatch.start()
    source_parents = list(population)
    parent_replicas: list[Candidate] = []
    snapshot_refreshed = is_self_play_refresh(config, generation)
    context_migration_required = (
        config.evaluation_mode == "self_play"
        and self_play_opponent_snapshot is not None
        and not population_matches_self_play_context(
            source_parents,
            self_play_opponent_snapshot,
        )
    )
    if snapshot_refreshed:
        update_self_play_opponent_library(
            run_dir,
            source_parents,
            capacity=config.self_play_opponent_library_capacity,
        )
        self_play_opponent_snapshot = select_self_play_library_candidates(
            run_dir,
            generation=generation,
            refresh_interval=config.self_play_refresh_interval,
        )
        write_self_play_snapshot(
            run_dir,
            generation=generation,
            candidates=self_play_opponent_snapshot,
            refresh_interval=config.self_play_refresh_interval,
        )
    if snapshot_refreshed or context_migration_required:
        parent_replicas = build_self_play_fitness_refresh_replicas(
            source_parents,
            generation=generation,
        )
        parent_replicas = evaluate_population(
            parent_replicas,
            generation=generation,
            config=config,
            backend=ExistingJavaPhenotypeBackend(),
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock,
            llm_client=shared_client,
            run_timing_path=run_dir / "timing.jsonl",
            run_id=run_id,
            opponent_candidates=self_play_opponent_snapshot,
        )

    parents_for_generation = parent_replicas or population
    activate_phase("reflection")
    plans = plan_offspring(
        parents_for_generation,
        config=config,
        generation=generation,
        rng=rng,
        mutations=mutations,
        operator_controller=operator_controller,
        artifact_root=candidates_dir,
        error_memory=error_memory,
    )
    plans = apply_offspring_mutations(plans, artifact_root=candidates_dir)
    activate_phase("generation")
    plans = materialize_code_reflections(plans, artifact_root=candidates_dir)
    offspring = [plan.candidate for plan in plans]
    evaluated_offspring = evaluate_population(
        offspring,
        generation=generation,
        config=config,
        backend=generation_backend,
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        llm_client=generation_client,
        run_timing_path=run_dir / "timing.jsonl",
        run_id=run_id,
        opponent_candidates=self_play_opponent_snapshot,
    )
    evaluated_offspring, rewards = operator_controller.collect_rewards(
        parents_for_generation,
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
    if config.parent_evaluation_mode == "regenerate_same_genotype":
        parent_replicas = build_parent_evaluation_replicas(
            source_parents,
            generation=generation,
        )
        parent_replicas = evaluate_population(
            parent_replicas,
            generation=generation,
            config=config,
            backend=generation_backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock,
            llm_client=generation_client,
            run_timing_path=run_dir / "timing.jsonl",
            run_id=run_id,
            opponent_candidates=self_play_opponent_snapshot,
        )

    selection_candidates = [*parent_replicas, *evaluated_offspring]
    if config.evaluation_mode == "self_play":
        assert_shared_self_play_context(
            [*(parent_replicas or population), *evaluated_offspring]
        )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, selection_candidates)
    error_memory = record_error_memory(run_dir, selection_candidates)
    append_event(
        run_dir / "timing.jsonl",
        build_generation_event(
            run_id=run_id,
            generation=generation,
            candidates=selection_candidates,
            span=generation_span.finish(),
        ),
    )
    next_population = select_next_generation(
        parent_replicas if parent_replicas else population,
        evaluated_offspring,
        population_size=config.population_size,
        rng=rng,
        selection_mode=config.algorithm,
        fitness_tolerance=config.fitness_tie_tolerance,
    )
    next_signature = population_signature(
        next_population,
        selection_mode=config.algorithm,
    )
    stagnation = (
        stagnation_count + 1
        if next_signature == population_state_signature
        else 0
    )
    diversity = generation_diversity_metrics(
        next_population,
        previous_archive_niches=archive_before,
    )
    if parent_replicas:
        if snapshot_refreshed or context_migration_required:
            write_self_play_parent_refresh_sidecar(
                run_dir,
                generation=generation,
                source_parents=source_parents,
                replicas=parent_replicas,
                selected_ids={candidate.id for candidate in next_population},
            )
        else:
            write_parent_evaluation_sidecar(
                run_dir,
                generation=generation,
                source_parents=source_parents,
                replicas=parent_replicas,
                selected_ids={candidate.id for candidate in next_population},
            )
    record_generation(
        run_dir,
        generation,
        next_population,
        diversity=diversity,
        aos=aos_record,
    )
    cleanup_retired_match_traces(
        candidates_dir,
        [*source_parents, *selection_candidates],
        surviving_candidate_ids={candidate.id for candidate in next_population},
    )
    print(diversity_console_summary(generation, diversity), flush=True)
    stop_reason = None
    if config.stagnation_generations > 0 and stagnation >= config.stagnation_generations:
        stop_reason = f"stagnation_{config.stagnation_generations}_generations"
    return GenerationStepResult(
        population=next_population,
        self_play_opponent_snapshot=self_play_opponent_snapshot,
        population_state_signature=next_signature,
        stagnation_count=stagnation,
        error_memory=error_memory,
        diversity=diversity,
        aos_record=aos_record,
        stop_reason=stop_reason,
    )
