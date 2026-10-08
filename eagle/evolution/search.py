"""Canonical evolutionary search for prompt-generated Java MicroRTS agents.

This module owns fresh-run initialization, generation iteration, and
finalization. Evaluation owns the shared child pipeline. The canonical entrypoint
is ``run_search``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from eagle.artifacts import write_run_config, write_summary
from eagle.candidate import Candidate, has_completed_evaluation
from eagle.config import ExperimentConfig
from eagle.evaluation.opponents import preflight_evaluation_opponents
from eagle.evaluation.pipeline import evaluate_population
from eagle.evolution.generation import run_generation_step
from eagle.evolution.runtime import build_search_runtime, preflight_llm_endpoint
from eagle.generation.backend import InitialJavaSeedBackend
from eagle.operators.initialization import generation_zero_uses_fixed_java, initialize_population
from eagle.operators.selection import best_candidate, population_signature
from eagle.run_artifacts import (
    finalize_run,
    initialize_run_manifest,
    mark_run_failed,
    mark_run_interrupted,
    record_error_memory,
    record_generation,
)
from eagle.self_play import (
    select_self_play_library_candidates,
    update_self_play_opponent_library,
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
    activate_model_phase: Callable[[str], None] | None = None,
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
            activate_model_phase=activate_model_phase,
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
    activate_model_phase: Callable[[str], None] | None = None,
) -> SearchResult:
    """Run the EA lifecycle: initialize, evaluate, select, repeat, and finalize.

    Operators create only candidate genotypes. The evaluation module owns the
    child boundary where generated Java, diagnostics, objectives, and compact
    artifacts are produced; this function owns population-level orchestration.
    """
    config.validate()
    if config.evaluation_mode == "fixed_roster":
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

    runtime = build_search_runtime(
        config,
        mock=mock,
        run_dir=run_dir,
        candidates_dir=candidates_dir,
    )
    generation_backend = runtime.generation_backend
    shared_client = runtime.client
    generation_client = runtime.generation_client
    operator_controller = runtime.operator_controller
    active_model_phase = "reflection"

    def activate_phase(phase: str) -> None:
        nonlocal active_model_phase
        if not config.uses_distinct_generation_model or phase == active_model_phase:
            return
        if mock:
            active_model_phase = phase
            return
        if activate_model_phase is None:
            raise RuntimeError(
                "A distinct generation_model requires the experiment orchestrator's "
                "model-phase activation callback."
            )
        activate_model_phase(phase)
        preflight_llm_endpoint(
            generation_client if phase == "generation" else shared_client
        )
        active_model_phase = phase

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
    if not generation_zero_fixed_java:
        activate_phase("generation")
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=(
            InitialJavaSeedBackend(config.initial_java_seed_path)
            if generation_zero_fixed_java
            else generation_backend
        ),
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        llm_client=(shared_client if generation_zero_fixed_java else generation_client),
        run_timing_path=run_dir / "timing.jsonl",
        run_id=active_run_id,
    )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, evaluated_population)
    append_event(run_dir / "timing.jsonl", build_generation_event(
        run_id=active_run_id,
        generation=0,
        candidates=evaluated_population,
        span=generation_span.finish(),
    ))
    generation_diversity = generation_diversity_metrics(
        evaluated_population,
        previous_archive_niches=archive_before,
    )
    if not any(has_completed_evaluation(candidate) for candidate in evaluated_population):
        raise ValueError(
            "Generation 0 produced no candidate that completed evaluation."
        )
    if config.evaluation_mode == "self_play":
        update_self_play_opponent_library(
            run_dir,
            evaluated_population,
            capacity=config.self_play_opponent_library_capacity,
        )
        self_play_opponent_snapshot = select_self_play_library_candidates(
            run_dir,
            generation=0,
            refresh_interval=config.self_play_refresh_interval,
        )
        write_self_play_snapshot(
            run_dir,
            generation=0,
            candidates=self_play_opponent_snapshot,
            refresh_interval=config.self_play_refresh_interval,
        )
    print(diversity_console_summary(0, generation_diversity), flush=True)
    error_memory = record_error_memory(run_dir, evaluated_population)
    record_generation(
        run_dir,
        0,
        evaluated_population,
        diversity=generation_diversity,
        aos=operator_controller.initial_generation_record(),
    )

    population_state_signature = population_signature(
        evaluated_population,
        selection_mode=config.algorithm,
    )
    self_play_opponent_snapshot = (
        select_self_play_library_candidates(
            run_dir,
            generation=0,
            refresh_interval=config.self_play_refresh_interval,
        )
        if config.evaluation_mode == "self_play"
        else None
    )
    stagnation_count = 0
    completed_generation = 0
    stop_reason: str | None = None
    # One fixed EA step per iteration: select parents -> create offspring ->
    # evaluate offspring -> select survivors.
    # Generation 0 is initialization only; ``generations`` counts evolutionary
    # offspring generations, so generations=20 runs gen1 through gen20.
    for generation in range(1, config.generations + 1):
        step = run_generation_step(
            generation=generation,
            config=config,
            run_dir=run_dir,
            candidates_dir=candidates_dir,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            mock=mock,
            run_id=active_run_id,
            rng=rng,
            population=evaluated_population,
            population_state_signature=population_state_signature,
            stagnation_count=stagnation_count,
            error_memory=error_memory,
            self_play_opponent_snapshot=self_play_opponent_snapshot,
            generation_backend=generation_backend,
            shared_client=shared_client,
            generation_client=generation_client,
            mutations=runtime.mutations,
            operator_controller=operator_controller,
            activate_phase=activate_phase,
        )
        evaluated_population = step.population
        self_play_opponent_snapshot = step.self_play_opponent_snapshot
        population_state_signature = step.population_state_signature
        stagnation_count = step.stagnation_count
        error_memory = step.error_memory
        completed_generation = generation
        if step.stop_reason is not None:
            stop_reason = step.stop_reason
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
