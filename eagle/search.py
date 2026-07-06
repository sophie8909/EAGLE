"""NSGA-II search loop for prompt-generated Java MicroRTS agents."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2

from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.microrts_runner import MatchResult, run_microrts_match
from evaluation.nsga2_objectives import build_objectives
from evaluation.strategy_alignment import StrategyAlignmentResult, evaluate_strategy_alignment
from generation.backend import GenerationBackend, build_generation_backend
from generation.java_agent_generator import GeneratedJavaAgent, generate_java_agent

from .artifacts import append_result, write_candidate_artifacts, write_generation_manifest, write_summary
from .candidate import Candidate
from .config import ExperimentConfig
from .offspring import make_offspring, mutate_prompt
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


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    agent: GeneratedJavaAgent | None
    compile_result: CompileResult | None
    match_results: list[MatchResult]
    game_metrics: GameMetrics | None
    alignment_result: StrategyAlignmentResult | None
    error: str | None = None


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
                strategy_prompt=mutate_prompt(source.strategy_prompt, config.mutation_suffix, clone_index=len(population)),
                metadata={"operator": "seed_mutation"},
            )
        )
    return population[: config.population_size]


def evaluate_population(
    population: list[Candidate],
    *,
    generation: int,
    config: ExperimentConfig,
    backend: GenerationBackend,
    alignment_backend: str,
    generated_agents_dir: Path,
    classes_dir: Path,
    candidates_dir: Path,
    results_path: Path,
    mock: bool,
) -> list[Candidate]:
    evaluated: list[Candidate] = []
    for index, candidate in enumerate(population):
        evaluation = evaluate_candidate(
            candidate,
            config=config,
            backend=backend,
            alignment_backend=alignment_backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            mock=mock,
            ordinal=index,
        )
        write_candidate_artifacts(candidates_dir, evaluation)
        append_result(results_path, evaluation)
        evaluated.append(evaluation.candidate)
        print_progress(
            generation=generation,
            index=index,
            population_size=len(population),
            evaluation=evaluation,
        )
    return evaluated


def evaluate_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    alignment_backend: str,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    ordinal: int,
) -> CandidateEvaluation:
    agent: GeneratedJavaAgent | None = None
    compile_result: CompileResult | None = None
    match_results: list[MatchResult] = []
    game_metrics: GameMetrics | None = None
    alignment_result: StrategyAlignmentResult | None = None
    error: str | None = None

    try:
        agent = generate_java_agent(candidate, backend, generated_agents_dir)
        compile_result = compile_generated_agent(
            agent.source_path,
            microrts_dir=config.microrts_dir,
            output_dir=classes_dir / candidate.id,
            mock=mock,
        )
        if compile_result.ok:
            for match_index in range(config.matches_per_candidate):
                match_results.append(
                    run_microrts_match(
                        microrts_dir=config.microrts_dir,
                        classes_dir=classes_dir / candidate.id,
                        agent_class=agent.qualified_class_name,
                        opponent=config.opponent,
                        tick_limit=config.tick_limit,
                        match_index=match_index,
                        mock=mock,
                        mock_score=config.mock_score_base + config.mock_score_step * (ordinal + match_index),
                    )
                )
            game_metrics = compute_game_metrics(match_results)
            try:
                alignment_result = evaluate_strategy_alignment(
                    strategy_prompt=candidate.strategy_prompt,
                    generated_java_code=agent.source,
                    match_summary=json.dumps(game_metrics.match_summaries, ensure_ascii=False),
                    backend=alignment_backend,
                    base_url=config.llm_base_url,
                    model=config.llm_model,
                )
            except (RuntimeError, ValueError, OSError) as exc:
                alignment_result = StrategyAlignmentResult(score=0.0, rationale=f"Alignment evaluation failed: {exc}")
        else:
            game_metrics = compute_game_metrics([])
            alignment_result = StrategyAlignmentResult(score=0.0, rationale="Compile failed; alignment not evaluated.")
    except (RuntimeError, ValueError, OSError) as exc:
        error = str(exc)

    objectives = build_objectives(
        compile_result=compile_result,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
    )
    status = "evaluated" if compile_result is not None and compile_result.ok and error is None else "failed"
    evaluated_candidate = Candidate(
        id=candidate.id,
        generation=candidate.generation,
        parent_ids=candidate.parent_ids,
        strategy_prompt=candidate.strategy_prompt,
        generated_java_agent_path=str(agent.source_path) if agent else None,
        compile_status=compile_result.status if compile_result else "not_run",
        game_eval_result=game_metrics.to_json_dict() if game_metrics else {},
        strategy_alignment_result=alignment_result.to_json_dict() if alignment_result else {},
        fitness_objectives=objectives,
        status=status,
        metadata=candidate.metadata,
    )
    return CandidateEvaluation(
        candidate=evaluated_candidate,
        agent=agent,
        compile_result=compile_result,
        match_results=match_results,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
        error=error,
    )


def print_progress(
    *,
    generation: int,
    index: int,
    population_size: int,
    evaluation: CandidateEvaluation,
) -> None:
    candidate = evaluation.candidate
    detail = ""
    if evaluation.error:
        detail = f" error={evaluation.error}"
    elif evaluation.compile_result is not None and not evaluation.compile_result.ok:
        stderr = (evaluation.compile_result.stderr or "").splitlines()
        detail = f" compile_error={stderr[0] if stderr else evaluation.compile_result.returncode}"
    print(
        f"[gen {generation} cand {index + 1}/{population_size}] "
        f"{candidate.id} status={candidate.status} objectives={candidate.fitness_objectives}{detail}",
        flush=True,
    )
