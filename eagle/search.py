"""NSGA-II search loop for prompt-generated Java MicroRTS agents."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2

from generation.backend import build_generation_backend
from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE

from .artifacts import write_generation_manifest, write_resolved_config, write_summary
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import Crossover, CrossoverContext
from .evaluation import evaluate_population
from .mutation import Mutation, MutationContext
from .llm_logging import LLMCallLogger
from .offspring import normalize_prompt
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


def run_search(
    config: ExperimentConfig,
    *,
    config_path: Path,
    mock: bool = False,
    run_id: str | None = None,
) -> SearchResult:
    config.validate()
    rng = random.Random(config.random_seed)
    # Search owns the algorithm order; the operator classes own only their local behavior.
    strategy_mutation = Mutation(config, method="strategy_reflection")
    code_mutation = Mutation(config, method="code_generation_reflection")
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

    llm_logger = LLMCallLogger(run_dir / "llm_logs")
    generation_backend = build_generation_backend(
        "mock" if mock else config.generation_backend,
        base_url=config.llm_base_url,
        model=config.llm_model,
        logger=llm_logger,
    )
    write_resolved_config(run_dir, config, mock=mock)
    results_path = run_dir / "results.jsonl"

    # NSGA-II begins with a complete evaluated population so every candidate has objectives.
    population = initialize_population(config)
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
    )

    for generation in range(1, config.generations):
        # Rank and crowding distance guide tournament parent selection.
        assign_rank_and_crowding(evaluated_population)

        # Selection chooses parents, crossover chooses components, and mutation can adjust the child afterward.
        offspring = create_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            mutations=(strategy_mutation, code_mutation),
            crossover=crossover,
            selection=selection,
        )

        # New children must be evaluated before survivor selection can compare them to parents.
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
        )

        # Survivor selection keeps the best Pareto fronts and preserves spread within a partial front.
        evaluated_population = select_next_generation(
            evaluated_population,
            evaluated_offspring,
            population_size=config.population_size,
        )

        # Save the generation view after survivor selection so artifacts match the active population.
        write_generation_manifest(run_dir, generation, evaluated_population)

    # Final rank/crowding data makes the summary and best-candidate choice inspectable.
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
    )
    return SearchResult(run_dir=run_dir, final_population=evaluated_population, best_candidate=best)


def initialize_population(config: ExperimentConfig) -> list[Candidate]:
    # Generation zero contains independent seeds; candidate ancestry starts after evaluation.
    population = [
        Candidate(
            generation=0,
            strategy_prompt=prompt,
            previous_code="",
            generation_prompt=config.generation_prompt,
            operator="seed",
            metadata={"seed_index": index},
        )
        for index, prompt in enumerate(config.seed_prompts)
    ]
    while len(population) < config.population_size:
        seed_index = len(population)
        prompt = config.seed_prompts[seed_index % len(config.seed_prompts)]
        population.append(Candidate(
            generation=0,
            strategy_prompt=prompt,
            previous_code="",
            generation_prompt=config.generation_prompt,
            operator="seed",
            metadata={"seed_index": seed_index},
        ))
    return population[: config.population_size]


def create_offspring(
    population: list[Candidate],
    *,
    config: ExperimentConfig,
    generation: int,
    rng: random.Random,
    mutations: tuple[Mutation, Mutation],
    crossover: Crossover,
    selection: Selection,
) -> list[Candidate]:
    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        context_index = len(offspring)

        # Binary tournament uses current rank/crowding values to pick each parent.
        parent_a = selection.select(population, 1, SelectionContext(rng=rng))[0]
        parent_b = selection.select(population, 1, SelectionContext(rng=rng))[0]

        # Crossover chooses each candidate component from either parent; otherwise the child starts as a copy.
        if len(population) > 1 and rng.random() < config.crossover_rate:
            child = crossover.crossover(
                parent_a,
                parent_b,
                CrossoverContext(generation=generation, index=context_index, rng=rng),
            )
        else:
            child = Candidate(
                generation=generation,
                parent_ids=(parent_a.id,),
                strategy_prompt=normalize_prompt(
                    parent_a.strategy_prompt,
                    max_chars=config.max_prompt_chars,
                    max_lines=config.max_prompt_lines,
                ),
                previous_code=parent_a.inheritable_previous_code,
                generation_prompt=parent_a.generation_prompt,
                operator="copy",
                strategy_parent_id=parent_a.id,
                previous_code_parent_id=parent_a.id,
                generation_prompt_parent_id=parent_a.id,
                source_candidate_ids=(parent_a.id,),
            )

        # Mutation is usually 50/50, but failed agents first get code-generation reflection.
        if rng.random() < config.mutation_rate:
            feedback_parent = parent_for_component(
                child.strategy_parent_id,
                (parent_a, parent_b),
            )
            mutation = choose_mutation(feedback_parent, mutations, rng)
            child = mutation.mutate(
                child,
                mutation_context_from_candidate(feedback_parent, generation=generation, index=context_index),
            )

        offspring.append(child)
    return offspring


def parent_for_component(parent_id: str | None, parents: tuple[Candidate, Candidate]) -> Candidate:
    """Resolve recorded component provenance without comparing component text."""

    for parent in parents:
        if parent.id == parent_id:
            return parent
    raise ValueError(f"Recorded component parent {parent_id!r} is not a direct parent.")


def choose_mutation(feedback_parent: Candidate, mutations: tuple[Mutation, Mutation], rng: random.Random) -> Mutation:
    # Failed agents need code-generation reflection first because their Java did not become a valid evaluated agent.
    game_performance = number_or_none(feedback_parent.fitness_objectives.get("game_performance"))
    if game_performance == FAILED_GAME_PERFORMANCE:
        return mutations[1]
    return rng.choice(mutations)


def mutation_context_from_candidate(candidate: Candidate, *, generation: int, index: int) -> MutationContext:
    # Game-performance and code-quality feedback improve separate evolutionary components.
    return MutationContext(
        generation=generation,
        index=index,
        game_performance=number_or_none(candidate.fitness_objectives.get("game_performance")),
        player_resource=number_or_none(candidate.game_eval_result.get("player0_resource")),
        enemy_resource=number_or_none(candidate.game_eval_result.get("player1_resource")),
        resource_breakdown=candidate.game_eval_result.get("resource_breakdown") or {},
        performance_breakdown=candidate.game_eval_result.get("performance_breakdown") or {},
        temporal_summary=candidate.game_eval_result.get("temporal_summary") or {},
        compilation_score=number_or_none((candidate.code_quality_result.get("code_quality_breakdown") or {}).get("compilation_score")),
        compiler_errors=tuple((candidate.code_quality_result.get("code_quality_breakdown") or {}).get("compiler_errors") or []),
        compiler_warnings=tuple((candidate.code_quality_result.get("code_quality_breakdown") or {}).get("compiler_warnings") or []),
        strategy_region_score=number_or_none((candidate.code_quality_result.get("code_quality_breakdown") or {}).get("strategy_region_score")),
        strategy_region_validation=candidate.code_quality_result.get("strategy_region_validation") or {},
        static_quality_score=number_or_none((candidate.code_quality_result.get("code_quality_breakdown") or {}).get("static_quality_score")),
        static_metrics=(candidate.code_quality_result.get("code_quality_breakdown") or {}).get("static_metrics") or {},
        compile_success=candidate.compile_status == "success",
        validation_success=candidate.metadata.get("failure_category") != "Java validation failure",
        runtime_success=candidate.status == "evaluated",
        error_category=str(candidate.metadata.get("failure_category") or ""),
        error_message=str(candidate.metadata.get("failure_reason") or ""),
    )


def number_or_none(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
