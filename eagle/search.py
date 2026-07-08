"""NSGA-II search loop for prompt-generated Java MicroRTS agents."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2

from generation.backend import build_generation_backend

from .artifacts import write_generation_manifest, write_summary
from .candidate import Candidate
from .config import ExperimentConfig
from .crossover import Crossover, CrossoverContext
from .evaluation import evaluate_population
from .mutation import Mutation, MutationContext
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
    generation_backend = build_generation_backend(
        "mock" if mock else config.generation_backend,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    alignment_backend = "mock" if mock else config.alignment_backend

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

    results_path = run_dir / "results.jsonl"

    # NSGA-II begins with a complete evaluated population so every candidate has objectives.
    population = initialize_population(config, strategy_mutation)
    evaluated_population = evaluate_population(
        population,
        generation=0,
        config=config,
        backend=generation_backend,
        alignment_backend=alignment_backend,
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
            alignment_backend=alignment_backend,
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


def initialize_population(config: ExperimentConfig, mutation: Mutation) -> list[Candidate]:
    # Seed prompts are the first generation; extra slots are simple mutated copies of seeds.
    population = [
        Candidate(
            generation=0,
            strategy_prompt=prompt,
            previous_code="",
            generation_prompt=config.generation_prompt,
            metadata={"seed_index": index},
        )
        for index, prompt in enumerate(config.seed_prompts)
    ]
    while len(population) < config.population_size:
        source = population[len(population) % len(config.seed_prompts)]
        seed_child = Candidate(
            generation=0,
            parent_ids=(source.id,),
            strategy_prompt=source.strategy_prompt,
            previous_code=source.previous_code,
            generation_prompt=source.generation_prompt,
            metadata={"operator": "seed_mutation"},
        )
        population.append(mutation.mutate(seed_child, MutationContext(generation=0, index=len(population))))
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
                previous_code=parent_a.previous_code,
                generation_prompt=parent_a.generation_prompt,
                metadata={"operator": "mutation"},
            )

        # Mutation is applied after crossover/copy. The two reflection targets are selected 50/50.
        if rng.random() < config.mutation_rate:
            feedback_parent = parent_b if child.strategy_prompt == parent_b.strategy_prompt else parent_a
            mutation = rng.choice(mutations)
            child = mutation.mutate(
                child,
                mutation_context_from_candidate(feedback_parent, generation=generation, index=context_index),
            )

        offspring.append(child)
    return offspring


def mutation_context_from_candidate(candidate: Candidate, *, generation: int, index: int) -> MutationContext:
    # Game performance feedback and alignment feedback stay separate because they improve different fields.
    return MutationContext(
        generation=generation,
        index=index,
        game_performance=number_or_none(candidate.fitness_objectives.get("game_performance")),
        player_resource=number_or_none(candidate.game_eval_result.get("player_resource")),
        enemy_resource=number_or_none(candidate.game_eval_result.get("enemy_resource")),
        resource_breakdown=candidate.game_eval_result.get("resource_breakdown") or {},
        alignment_score=number_or_none(candidate.strategy_alignment_result.get("score")),
        alignment_reason=str(candidate.strategy_alignment_result.get("rationale", "")),
    )


def number_or_none(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None
