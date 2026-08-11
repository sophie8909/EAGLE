"""Canonical evolutionary search for prompt-generated Java MicroRTS agents.

This module owns experiment lifecycle, offspring orchestration, and population
updates. Evaluation owns the shared child pipeline; final-test execution is a
separate post-evolution protocol. The canonical entrypoint is ``run_search``.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from shutil import copy2

from generation.backend import MockGenerationBackend, build_generation_backend
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE

from .artifacts import write_prompt_snapshot, write_resolved_config, write_summary
from .run_artifacts import finalize_run, initialize_run_manifest, record_error_memory, record_generation
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import CrossoverContext, crossover
from .evaluation import evaluate_population, prepare_eagle_opponent, preflight_evaluation_opponents
from .mutation import ReflectionContext, build_reflection_backend
from .reflection_context import build_reflection_context
from .llm_logging import LLMCallLogger
from .timing import Stopwatch, append_event, build_generation_event, utc_now
from .llm_profiles import LLMClient
from .llm_errors import LLMServerError
from .offspring import normalize_prompt
from .rewrite import PromptRewriteMutation
from .strategy_reflection import MockRoleBackend, StrategyReflectionMutation, select_strategy_mutation_intent
from .strategy_archive import archive_niches, ensure_strategy_archive, update_strategy_archive
from .strategy_diversity import diversity_console_summary, generation_diversity_metrics
from .selection import (
    select_parent,
    assign_rank_and_crowding,
    best_candidate,
    select_next_generation,
)
from evaluation.opponent_schedule import eagle_opponent_weight, select_previous_generation_champion


@dataclass(frozen=True)
class SearchResult:
    run_dir: Path
    final_population: list[Candidate]
    best_candidate: Candidate | None
    completed_generation: int = 0
    stop_reason: str | None = None


def run_search(config: ExperimentConfig, *, config_path: Path, mock: bool = False, run_id: str | None = None) -> SearchResult:
    """Prepare a run, evolve generations, persist state, and finalize the run."""
    config.validate()
    preflight_evaluation_opponents(config, mock=mock)
    rng = random.Random(config.random_seed)

    backend_name = "mock" if mock else config.generation_backend
    client = LLMClient(config.llm_base_url, config.llm_model, temperature=config.llm_temperature, max_output_tokens=config.llm_max_tokens)
    shared_profile = client.profile
    if not mock:
        _preflight_llm_endpoint(client)

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
    initialize_run_manifest(run_dir, config_path=config_path)
    ensure_strategy_archive(run_dir)

    llm_logger = LLMCallLogger(run_dir / "llm_logs", run_id=active_run_id, timing_path=run_dir / "timing.jsonl")
    generation_backend = MockGenerationBackend() if mock else client.generation_backend(logger=llm_logger)
    if mock:
        reflection_backend = build_reflection_backend("mock")
        rewrite_backend = reflection_backend
    else:
        reflection_backend = client.prompt_backend(operation="reflection")
        rewrite_backend = client.prompt_backend(operation="rewrite")
    code_mutation = PromptRewriteMutation(
        config,
        mutation_type="code",
        reflection_backend=reflection_backend,
        rewrite_backend=rewrite_backend,
        artifact_root=candidates_dir,
        logger=llm_logger,
        reflection_model=None if backend_name == "mock" else client.model,
        rewrite_model=None if backend_name == "mock" else client.model,
        backend_name=backend_name,
    )
    role_temperatures = {role: temperature for role, _, temperature in config.llm_roles}
    enabled_roles = ({role for role, enabled, _ in config.llm_roles if enabled} if config.llm_roles else {"match_commentator", "manager", "coach", "generator"})
    strategy_role_backend = MockRoleBackend() if mock else client.prompt_backend(operation="match_commentator", temperature=role_temperatures.get("match_commentator"))
    strategy_reflection_mutation = StrategyReflectionMutation(
        strategy_role_backend,
        max_attempts=config.mutation_max_attempts,
        max_prompt_chars=60_000,
        model_identity=None if backend_name == "mock" else client.model,
        enabled_roles=enabled_roles,
        selection_seed=config.random_seed,
    )
    write_resolved_config(
        run_dir,
        config,
        mock=mock,
        client=client,
    )
    write_prompt_snapshot(run_dir, config)
    population = initialize_population(config)
    # Generation zero enters the same evaluation boundary as every offspring so objective and failure records have one shape.
    generation_span = Stopwatch.start()
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=generation_backend,
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        candidates_dir=candidates_dir,
        mock=mock,
        alignment_profile=shared_profile,
        eagle_opponent=None,
    )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, evaluated_population)
    append_event(run_dir / "timing.jsonl", build_generation_event(
        run_id=active_run_id,
        generation=0,
        candidates=evaluated_population,
        span=generation_span.finish(),
    ))
    generation_diversity = generation_diversity_metrics(evaluated_population, previous_archive_niches=archive_before)
    record_generation(
        run_dir,
        0,
        evaluated_population,
        diversity=generation_diversity,
    )
    print(diversity_console_summary(0, generation_diversity), flush=True)
    error_memory = record_error_memory(run_dir, evaluated_population)

    front0_signature = front_zero_signature(evaluated_population)
    front0_stagnation_count = 0
    completed_generation = 0
    stop_reason: str | None = None

    for generation in range(1, config.generations):
        assign_rank_and_crowding(evaluated_population)
        previous_champion = select_previous_generation_champion(evaluated_population)
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
        print(
            f"[gen {generation}] eagle_opponent={previous_champion.id} "
            f"source_gen={generation - 1} weight={eagle_opponent.weight:g}",
            flush=True,
        )
        # Operators produce only child genotypes; evaluation starts at the shared boundary below.
        offspring = create_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            mutations={"strategy": strategy_reflection_mutation, "code": code_mutation},
            artifact_root=candidates_dir,
            error_memory=error_memory,
        )
        generation_span = Stopwatch.start()
        # Validation, compilation, runtime evaluation, objectives, and candidate artifacts stay centralized in evaluation.
        evaluated_offspring = evaluate_population(
            offspring,
            generation=generation,
            config=config,
            backend=generation_backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            candidates_dir=candidates_dir,
            mock=mock,
            alignment_profile=shared_profile,
            eagle_opponent=eagle_opponent,
        )
        archive_before = archive_niches(run_dir)
        update_strategy_archive(run_dir, evaluated_offspring)
        error_memory = record_error_memory(run_dir, evaluated_offspring)
        append_event(run_dir / "timing.jsonl", build_generation_event(
            run_id=active_run_id,
            generation=generation,
            candidates=evaluated_offspring,
            span=generation_span.finish(),
        ))
        # Survival selection is the only population update boundary and consumes
        # the objectives already persisted by evaluate_population.
        evaluated_population = select_next_generation(evaluated_population, evaluated_offspring, population_size=config.population_size)
        current_front0_signature = front_zero_signature(evaluated_population)
        if current_front0_signature == front0_signature:
            front0_stagnation_count += 1
        else:
            front0_signature = current_front0_signature
            front0_stagnation_count = 0
        generation_diversity = generation_diversity_metrics(evaluated_population, previous_archive_niches=archive_before)
        record_generation(
            run_dir,
            generation,
            evaluated_population,
            diversity=generation_diversity,
        )
        print(diversity_console_summary(generation, generation_diversity), flush=True)
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
    finalize_run(run_dir, evaluated_population, stop_reason=stop_reason)
    return SearchResult(
        run_dir=run_dir,
        final_population=evaluated_population,
        best_candidate=best,
        completed_generation=completed_generation,
        stop_reason=stop_reason,
    )


def _preflight_llm_endpoint(client: LLMClient) -> None:
    """Verify the one configured endpoint with one small request."""
    api_root = client.base_url.rstrip("/")
    if not api_root.endswith("/v1"):
        api_root += "/v1"
    url = f"{api_root}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps({
            "model": client.model,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "temperature": 0,
            "max_tokens": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=min(15.0, client.timeout_seconds)) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload.get("choices"), list):
            raise RuntimeError("response has no choices array")
    except (OSError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        raise LLMServerError(f"Qwen3.5 endpoint preflight failed at {url}: {exc}") from exc


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


def create_offspring(population: list[Candidate], *, config: ExperimentConfig, generation: int, rng: random.Random, mutations: dict[str, PromptRewriteMutation], artifact_root: Path | None = None, error_memory: tuple[dict[str, object], ...] = ()) -> list[Candidate]:
    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        context_index = len(offspring)
        parent_selection_started = time.monotonic()
        parent_a = select_parent(population, rng)
        parent_b = select_parent(population, rng)
        parent_selection_duration = max(0.0, time.monotonic() - parent_selection_started)
        if len(population) > 1 and rng.random() < config.crossover_rate:
            crossover_started_at = utc_now()
            crossover_started = time.monotonic()
            child = crossover(parent_a, parent_b, CrossoverContext(generation=generation, index=context_index, rng=rng))
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
                strategy_signature=dict(parent_a.strategy_signature),
                strategy_niche=parent_a.strategy_niche,
                previous_code=parent_a.generated_java,
                generation_prompt=parent_a.generation_prompt,
                operator="copy",
                strategy_parent_id=parent_a.id,
                previous_code_parent_id=parent_a.id,
                generation_prompt_parent_id=parent_a.id,
                source_candidate_ids=(parent_a.id,),
            )
        if rng.random() < config.mutation_rate:
            feedback_parent = parent_for_component(child.strategy_parent_id, (parent_a, parent_b))
            mutation_name = choose_mutation(feedback_parent, rng)
            mutation = mutations[mutation_name]
            mutation_intent = None
            if mutation_name == "strategy":
                mutation_intent = select_strategy_mutation_intent(rng=rng)
                child = replace(child, mutation_intent=mutation_intent, parent_strategy_niche=feedback_parent.strategy_niche)
            mutation_started_at = utc_now()
            mutation_started = time.monotonic()
            parent_objectives = {
                parent.id: dict(parent.fitness_objectives)
                for parent in (parent_a, parent_b)
            }
            generation_best = max(
                (item for item in population if item.game_eval_result),
                key=lambda item: float(item.fitness_objectives.get("game_performance", float("-inf"))),
                default=None,
            )
            reference_candidates = {parent.id: parent for parent in (parent_a, parent_b)}
            if generation_best is not None:
                reference_candidates["generation_best"] = generation_best
            mutation_context = mutation_context_from_candidate(
                feedback_parent,
                generation=generation,
                index=context_index,
                reflection_type=mutation_name,
                error_memory=error_memory,
                evolution_candidate=child,
                parent_objectives=parent_objectives,
                reference_candidates=reference_candidates,
            )
            if mutation_name == "strategy":
                child = mutation.mutate(
                    child,
                    mutation_context,
                    artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
                    mutation_intent=mutation_intent,
                )
            else:
                child = mutation.mutate(
                    child,
                    mutation_context,
                    artifact_dir=(artifact_root / child.id) if artifact_root is not None else None,
                )
            mutation_record = child.metadata.get("mutation") or {}
            mutation_applied = bool(mutation_record.get("applied"))
            mutation_error = mutation_record.get("reflection_error") or mutation_record.get("rewrite_error")
            child = replace(child, timing={
                **child.timing,
                "mutation": {
                    "operation_type": "mutation",
                    "started_at": mutation_started_at,
                    "finished_at": utc_now(),
                    "generation_only_duration_seconds": max(0.0, time.monotonic() - mutation_started),
                    "parent_selection_duration_seconds": parent_selection_duration,
                    "status": "success" if mutation_applied else "failed",
                    "error": mutation_error,
                },
            })
        offspring.append(child)
    return offspring


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


def choose_mutation(feedback_parent: Candidate, rng: random.Random) -> str:
    """Choose a mutation type from the parent's latest evaluation.

    A failed game still takes the code-mutation path so the generated agent
    can address implementation-level failures. Once simplicity is above 50,
    the code is considered strong enough to favor strategy exploration:
    90% strategy mutation and 10% code mutation. All other successful
    candidates retain the default 50/50 split.
    """
    evidence = feedback_parent.metadata.get("reflection_evidence") or {}
    failure_stage = evidence.get("failure_stage") or feedback_parent.failure_stage
    if failure_stage or feedback_parent.status == "failed":
        return "code"
    if number_or_none(feedback_parent.fitness_objectives.get("game_performance")) == FAILED_GAME_PERFORMANCE:
        return "code"
    game = evidence.get("game") or feedback_parent.game_eval_result or {}
    if evidence and (
        int(game.get("completed_match_count") or 0) != int(game.get("expected_match_count") or 180)
        or number_or_none(feedback_parent.fitness_objectives.get("game_performance")) == FAILED_GAME_PERFORMANCE
    ):
        return "code"
    quality = evidence.get("code_quality") or feedback_parent.code_quality_result.get("code_quality_breakdown") or {}
    if evidence and (
        int(quality.get("warning_count") or 0) > 0
        or (number_or_none(quality.get("function_score")) is not None and number_or_none(quality.get("function_score")) < 50)
        or (number_or_none(quality.get("strategy_alignment_score")) is not None and number_or_none(quality.get("strategy_alignment_score")) < 5)
    ):
        return "code"
    # Valid simplicity scores are in [0, 100]; retain the old midpoint-style
    # routing threshold after removing the obsolete +500 score base.
    if (number_or_none(feedback_parent.fitness_objectives.get("code_quality")) or 0.0) > 50:
        return "strategy" if rng.random() < 0.9 else "code"
    return "strategy" if rng.random() < 0.5 else "code"

def mutation_context_from_candidate(
    candidate: Candidate,
    *,
    generation: int,
    index: int,
    reflection_type: str | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
    evolution_candidate: Candidate | None = None,
    parent_objectives: dict[str, dict[str, float]] | None = None,
    reference_candidates: dict[str, Candidate] | None = None,
) -> ReflectionContext:
    return build_reflection_context(
        candidate,
        generation=generation,
        index=index,
        reflection_type=reflection_type,
        error_memory=error_memory,
        evolution_candidate=evolution_candidate,
        parent_objectives=parent_objectives,
        reference_candidates=reference_candidates,
    )


def number_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None
