"""Resume the canonical EA from the latest surviving-population snapshot."""
from __future__ import annotations

import random
import json
from dataclasses import replace
from pathlib import Path

from generation.backend import MockGenerationBackend

from .artifacts import write_summary
from .config import ExperimentConfig
from .crossover import CrossoverContext
from .evaluation import evaluate_population, prepare_eagle_opponent, preflight_evaluation_opponents
from .llm_logging import LLMCallLogger
from .llm_profiles import LLMClient
from .mutation import build_reflection_backend
from .rewrite import PromptRewriteMutation
from .run_artifacts import finalize_run, load_error_memory, load_resume_population, record_error_memory, record_generation
from .search import SearchResult, create_offspring, front_zero_signature
from .strategy_archive import archive_niches, ensure_strategy_archive, update_strategy_archive
from .strategy_diversity import diversity_console_summary, generation_diversity_metrics
from .strategy_reflection import MockRoleBackend, StrategyReflectionMutation
from .selection import assign_rank_and_crowding, best_candidate, select_next_generation
from .timing import Stopwatch, append_event, build_generation_event
from evaluation.opponent_schedule import eagle_opponent_weight, select_previous_generation_champion


def resume_search(config: ExperimentConfig, *, config_path: Path, run_dir: Path, mock: bool = False) -> SearchResult:
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    _validate_resume_config(config, run_dir)
    completed_generation, population = load_resume_population(run_dir)
    ensure_strategy_archive(run_dir)
    # Backfill the archive from the surviving snapshot when resuming a run
    # created before strategy_archive.json existed.  Older candidates retain
    # the explicit ``unknown`` fallback and are not inferred from prompt text.
    update_strategy_archive(run_dir, population)
    if completed_generation >= config.generations - 1:
        best = best_candidate(population)
        return SearchResult(run_dir, population, best, completed_generation)

    backend_name = "mock" if mock else config.generation_backend
    client = LLMClient(config.llm_base_url, config.llm_model, temperature=config.llm_temperature, max_output_tokens=config.llm_max_tokens)
    shared_profile = client.profile
    if not mock:
        from .search import _preflight_llm_endpoint
        _preflight_llm_endpoint(client)
    logger = LLMCallLogger(run_dir / "llm_logs", run_id=run_dir.name, timing_path=run_dir / "timing.jsonl")
    generation_backend = MockGenerationBackend() if mock else client.generation_backend(logger=logger)
    if mock:
        reflection_backend = build_reflection_backend("mock")
        rewrite_backend = reflection_backend
    else:
        reflection_backend = client.prompt_backend(operation="reflection")
        rewrite_backend = client.prompt_backend(operation="rewrite")
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    for directory in (candidates_dir, generated_agents_dir, classes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    role_temperatures = {role: temperature for role, _, temperature in config.llm_roles}
    enabled_roles = ({role for role, enabled, _ in config.llm_roles if enabled} if config.llm_roles else {"match_commentator", "manager", "coach", "generator"})
    strategy_role_backend = MockRoleBackend() if mock else client.prompt_backend(operation="match_commentator", temperature=role_temperatures.get("match_commentator"))
    mutations = {
        "strategy": StrategyReflectionMutation(
            strategy_role_backend,
            max_attempts=config.mutation_max_attempts,
            max_prompt_chars=60_000,
            model_identity=None if mock else client.model,
            enabled_roles=enabled_roles,
            selection_seed=config.random_seed,
        ),
        "code": PromptRewriteMutation(
            config, mutation_type="code", reflection_backend=reflection_backend,
            rewrite_backend=rewrite_backend, artifact_root=candidates_dir, logger=logger,
            reflection_model=None if mock else client.model,
            rewrite_model=None if mock else client.model, backend_name=backend_name,
        ),
    }
    rng = random.Random(f"{config.random_seed}:{completed_generation}")
    front_signature = front_zero_signature(population)
    stagnation = 0
    error_memory = load_error_memory(run_dir)
    stop_reason = None
    for generation in range(completed_generation + 1, config.generations):
        assign_rank_and_crowding(population)
        previous_champion = select_previous_generation_champion(population)
        eagle_opponent = prepare_eagle_opponent(
            previous_champion,
            generation=generation,
            config=config,
            classes_dir=classes_dir,
            mock=mock,
        )
        eagle_opponent = replace(
            eagle_opponent,
            weight=eagle_opponent_weight(
                generation,
                config.generations,
                enabled=config.eagle_opponent_enabled,
                min_weight=config.eagle_opponent_min_weight,
                max_weight=config.eagle_opponent_max_weight,
            ),
        )
        offspring = create_offspring(
            population, config=config, generation=generation, rng=rng,
            mutations=mutations, artifact_root=candidates_dir, error_memory=error_memory,
        )
        span = Stopwatch.start()
        evaluated = evaluate_population(
            offspring, generation=generation, config=config, backend=generation_backend,
            generated_agents_dir=generated_agents_dir, classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock, alignment_profile=shared_profile,
            eagle_opponent=eagle_opponent,
        )
        archive_before = archive_niches(run_dir)
        update_strategy_archive(run_dir, evaluated)
        error_memory = record_error_memory(run_dir, evaluated)
        append_event(
            run_dir / "timing.jsonl",
            build_generation_event(
                run_id=run_dir.name, generation=generation, candidates=evaluated,
                span=span.finish(),
            ),
        )
        population = select_next_generation(population, evaluated, population_size=config.population_size)
        signature = front_zero_signature(population)
        stagnation = stagnation + 1 if signature == front_signature else 0
        front_signature = signature
        generation_diversity = generation_diversity_metrics(population, previous_archive_niches=archive_before)
        record_generation(
            run_dir,
            generation,
            population,
            diversity=generation_diversity,
        )
        print(diversity_console_summary(generation, generation_diversity), flush=True)
        completed_generation = generation
        if config.front0_stagnation_generations > 0 and stagnation >= config.front0_stagnation_generations:
            stop_reason = f"front0_stagnation_{config.front0_stagnation_generations}_generations"
            break
    fronts = assign_rank_and_crowding(population)
    best = best_candidate(population)
    write_summary(
        run_dir, config=config, final_population=population, best_candidate=best,
        pareto_fronts=fronts, mock=mock, completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    finalize_run(run_dir, population, stop_reason=stop_reason)
    return SearchResult(run_dir, population, best, completed_generation, stop_reason)


def _validate_resume_config(config: ExperimentConfig, run_dir: Path) -> None:
    path = run_dir / "resolved_config.json"
    if not path.is_file():
        raise ValueError(f"Resume run has no resolved_config.json: {run_dir}")
    resolved = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "population_size": config.population_size,
        "crossover_rate": config.crossover_rate,
        "mutation_rate": config.mutation_rate,
        "ea_random_seed": config.random_seed,
        "map": config.map_path,
        "evaluation_maps": [
            {"map_id": f"map_{index}", "path": path}
            for index, path in enumerate(config.evaluation_maps, start=1)
        ],
        "rounds_per_map": config.rounds_per_map,
        "swap_player_sides": config.swap_player_sides,
        "max_cycles": config.tick_limit,
        "microrts_match_seeds": list(config.resolved_match_seeds),
    }
    mismatches = [
        f"{key}: run={resolved.get(key)!r}, config={value!r}"
        for key, value in expected.items()
        if resolved.get(key) != value
    ]
    if mismatches:
        raise ValueError("Resume config does not match the run: " + "; ".join(mismatches))
