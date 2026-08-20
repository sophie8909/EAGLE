"""Resume the canonical EA from the latest surviving-population snapshot."""
from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

from .artifacts import write_summary
from .config import ExperimentConfig
from .crossover import CrossoverContext
from .evaluation import evaluate_population, preflight_evaluation_opponents
from .run_artifacts import (
    finalize_run,
    load_error_memory,
    load_aos_state,
    load_resume_population,
    mark_run_failed,
    mark_run_interrupted,
    record_error_memory,
    record_generation,
)
from .search import SearchResult, create_offspring
from .strategy_diversity import (
    archive_niches,
    diversity_console_summary,
    ensure_strategy_archive,
    generation_diversity_metrics,
    update_strategy_archive,
)
from .opponent_archive import ensure_opponent_archive, update_opponent_archive
from .selection import best_candidate, population_signature, select_next_generation
from .search_runtime import build_search_runtime
from .timing import Stopwatch, append_event, build_generation_event


def resume_search(
    config: ExperimentConfig | None = None,
    *,
    config_path: Path | None = None,
    run_dir: Path,
    mock: bool = False,
) -> SearchResult:
    """Continue from the last atomically recorded generation."""

    persisted = load_resume_config(run_dir)
    if config is not None:
        validate_resume_config(config, persisted, mock=mock)
    config = persisted
    try:
        return _resume_search_impl(config, config_path=config_path, run_dir=run_dir, mock=mock)
    except KeyboardInterrupt:
        mark_run_interrupted(run_dir)
        raise
    except Exception as exc:
        mark_run_failed(run_dir, exc)
        raise


def load_resume_config(run_dir: Path) -> ExperimentConfig:
    """Load the immutable experiment definition owned by a run."""

    run_config_path = run_dir / "config.yaml"
    if not run_config_path.is_file():
        raise ValueError(f"Resume run has no canonical config.yaml: {run_dir}")
    return ExperimentConfig.from_file(run_config_path)


def _resume_search_impl(config: ExperimentConfig, *, config_path: Path | None, run_dir: Path, mock: bool = False) -> SearchResult:
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    completed_generation, population = load_resume_population(run_dir)
    ensure_strategy_archive(run_dir)
    ensure_opponent_archive(run_dir)
    # Backfill the archive from the surviving snapshot when resuming a run
    # created before strategy_archive.json existed.  Older candidates retain
    # the explicit ``unknown`` fallback and are not inferred from prompt text.
    update_strategy_archive(run_dir, population)
    update_opponent_archive(run_dir, population)
    if completed_generation >= config.generations:
        best = best_candidate(population)
        return SearchResult(run_dir, population, best, completed_generation)

    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    for directory in (candidates_dir, generated_agents_dir, classes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
        controller_state=load_aos_state(run_dir),
    )
    generation_backend = runtime.generation_backend
    shared_client = runtime.client
    mutations = runtime.mutations
    rng = random.Random(f"{config.random_seed}:{completed_generation}")
    operator_controller = runtime.operator_controller
    population_state_signature = population_signature(population)
    stagnation = 0
    error_memory = load_error_memory(run_dir)
    stop_reason = None
    for generation in range(completed_generation + 1, config.generations + 1):
        offspring = create_offspring(
            population, config=config, generation=generation, rng=rng,
            mutations=mutations, operator_controller=operator_controller,
            artifact_root=candidates_dir, error_memory=error_memory,
        )
        span = Stopwatch.start()
        evaluated = evaluate_population(
            offspring, generation=generation, config=config, backend=generation_backend,
            generated_agents_dir=generated_agents_dir, classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock, llm_client=shared_client,
        )
        evaluated, rewards = operator_controller.collect_rewards(
            population,
            evaluated,
            config=config,
            candidates_dir=candidates_dir,
            classes_dir=classes_dir,
            mock=mock,
        )
        aos_record = operator_controller.update_generation(rewards)
        evaluated = operator_controller.persist_reward_outcomes(
            evaluated,
            rewards,
            record=aos_record,
            candidates_dir=candidates_dir,
        )
        archive_before = archive_niches(run_dir)
        update_strategy_archive(run_dir, evaluated)
        update_opponent_archive(run_dir, evaluated)
        error_memory = record_error_memory(run_dir, evaluated)
        append_event(
            run_dir / "timing.jsonl",
            build_generation_event(
                run_id=run_dir.name, generation=generation, candidates=evaluated,
                span=span.finish(),
            ),
        )
        population = select_next_generation(
            population, evaluated, population_size=config.population_size, rng=rng,
        )
        signature = population_signature(population)
        stagnation = stagnation + 1 if signature == population_state_signature else 0
        population_state_signature = signature
        generation_diversity = generation_diversity_metrics(population, previous_archive_niches=archive_before)
        record_generation(
            run_dir,
            generation,
            population,
            diversity=generation_diversity,
            aos=aos_record,
        )
        print(diversity_console_summary(generation, generation_diversity), flush=True)
        completed_generation = generation
        if config.stagnation_generations > 0 and stagnation >= config.stagnation_generations:
            stop_reason = f"stagnation_{config.stagnation_generations}_generations"
            break
    best = best_candidate(population)
    write_summary(
        run_dir, config=config, final_population=population, best_candidate=best,
        mock=mock, completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    finalize_run(run_dir, population, stop_reason=stop_reason)
    return SearchResult(run_dir, population, best, completed_generation, stop_reason)


def validate_resume_config(
    config: ExperimentConfig,
    persisted: ExperimentConfig,
    *,
    mock: bool = False,
) -> None:
    run_mapping = persisted.to_mapping(mock=False)
    requested_mapping = config.to_mapping(mock=mock)
    mismatches = _mapping_differences(run_mapping, requested_mapping)
    if mismatches:
        raise ValueError("Resume config does not match the run: " + "; ".join(mismatches))


def _mapping_differences(run_value, requested_value, prefix: str = "") -> list[str]:
    if isinstance(run_value, dict) and isinstance(requested_value, dict):
        differences: list[str] = []
        for key in sorted(set(run_value) | set(requested_value)):
            path = f"{prefix}.{key}" if prefix else str(key)
            differences.extend(
                _mapping_differences(run_value.get(key), requested_value.get(key), path)
            )
        return differences
    if run_value == requested_value:
        return []
    return [f"{prefix}: run={run_value!r}, config={requested_value!r}"]
