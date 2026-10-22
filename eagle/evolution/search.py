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
    run_dir = config.runs_dir / active_run_id
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
    ensure_strategy_archive(run_dir)

    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
    )
    # Initialization is followed by the same evaluation boundary used for
    # every later offspring generation.
    generation_span = Stopwatch.start()
    population = initialize_population(
        config,
        policy_backend=runtime.initial_policy_backend,
        candidates_dir=candidates_dir,
        timing_logger=runtime.llm_logger,
    )
    # Generation zero enters the same evaluation boundary as every offspring,
    # so objective and failure records have one shape.
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
