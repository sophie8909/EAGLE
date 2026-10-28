"""Shared generation step for fresh and resumed evolutionary searches."""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.pipeline import evaluate_population
from eagle.evaluation.determinism import derive_seed
from eagle.evolution.offspring import (
    OffspringPlan,
    apply_offspring_mutation,
    materialize_code_reflection,
    iter_offspring_plans,
)
from eagle.evolution.framework_reflection import reflect_population_framework
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
from eagle.opponent_pool import PoolMember, select_pool_opponents, update_pool
from eagle.self_play import (
    assert_shared_self_play_context,
    is_self_play_refresh,
    population_matches_self_play_context,
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
    self_play_opponent_snapshot: list[PoolMember] | None
    population_state_signature: Any
    stagnation_count: int
    error_memory: tuple[dict[str, object], ...]
    diversity: dict[str, Any]
    aos_record: dict[str, Any]
    stop_reason: str | None
    config: ExperimentConfig | None = None


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
    self_play_opponent_snapshot: list[PoolMember] | None,
    generation_backend: Any,
    shared_client: Any,
    generation_client: Any,
    mutations: Any,
    operator_controller: ReflectionOperatorController,
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
        self_play_opponent_snapshot = select_pool_opponents(run_dir, generation=generation, config=config)
        write_self_play_snapshot(
            run_dir,
            generation=generation,
            candidates=self_play_opponent_snapshot,
            config=config,
        )
    framework_replicas = None
    if (
        snapshot_refreshed
        and generation > 1
        and config.framework_evolution_mode in {"reflection", "option_reflection"}
    ):
        config, framework_replicas = reflect_population_framework(
            population=source_parents, config=config, run_dir=run_dir,
            generation=generation, client=shared_client, mock=mock,
        )
    if snapshot_refreshed or context_migration_required:
        parent_replicas = framework_replicas or build_self_play_fitness_refresh_replicas(
            source_parents,
            generation=generation,
            random_seed=config.random_seed,
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
    plans = iter_offspring_plans(
        parents_for_generation,
        config=config,
        generation=generation,
        rng=rng,
        mutations=mutations,
        operator_controller=operator_controller,
        artifact_root=candidates_dir,
        error_memory=error_memory,
    )
    pending_plans: dict[int, OffspringPlan] = {}

    def offspring_candidates() -> Iterator[Candidate]:
        try:
            for index, plan in enumerate(plans):
                pending_plans[index] = plan
                yield plan.candidate
        finally:
            plans.close()

    def prepare_offspring(index: int, _candidate: Candidate) -> Candidate:
        plan = pending_plans.pop(index)
        plan = apply_offspring_mutation(
            plan, artifact_root=candidates_dir, total_count=config.population_size,
        )
        return materialize_code_reflection(
            plan, artifact_root=candidates_dir, total_count=config.population_size,
        ).candidate

    evaluated_offspring = evaluate_population(
        offspring_candidates(),
        population_size=config.population_size,
        candidate_transform=prepare_offspring,
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
            random_seed=config.random_seed,
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
    next_population = select_next_generation(
        parent_replicas if parent_replicas else population,
        evaluated_offspring,
        population_size=config.population_size,
        rng=random.Random(derive_seed(config.random_seed, "evolution", generation, "survivors")),
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
    if parent_replicas and framework_replicas is None:
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
    if config.evaluation_mode == "self_play":
        update_pool(run_dir, evaluated_offspring, generation=generation, config=config, mock=mock)
    append_event(
        run_dir / "timing.jsonl",
        build_generation_event(
            run_id=run_id, generation=generation, candidates=selection_candidates,
            span=generation_span.finish(),
        ),
    )
    record_generation(
        run_dir,
        generation,
        next_population,
        diversity=diversity,
        aos=aos_record,
        stagnation_count=stagnation,
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
        config=config,
    )
