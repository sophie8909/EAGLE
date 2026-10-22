"""Shared generation iteration and finalization after fresh/resume setup."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from eagle.artifacts import write_summary
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evolution.generation import run_generation_step
from eagle.evolution.runtime import SearchRuntime
from eagle.operators.selection import best_candidate, population_signature
from eagle.opponent_pool import PoolMember
from eagle.run_artifacts import finalize_run


@dataclass(frozen=True)
class SearchResult:
    run_dir: Path
    final_population: list[Candidate]
    best_candidate: Candidate | None
    completed_generation: int = 0
    stop_reason: str | None = None


def continue_search(
    *,
    config: ExperimentConfig,
    run_dir: Path,
    run_id: str,
    runtime: SearchRuntime,
    population: list[Candidate],
    completed_generation: int,
    stagnation_count: int,
    error_memory: tuple[dict[str, object], ...],
    self_play_opponent_snapshot: list[PoolMember] | None,
    mock: bool,
) -> SearchResult:
    """Continue evaluated state through remaining generations and finalize it."""

    rng = random.Random(config.random_seed)
    population_state_signature = population_signature(
        population, selection_mode=config.algorithm,
    )
    stop_reason = (
        f"stagnation_{config.stagnation_generations}_generations"
        if config.stagnation_generations > 0 and stagnation_count >= config.stagnation_generations
        else None
    )
    # Generation zero is initialization; generations counts offspring batches.
    for generation in range(completed_generation + 1, config.generations + 1):
        if stop_reason is not None:
            break
        step = run_generation_step(
            generation=generation,
            config=config,
            run_dir=run_dir,
            candidates_dir=run_dir / "candidates",
            generated_agents_dir=run_dir / "generated_agents",
            classes_dir=run_dir / "classes",
            mock=mock,
            run_id=run_id,
            rng=rng,
            population=population,
            population_state_signature=population_state_signature,
            stagnation_count=stagnation_count,
            error_memory=error_memory,
            self_play_opponent_snapshot=self_play_opponent_snapshot,
            generation_backend=runtime.generation_backend,
            shared_client=runtime.client,
            generation_client=runtime.generation_client,
            mutations=runtime.mutations,
            operator_controller=runtime.operator_controller,
        )
        population = step.population
        self_play_opponent_snapshot = step.self_play_opponent_snapshot
        population_state_signature = step.population_state_signature
        stagnation_count = step.stagnation_count
        error_memory = step.error_memory
        completed_generation = generation
        stop_reason = step.stop_reason

    best = best_candidate(population)
    write_summary(
        run_dir,
        config=config,
        final_population=population,
        best_candidate=best,
        mock=mock,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    finalize_run(run_dir, population, stop_reason=stop_reason)
    return SearchResult(run_dir, population, best, completed_generation, stop_reason)
