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
from .evaluation import evaluate_population
from .offspring import make_offspring, mutate_prompt, normalize_prompt
from .selection import (
    assign_rank_and_crowding,
    best_candidate,
    select_next_generation,
    tournament_select,
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
    population = initialize_population(config)
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
        assign_rank_and_crowding(evaluated_population)
        offspring = make_offspring(
            evaluated_population,
            config=config,
            generation=generation,
            rng=rng,
            parent_selector=tournament_select,
        )
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
        evaluated_population = select_next_generation(
            evaluated_population,
            evaluated_offspring,
            population_size=config.population_size,
        )
        write_generation_manifest(run_dir, generation, evaluated_population)

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
    population = [
        Candidate(generation=0, strategy_prompt=prompt, metadata={"seed_index": index})
        for index, prompt in enumerate(config.seed_prompts)
    ]
    while len(population) < config.population_size:
        source = population[len(population) % len(config.seed_prompts)]
        population.append(
            Candidate(
                generation=0,
                parent_ids=(source.id,),
                strategy_prompt=normalize_prompt(
                    mutate_prompt(source.strategy_prompt, config.mutation_suffix, clone_index=len(population)),
                    max_chars=config.max_prompt_chars,
                    max_lines=config.max_prompt_lines,
                ),
                metadata={"operator": "seed_mutation"},
            )
        )
    return population[: config.population_size]
