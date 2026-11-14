"""Canonical evolutionary search for prompt-generated Java MicroRTS agents.

This module owns fresh-run initialization. The shared loop owns generation
iteration and finalization; evaluation owns the child pipeline.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from eagle.artifacts import write_run_config
from eagle.candidate import has_completed_evaluation
from eagle.config import ExperimentConfig
from eagle.evaluation.opponents import preflight_evaluation_opponents
from eagle.evaluation.pipeline import evaluate_population
from eagle.evolution.loop import SearchResult, continue_search
from eagle.evolution.runtime import build_search_runtime
from eagle.generation.backend import InitialJavaSeedBackend
from eagle.operators.initialization import generation_zero_uses_fixed_java, initialize_population
from eagle.run_artifacts import (
    freeze_framework_bundle,
    initialize_run_manifest,
    mark_run_failed,
    mark_run_interrupted,
    record_error_memory,
    record_generation,
)
from eagle.opponent_pool import initial_pool, update_pool
from eagle.self_play import (
    write_self_play_snapshot,
)
from eagle.strategy_diversity import (
    archive_niches,
    diversity_console_summary,
    ensure_strategy_archive,
    generation_diversity_metrics,
    update_strategy_archive,
)
from eagle.timing import Stopwatch, append_event, build_generation_event


def _result_version_folder(config: ExperimentConfig) -> str:
    """Return the comparison dimensions used in a GUI-facing result folder."""
    population = int(config.population_size)
    if config.generations == 0 and config.framework_gpt_initial_candidates:
        initialization = "gpt_initial_genome"
    elif config.framework_qwen_initial_candidates:
        initialization = f"{config.framework_qwen_initial_candidates}_qwen_initial_genome"
    elif config.framework_gpt_initial_candidates >= population:
        initialization = f"{population}_gpt_description"
    elif config.framework_initial_genomes:
        initialization = "1_gpt_9_local_description"
    elif config.framework_initial_strategy_mode == "llm_plus_authored":
        initialization = "gpt_description_authored"
    else:
        initialization = "local_seeded"
    selection = (
        "game_performance_plus_diversity_per_generation"
        if config.evaluation_mode == "self_play"
        else "opponent_wise_lexicase_per_generation"
    )
    if config.framework_evolution_mode == "local" and config.framework_qwen_initial_candidates:
        reflection = "no_reflection"
    elif config.framework_evolution_mode == "option_reflection":
        reflection = "option_reflection_every_5_generations"
    elif config.framework_evolution_mode == "reflection":
        reflection = "framework_reflection_every_5_generations"
    elif config.reflection_operator_mode.value == "static" and config.strategy_reflection_probability == 1.0:
        reflection = "strategy_reflection_per_offspring"
    else:
        reflection = "no_reflection"
    return f"{initialization}__{selection}__{reflection}"


def _new_run_directory(config: ExperimentConfig, active_run_id: str, run_id: str | None) -> Path:
    # Explicit IDs are used by tests, forks, and callers that own their layout.
    if run_id is not None:
        return config.runs_dir / active_run_id
    return config.runs_dir / _result_version_folder(config) / f"seed_{config.random_seed}" / active_run_id


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
    if config.evaluation_mode == "fixed_roster":
        preflight_evaluation_opponents(config, mock=mock)
    active_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = _new_run_directory(config, active_run_id, run_id)
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    run_dir.mkdir(parents=True, exist_ok=False)
    candidates_dir.mkdir()
    generated_agents_dir.mkdir()
    classes_dir.mkdir()
    initialize_run_manifest(run_dir, config=config)
    try:
        try:
            config = freeze_framework_bundle(run_dir, config, mock=mock)
        finally:
            # On failure retain the requested input; on success freeze the resolved config.
            write_run_config(run_dir, config, mock=mock)
        initialize_run_manifest(run_dir, config=config)
    except KeyboardInterrupt:
        mark_run_interrupted(run_dir)
        raise
    except Exception as exc:
        mark_run_failed(run_dir, exc)
        raise
    if on_run_created is not None:
        on_run_created(run_dir)

    return run_generation_zero(
        config,
        run_dir=run_dir,
        mock=mock,
    )


def run_generation_zero(
    config: ExperimentConfig,
    *,
    run_dir: Path,
    mock: bool = False,
) -> SearchResult:
    """Initialize generation zero in a fresh or frozen-framework run."""

    active_run_id = run_dir.name
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    for directory in (candidates_dir, generated_agents_dir, classes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_strategy_archive(run_dir)

    framework_slots = config.java_materialization_mode == "framework_slots"
    if framework_slots:
        print(
            "Framework bootstrap: checkpoint persisted; entering generation 0",
            flush=True,
        )
    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
    )
    # Initialization is followed by the same evaluation boundary used for
    # every later offspring generation.
    generation_span = Stopwatch.start()
    if framework_slots:
        print("Generation 0: initializing population", flush=True)
    population = initialize_population(
        config,
        policy_backend=runtime.initial_policy_backend,
        candidates_dir=candidates_dir,
        timing_logger=runtime.llm_logger,
    )
    if (
        config.java_materialization_mode == "framework_slots"
        and (config.framework_evolution_mode in {"reflection", "option_reflection"}
             or config.framework_initial_strategy_mode == "llm_plus_authored")
    ):
        from eagle.evolution.framework_reflection import initialize_framework_strategies

        print(
            "Generation 0: selecting initial framework genomes from strategy descriptions",
            flush=True,
        )
        population = initialize_framework_strategies(
            population=population, config=config, run_dir=run_dir,
            client=runtime.client, mock=mock,
        )
    # Generation zero enters the same evaluation boundary as every offspring,
    # so objective and failure records have one shape.
    if framework_slots:
        print("Generation 0: evaluating initial population", flush=True)
    generation_zero_fixed_java = generation_zero_uses_fixed_java(config)
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=(
            InitialJavaSeedBackend(config.initial_java_seed_path)
            if generation_zero_fixed_java
            else runtime.generation_backend
        ),
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        llm_client=(runtime.client if generation_zero_fixed_java else runtime.generation_client),
        run_timing_path=run_dir / "timing.jsonl",
        run_id=active_run_id,
    )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, evaluated_population)
    generation_diversity = generation_diversity_metrics(
        evaluated_population,
        previous_archive_niches=archive_before,
    )
    if not any(has_completed_evaluation(candidate) for candidate in evaluated_population):
        raise ValueError(
            "Generation 0 produced no candidate that completed evaluation."
        )
    if config.evaluation_mode == "self_play":
        update_pool(run_dir, evaluated_population, generation=0, config=config, mock=mock)
        self_play_opponent_snapshot = initial_pool()
        write_self_play_snapshot(
            run_dir,
            generation=0,
            candidates=self_play_opponent_snapshot,
            config=config,
        )
    append_event(run_dir / "timing.jsonl", build_generation_event(
        run_id=active_run_id, generation=0, candidates=evaluated_population,
        span=generation_span.finish(),
    ))
    print(diversity_console_summary(0, generation_diversity), flush=True)
    error_memory = record_error_memory(run_dir, evaluated_population)
    record_generation(
        run_dir,
        0,
        evaluated_population,
        diversity=generation_diversity,
        aos=runtime.operator_controller.initial_generation_record(),
    )
    if framework_slots:
        print("Generation 0: checkpoint complete", flush=True)

    return continue_search(
        config=config,
        run_dir=run_dir,
        run_id=active_run_id,
        runtime=runtime,
        population=evaluated_population,
        completed_generation=0,
        stagnation_count=0,
        error_memory=error_memory,
        self_play_opponent_snapshot=(initial_pool() if config.evaluation_mode == "self_play" else None),
        mock=mock,
    )
