"""Canonical evolutionary search for prompt-generated Java MicroRTS agents.

This module owns experiment lifecycle, offspring orchestration, and population
updates. Evaluation owns the shared child pipeline. The canonical entrypoint
is ``run_search``.
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
from typing import Callable

from generation.backend import MockGenerationBackend, build_generation_backend
from .aos import (
    AdaptiveOperatorSelection,
    OPERATOR_TO_MUTATION,
    OperatorReward,
    calculate_operator_reward,
)
from .artifacts import (
    write_aos_reward_artifact,
    write_prompt_snapshot,
    write_resolved_config,
    write_summary,
)
from .run_artifacts import (
    finalize_run,
    initialize_run_manifest,
    mark_run_interrupted,
    record_error_memory,
    record_generation,
)
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import CrossoverContext, crossover
from .evaluation import evaluate_population, preflight_evaluation_opponents
from .mutation import ReflectionContext, build_reflection_backend
from .reflection_context import build_reflection_context
from .llm import LLMCallLogger
from .timing import Stopwatch, append_event, build_generation_event, utc_now
from .llm import LLMClient, LLMServerError
from .prompts import normalize_prompt
from .rewrite import PromptRewriteMutation
from .strategy_reflection import MockRoleBackend, StrategyReflectionMutation, select_strategy_mutation_intent
from .strategy_diversity import (
    archive_niches,
    diversity_console_summary,
    ensure_strategy_archive,
    generation_diversity_metrics,
    update_strategy_archive,
)
from .opponent_archive import ensure_opponent_archive, update_opponent_archive
from .selection import (
    select_parent,
    best_candidate,
    population_signature,
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
    """Run the EA and preserve the last completed generation on Ctrl-C."""

    active_run: list[Path | None] = [None]
    try:
        return _run_search_impl(
            config,
            config_path=config_path,
            mock=mock,
            run_id=run_id,
            on_run_created=lambda path: active_run.__setitem__(0, path),
        )
    except KeyboardInterrupt:
        if active_run[0] is not None:
            mark_run_interrupted(active_run[0])
        raise


def _run_search_impl(
    config: ExperimentConfig,
    *,
    config_path: Path,
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
    preflight_evaluation_opponents(config, mock=mock)
    rng = random.Random(config.random_seed)
    aos = AdaptiveOperatorSelection(config.aos)

    backend_name = "mock" if mock else config.generation_backend
    client = LLMClient(config.llm_base_url, config.llm_model, temperature=config.llm_temperature, max_output_tokens=config.llm_max_tokens)
    shared_client = client
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
    if on_run_created is not None:
        on_run_created(run_dir)
    ensure_strategy_archive(run_dir)
    ensure_opponent_archive(run_dir)

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
        backend_name=backend_name,
    )
    enabled_roles = {"coach"}
    if config.match_commentator_enabled:
        enabled_roles.add("match_commentator")
    strategy_role_backend = MockRoleBackend() if mock else client.prompt_backend(operation="match_commentator", temperature=config.match_commentator_temperature)
    strategy_reflection_mutation = StrategyReflectionMutation(
        strategy_role_backend,
        max_attempts=config.mutation_max_attempts,
        max_prompt_chars=60_000,
        model_identity=None if backend_name == "mock" else client.model,
        enabled_roles=enabled_roles,
        selection_seed=config.random_seed,
        sample_budget=config.match_commentator_sample_count,
    )
    write_resolved_config(
        run_dir,
        config,
        mock=mock,
        client=client,
    )
    write_prompt_snapshot(run_dir, config)
    # Initialization is followed by the same evaluation boundary used for
    # every later offspring generation.
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
        llm_client=shared_client,
    )
    archive_before = archive_niches(run_dir)
    update_strategy_archive(run_dir, evaluated_population)
    update_opponent_archive(run_dir, evaluated_population)
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
        aos=aos.initial_generation_record(),
    )
    print(diversity_console_summary(0, generation_diversity), flush=True)
    error_memory = record_error_memory(run_dir, evaluated_population)

    population_state_signature = population_signature(evaluated_population)
    stagnation_count = 0
    completed_generation = 0
    stop_reason: str | None = None

    # One fixed EA step per iteration: select parents -> create offspring ->
    # evaluate offspring -> select survivors.
    for generation in range(1, config.generations):
        # Operators produce only child genotypes; evaluation starts at the shared boundary below.
        offspring = create_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            mutations={"strategy": strategy_reflection_mutation, "code": code_mutation},
            aos=aos,
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
            llm_client=shared_client,
        )
        evaluated_offspring, rewards = apply_aos_rewards(
            evaluated_population,
            evaluated_offspring,
            config=config,
            aos=aos,
            candidates_dir=candidates_dir,
        )
        aos_record = aos.update_generation(rewards)
        archive_before = archive_niches(run_dir)
        update_strategy_archive(run_dir, evaluated_offspring)
        update_opponent_archive(run_dir, evaluated_offspring)
        error_memory = record_error_memory(run_dir, evaluated_offspring)
        append_event(run_dir / "timing.jsonl", build_generation_event(
            run_id=active_run_id,
            generation=generation,
            candidates=evaluated_offspring,
            span=generation_span.finish(),
        ))
        # Survival selection is the only population update boundary and consumes
        # the objectives already persisted by evaluate_population.
        evaluated_population = select_next_generation(
            evaluated_population,
            evaluated_offspring,
            population_size=config.population_size,
            rng=rng,
        )
        current_population_signature = population_signature(evaluated_population)
        if current_population_signature == population_state_signature:
            stagnation_count += 1
        else:
            population_state_signature = current_population_signature
            stagnation_count = 0
        generation_diversity = generation_diversity_metrics(evaluated_population, previous_archive_niches=archive_before)
        record_generation(
            run_dir,
            generation,
            evaluated_population,
            diversity=generation_diversity,
            aos=aos_record,
        )
        print(diversity_console_summary(generation, generation_diversity), flush=True)
        completed_generation = generation
        if (
            config.stagnation_generations > 0
            and stagnation_count >= config.stagnation_generations
        ):
            stop_reason = f"stagnation_{config.stagnation_generations}_generations"
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
        raise LLMServerError(f"Configured llama.cpp endpoint preflight failed at {url}: {exc}") from exc


def initialize_population(config: ExperimentConfig) -> list[Candidate]:
    population = [Candidate(generation=0, strategy_prompt=prompt, previous_code="", generation_prompt=config.generation_prompt, operator="seed", metadata={"seed_index": index}) for index, prompt in enumerate(config.seed_prompts)]
    while len(population) < config.population_size:
        seed_index = len(population)
        population.append(Candidate(generation=0, strategy_prompt=config.seed_prompts[seed_index % len(config.seed_prompts)], previous_code="", generation_prompt=config.generation_prompt, operator="seed", metadata={"seed_index": seed_index}))
    return population[: config.population_size]


def create_offspring(
    population: list[Candidate], *, config: ExperimentConfig, generation: int,
    rng: random.Random, mutations: dict[str, PromptRewriteMutation],
    aos: AdaptiveOperatorSelection, artifact_root: Path | None = None,
    error_memory: tuple[dict[str, object], ...] = (),
) -> list[Candidate]:
    """Create the next generation's genotypes without evaluating them.

    Parent selection, optional three-component crossover, and optional
    prompt-only mutation happen here. Java generation, compilation, matches,
    and objective calculation remain in :func:`evaluate_population`.
    """
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
            operator_used = aos.select_operator(rng)
            mutation_name = OPERATOR_TO_MUTATION[operator_used]
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
                key=lambda item: float((item.game_eval_result or {}).get("game_performance", float("-inf"))),
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
            child = replace(child, metadata={
                **child.metadata,
                "aos": {
                    "parent_candidate_id": parent_a.id,
                    "child_candidate_id": child.id,
                    "operator_used": operator_used,
                    "selection_probability": aos.probability(operator_used),
                },
            })
        offspring.append(child)
    return offspring


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


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


def apply_aos_rewards(
    parents: list[Candidate],
    children: list[Candidate],
    *,
    config: ExperimentConfig,
    aos: AdaptiveOperatorSelection,
    candidates_dir: Path,
) -> tuple[list[Candidate], list[OperatorReward]]:
    """Assign rewards only after all children in the generation are evaluated."""

    parent_by_id = {candidate.id: candidate for candidate in parents}
    updated: list[Candidate] = []
    rewards: list[OperatorReward] = []
    for child in children:
        aos_metadata = child.metadata.get("aos") or {}
        operator = aos_metadata.get("operator_used")
        parent_id = aos_metadata.get("parent_candidate_id")
        if not operator or not parent_id or parent_id not in parent_by_id:
            updated.append(child)
            continue
        reward = calculate_operator_reward(
            parent_by_id[parent_id], child, operator=operator, config=config.aos,
        )
        reward_metadata = {**aos_metadata, **reward.to_dict()}
        child = replace(child, metadata={**child.metadata, "aos": reward_metadata})
        write_aos_reward_artifact(candidates_dir, reward_metadata)
        updated.append(child)
        rewards.append(reward)
    return updated, rewards
