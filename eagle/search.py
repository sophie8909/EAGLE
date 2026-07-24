"""NSGA-II search loop for prompt-generated Java MicroRTS agents."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from shutil import copy2

from generation.backend import build_generation_backend
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE

from .artifacts import write_generation_manifest, write_prompt_snapshot, write_resolved_config, write_summary
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import Crossover, CrossoverContext
from .evaluation import evaluate_population, preflight_evaluation_opponents
from .mutation import MutationContext, build_reflection_backend
from .llm_logging import LLMCallLogger
from .timing import Stopwatch, append_event, build_generation_event, utc_now
from .llm_profiles import LLMProfile, load_effective_role_profiles
from .offspring import normalize_prompt
from .rewrite import PromptRewriteMutation
from .selection import (
    Selection,
    SelectionContext,
    assign_rank_and_crowding,
    best_candidate,
    select_next_generation,
)


@dataclass(frozen=True)
class SearchResult:
    run_dir: Path
    final_population: list[Candidate]
    best_candidate: Candidate | None
    completed_generation: int = 0
    stop_reason: str | None = None


def run_search(config: ExperimentConfig, *, config_path: Path, mock: bool = False, run_id: str | None = None) -> SearchResult:
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    rng = random.Random(config.random_seed)
    crossover = Crossover(method="uniform")
    selection = Selection(method="binary_tournament")

    active_run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = config.runs_dir / active_run_id
    candidates_dir = run_dir / "candidates"
    generated_agents_dir = run_dir / "generated_agents"
    classes_dir = run_dir / "classes"
    run_dir.mkdir(parents=True, exist_ok=False)
    candidates_dir.mkdir()
    generated_agents_dir.mkdir()
    classes_dir.mkdir()
    copy2(config_path, run_dir / "config.yaml")

    llm_logger = LLMCallLogger(run_dir / "llm_logs", run_id=active_run_id, timing_path=run_dir / "timing.jsonl")
    backend_name = "mock" if mock else config.generation_backend
    if mock:
        role_profiles = {
            "reflector": LLMProfile("reflector", config.llm_base_url, config.llm_model),
            "rewriter": LLMProfile("rewriter", config.llm_base_url, config.llm_model),
            "generator": LLMProfile("generator", config.llm_base_url, config.llm_model),
        }
        stage_routing = {
            "reflection": "reflector",
            "rewrite": "rewriter",
            "generation": "generator",
            "strategy_alignment": "reflector",
        }
    else:
        role_profiles, stage_routing = load_effective_role_profiles(
            role_topology_path=config.llm_role_topology_path,
            endpoint_config_path=config.endpoint_config_path,
            llm_topology=config.llm_topology,
            allow_coder_loopback=config.allow_coder_loopback,
        )
    reflector_profile = role_profiles["reflector"]
    rewriter_profile = role_profiles["rewriter"]
    generator_profile = role_profiles["generator"]
    generation_backend = build_generation_backend(
        backend_name,
        base_url=generator_profile.base_url,
        model=generator_profile.model,
        logger=llm_logger,
        llm_profile="generator",
        timeout_sec=generator_profile.timeout_seconds,
        temperature=generator_profile.temperature,
        max_output_tokens=generator_profile.max_output_tokens,
    )
    reflection_backend = build_reflection_backend(
        backend_name,
        base_url=reflector_profile.base_url,
        model=reflector_profile.model,
        llm_profile="reflector",
        timeout_sec=reflector_profile.timeout_seconds,
        temperature=reflector_profile.temperature,
        max_output_tokens=reflector_profile.max_output_tokens,
    )
    rewrite_backend = build_reflection_backend(
        backend_name,
        base_url=rewriter_profile.base_url,
        model=rewriter_profile.model,
        llm_profile="rewriter",
        timeout_sec=rewriter_profile.timeout_seconds,
        temperature=rewriter_profile.temperature,
        max_output_tokens=rewriter_profile.max_output_tokens,
    )
    strategy_mutation = PromptRewriteMutation(

        config,
        mutation_type="strategy",
        reflection_backend=reflection_backend,
        rewrite_backend=rewrite_backend,
        artifact_root=candidates_dir,
        logger=llm_logger,
        reflection_model=None if backend_name == "mock" else reflector_profile.model,
        rewrite_model=None if backend_name == "mock" else rewriter_profile.model,
        backend_name=backend_name,
    )
    code_mutation = PromptRewriteMutation(
        config,
        mutation_type="code",
        reflection_backend=reflection_backend,
        rewrite_backend=rewrite_backend,
        artifact_root=candidates_dir,
        logger=llm_logger,
        reflection_model=None if backend_name == "mock" else reflector_profile.model,
        rewrite_model=None if backend_name == "mock" else rewriter_profile.model,
        backend_name=backend_name,
    )
    write_resolved_config(
        run_dir,
        config,
        mock=mock,
        profiles=role_profiles,
        stage_routing=stage_routing,
    )
    write_prompt_snapshot(run_dir, config)
    results_path = run_dir / "results.jsonl"

    population = initialize_population(config)
    generation_span = Stopwatch.start()
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=generation_backend,
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        results_path=results_path,
        mock=mock,
        alignment_profile=reflector_profile,
    )
    append_event(run_dir / "timing.jsonl", build_generation_event(
        run_id=active_run_id,
        generation=0,
        candidates=evaluated_population,
        span=generation_span.finish(),
    ))

    front0_signature = front_zero_signature(evaluated_population)
    front0_stagnation_count = 0
    completed_generation = 0
    stop_reason: str | None = None

    for generation in range(1, config.generations):
        assign_rank_and_crowding(evaluated_population)
        offspring = create_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            mutations=(strategy_mutation, code_mutation),
            crossover=crossover,
            selection=selection,
            artifact_root=candidates_dir,
        )
        generation_span = Stopwatch.start()
        evaluated_offspring = evaluate_population(
            offspring,
            generation=generation,
            config=config,
            backend=generation_backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            results_path=results_path,
            mock=mock,
            alignment_profile=reflector_profile,
        )
        append_event(run_dir / "timing.jsonl", build_generation_event(
            run_id=active_run_id,
            generation=generation,
            candidates=evaluated_offspring,
            span=generation_span.finish(),
        ))
        evaluated_population = select_next_generation(evaluated_population, evaluated_offspring, population_size=config.population_size)
        current_front0_signature = front_zero_signature(evaluated_population)
        if current_front0_signature == front0_signature:
            front0_stagnation_count += 1
        else:
            front0_signature = current_front0_signature
            front0_stagnation_count = 0
        write_generation_manifest(run_dir, generation, evaluated_population)
        completed_generation = generation
        if (
            config.front0_stagnation_generations > 0
            and front0_stagnation_count >= config.front0_stagnation_generations
        ):
            stop_reason = f"front0_stagnation_{config.front0_stagnation_generations}_generations"
            break

    assign_rank_and_crowding(evaluated_population)
    best = best_candidate(evaluated_population)
    final_fronts = assign_rank_and_crowding(evaluated_population)
    write_summary(
        run_dir,
        config=config,
        final_population=evaluated_population,
        best_candidate=best,
        pareto_fronts=final_fronts,
        mock=mock,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )
    return SearchResult(
        run_dir=run_dir,
        final_population=evaluated_population,
        best_candidate=best,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )


def front_zero_signature(population: list[Candidate]) -> tuple[tuple[float, ...], ...]:
    """Return a stable signature for the objective values in Pareto front 0."""

    fronts = assign_rank_and_crowding(population)
    if not fronts:
        return ()
    return tuple(sorted(_objective_signature(candidate) for candidate in fronts[0]))


def _objective_signature(candidate: Candidate) -> tuple[float, ...]:
    return tuple(round(float(value), 12) for value in candidate.objective_vector())


def initialize_population(config: ExperimentConfig) -> list[Candidate]:
    population = [Candidate(generation=0, strategy_prompt=prompt, previous_code="", generation_prompt=config.generation_prompt, operator="seed", metadata={"seed_index": index}) for index, prompt in enumerate(config.seed_prompts)]
    while len(population) < config.population_size:
        seed_index = len(population)
        population.append(Candidate(generation=0, strategy_prompt=config.seed_prompts[seed_index % len(config.seed_prompts)], previous_code="", generation_prompt=config.generation_prompt, operator="seed", metadata={"seed_index": seed_index}))
    return population[: config.population_size]


def create_offspring(population: list[Candidate], *, config: ExperimentConfig, generation: int, rng: random.Random, mutations: tuple[PromptRewriteMutation, PromptRewriteMutation], crossover: Crossover, selection: Selection, artifact_root: Path | None = None) -> list[Candidate]:
    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        context_index = len(offspring)
        parent_selection_started = time.monotonic()
        parent_a = selection.select(population, 1, SelectionContext(rng=rng))[0]
        parent_b = selection.select(population, 1, SelectionContext(rng=rng))[0]
        parent_selection_duration = max(0.0, time.monotonic() - parent_selection_started)
        if len(population) > 1 and rng.random() < config.crossover_rate:
            crossover_started_at = utc_now()
            crossover_started = time.monotonic()
            child = crossover.crossover(parent_a, parent_b, CrossoverContext(generation=generation, index=context_index, rng=rng))
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
                previous_code=parent_a.inheritable_previous_code,
                generation_prompt=parent_a.generation_prompt,
                operator="copy",
                strategy_parent_id=parent_a.id,
                previous_code_parent_id=parent_a.id,
                generation_prompt_parent_id=parent_a.id,
                source_candidate_ids=(parent_a.id,),
            )
        if rng.random() < config.mutation_rate:
            feedback_parent = parent_for_component(child.strategy_parent_id, (parent_a, parent_b))
            mutation = choose_mutation(feedback_parent, mutations, rng)
            mutation_started_at = utc_now()
            mutation_started = time.monotonic()
            child = mutation.mutate(child, mutation_context_from_candidate(feedback_parent, generation=generation, index=context_index), artifact_dir=(artifact_root / child.id) if artifact_root is not None else None)
            child = replace(child, timing={
                **child.timing,
                "mutation": {
                    "operation_type": "mutation",
                    "started_at": mutation_started_at,
                    "finished_at": utc_now(),
                    "generation_only_duration_seconds": max(0.0, time.monotonic() - mutation_started),
                    "parent_selection_duration_seconds": parent_selection_duration,
                    "status": "success",
                    "error": None,
                },
            })
        offspring.append(child)
    return offspring


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


def choose_mutation(feedback_parent: Candidate, mutations: tuple[PromptRewriteMutation, PromptRewriteMutation], rng: random.Random) -> PromptRewriteMutation:
    """Choose a mutation type from the parent's latest evaluation.

    A failed game still takes the code-mutation path so the generated agent
    can address implementation-level failures. Once code quality is above
    500, the code is considered strong enough to favor strategy exploration:
    90% strategy mutation and 10% code mutation. All other successful
    candidates retain the default 50/50 split.
    """
    if number_or_none(feedback_parent.fitness_objectives.get("game_performance")) == FAILED_GAME_PERFORMANCE:
        return mutations[1]
    if (number_or_none(feedback_parent.fitness_objectives.get("code_quality")) or 0.0) > 500:
        return mutations[0] if rng.random() < 0.9 else mutations[1]
    return rng.choice(mutations)

def mutation_context_from_candidate(candidate: Candidate, *, generation: int, index: int) -> MutationContext:
    game = candidate.game_eval_result or {}
    quality = candidate.code_quality_result.get("code_quality_breakdown") or {}
    matches = tuple(game.get("match_results") or game.get("matches") or ())
    return MutationContext(
        generation=generation,
        index=index,
        game_performance=number_or_none(candidate.fitness_objectives.get("game_performance")),
        player_resource=number_or_none(game.get("player0_resource")),
        enemy_resource=number_or_none(game.get("player1_resource")),
        resource_breakdown=game.get("resource_breakdown") or {},
        performance_breakdown=game.get("performance_breakdown") or {},
        temporal_summary=game.get("temporal_summary") or {},
        match_summary=game,
        per_match_results=matches,
        wins=_as_int(game.get("wins")),
        draws=_as_int(game.get("draws")),
        losses=_as_int(game.get("losses")),
        final_player_resources=game.get("final_player_resources") or {},
        final_enemy_resources=game.get("final_enemy_resources") or {},
        final_resource_difference=game.get("final_resource_difference"),
        unit_material_statistics=game.get("unit_material_statistics") or {},
        survival_statistics=game.get("survival_statistics") or {},
        round_state_summary=game.get("round_state_summary") or {},
        behavior_summary=game.get("behavior_summary") or {},
        latest_child_java=candidate.generated_java,
        raw_generation_response=str(candidate.metadata.get("raw_generation_response") or ""),
        validation_result=candidate.metadata.get("validation_result") or {},
        compilation_result=candidate.metadata.get("compile_result") or {},
        integration_result=candidate.metadata.get("integration_result") or {},
        runtime_result=game,
        completed_match_count=_as_int(game.get("completed_match_count")),
        function_capability_score=number_or_none(quality.get("function_score")),
        strategy_alignment_score=number_or_none(quality.get("strategy_alignment_score")),
        compilation_score=number_or_none(quality.get("compilation_score")),
        compiler_errors=tuple(quality.get("compiler_errors") or []),
        compiler_warnings=tuple(quality.get("compiler_warnings") or []),
        strategy_region_score=number_or_none(quality.get("strategy_region_score")),
        strategy_region_validation=candidate.code_quality_result.get("strategy_region_validation") or {},
        static_quality_score=number_or_none(quality.get("static_quality_score")),
        static_metrics=quality.get("static_metrics") or {},
        compile_success=candidate.compile_status == "success",
        validation_success=candidate.metadata.get("failure_category") != "Java validation failure",
        runtime_success=candidate.status == "evaluated",
        error_category=str(candidate.metadata.get("failure_category") or ""),
        error_message=str(candidate.metadata.get("failure_reason") or ""),
    )


def number_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _as_int(value: object) -> int | None:
    return int(value) if isinstance(value, int) else None
