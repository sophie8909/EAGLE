"""Resume the canonical EA from the latest surviving-population snapshot."""
from __future__ import annotations

import random
import json
from pathlib import Path

from generation.backend import build_generation_backend

from .artifacts import write_generation_manifest, write_summary
from .config import ExperimentConfig
from .crossover import CrossoverContext
from .evaluation import evaluate_population, preflight_evaluation_opponents
from .llm_logging import LLMCallLogger
from .llm_profiles import LLMProfile
from .mutation import build_reflection_backend
from .rewrite import PromptRewriteMutation
from .run_artifacts import finalize_run, load_resume_population, record_generation
from .search import (
    SearchResult,
    _preflight_llm_endpoints,
    create_offspring,
    front_zero_signature,
)
from .selection import assign_rank_and_crowding, best_candidate, select_next_generation
from .timing import Stopwatch, append_event, build_generation_event


def resume_search(config: ExperimentConfig, *, config_path: Path, run_dir: Path, mock: bool = False) -> SearchResult:
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    _validate_resume_config(config, run_dir)
    completed_generation, population = load_resume_population(run_dir)
    if completed_generation >= config.generations - 1:
        best = best_candidate(population)
        return SearchResult(run_dir, population, best, completed_generation)

    backend_name = "mock" if mock else config.generation_backend
    if mock:
        from .llm_profiles import LLMProfile
        profiles = {
            role: LLMProfile(role, config.llm_base_url, config.llm_model)
            for role in ("reflector", "rewriter", "generator")
        }
    else:
        shared_profile = LLMProfile("shared", config.llm_base_url, config.llm_model)
        profiles = {"reflector": shared_profile, "rewriter": shared_profile, "generator": shared_profile}
        _preflight_llm_endpoints(profiles)
    logger = LLMCallLogger(run_dir / "llm_logs", run_id=run_dir.name, timing_path=run_dir / "timing.jsonl")
    generator = profiles["generator"]
    reflector = profiles["reflector"]
    rewriter = profiles["rewriter"]
    generation_backend = build_generation_backend(
        backend_name, base_url=generator.base_url, model=generator.model, logger=logger,
        llm_profile="generator", timeout_sec=generator.timeout_seconds,
        temperature=generator.temperature, max_output_tokens=generator.max_output_tokens,
    )
    reflection_backend = build_reflection_backend(
        backend_name, base_url=reflector.base_url, model=reflector.model,
        llm_profile="reflector", timeout_sec=reflector.timeout_seconds,
        temperature=reflector.temperature, max_output_tokens=reflector.max_output_tokens,
    )
    rewrite_backend = build_reflection_backend(
        backend_name, base_url=rewriter.base_url, model=rewriter.model,
        llm_profile="rewriter", timeout_sec=rewriter.timeout_seconds,
        temperature=rewriter.temperature, max_output_tokens=rewriter.max_output_tokens,
    )
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    for directory in (candidates_dir, generated_agents_dir, classes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    mutations = {
        "strategy": PromptRewriteMutation(
            config, mutation_type="strategy", reflection_backend=reflection_backend,
            rewrite_backend=rewrite_backend, artifact_root=candidates_dir, logger=logger,
            reflection_model=None if mock else reflector.model,
            rewrite_model=None if mock else rewriter.model, backend_name=backend_name,
        ),
        "code": PromptRewriteMutation(
            config, mutation_type="code", reflection_backend=reflection_backend,
            rewrite_backend=rewrite_backend, artifact_root=candidates_dir, logger=logger,
            reflection_model=None if mock else reflector.model,
            rewrite_model=None if mock else rewriter.model, backend_name=backend_name,
        ),
    }
    rng = random.Random(f"{config.random_seed}:{completed_generation}")
    front_signature = front_zero_signature(population)
    stagnation = 0
    stop_reason = None
    for generation in range(completed_generation + 1, config.generations):
        assign_rank_and_crowding(population)
        offspring = create_offspring(
            population, config=config, generation=generation, rng=rng,
            mutations=mutations, artifact_root=candidates_dir,
        )
        span = Stopwatch.start()
        evaluated = evaluate_population(
            offspring, generation=generation, config=config, backend=generation_backend,
            generated_agents_dir=generated_agents_dir, classes_dir=classes_dir,
            candidates_dir=candidates_dir, results_path=run_dir / "results.jsonl",
            mock=mock, alignment_profile=reflector,
        )
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
        write_generation_manifest(run_dir, generation, population)
        record_generation(run_dir, generation, population)
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

