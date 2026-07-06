"""NSGA-II search loop for prompt-generated Java MicroRTS agents."""

from __future__ import annotations

import json
import math
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

from .candidate import Candidate
from .config import ExperimentConfig


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
        offspring = make_offspring(evaluated_population, config=config, generation=generation, rng=rng)
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
    write_summary(run_dir, config=config, final_population=evaluated_population, best_candidate=best, mock=mock)
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


def make_offspring(
    population: list[Candidate],
    *,
    config: ExperimentConfig,
    generation: int,
    rng: random.Random,
) -> list[Candidate]:
    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        parent_a = tournament_select(population, rng)
        parent_b = tournament_select(population, rng)
        operator = "mutation"
        if len(population) > 1 and rng.random() < config.crossover_rate:
            prompt = crossover_prompts(parent_a.strategy_prompt, parent_b.strategy_prompt)
            parent_ids = (parent_a.id, parent_b.id)
            operator = "crossover"
        else:
            prompt = parent_a.strategy_prompt
            parent_ids = (parent_a.id,)
        if rng.random() < config.mutation_rate:
            prompt = mutate_prompt(prompt, config.mutation_suffix, clone_index=len(offspring))
            operator = f"{operator}+mutation" if operator == "crossover" else "mutation"
        offspring.append(
            Candidate(
                generation=generation,
                parent_ids=parent_ids,
                strategy_prompt=prompt,
                metadata={"operator": operator},
            )
        )
    return offspring


def mutate_prompt(prompt: str, mutation_suffix: str, *, clone_index: int) -> str:
    return (
        f"{prompt.rstrip()}\n\n"
        f"Mutation {clone_index + 1}: {mutation_suffix} "
        "Emphasize one concrete MicroRTS behavior such as economy, defense, scouting, or pressure."
    )


def crossover_prompts(prompt_a: str, prompt_b: str) -> str:
    return (
        "Blend these two MicroRTS strategy prompts into one Java-agent generation request.\n\n"
        f"Parent strategy A:\n{prompt_a.rstrip()}\n\n"
        f"Parent strategy B:\n{prompt_b.rstrip()}\n\n"
        "Child strategy: keep the strongest compatible ideas from both parents and avoid runtime LLM calls."
    )


def tournament_select(population: list[Candidate], rng: random.Random) -> Candidate:
    if len(population) == 1:
        return population[0]
    first, second = rng.sample(population, 2)
    return better_candidate(first, second, rng)


def better_candidate(first: Candidate, second: Candidate, rng: random.Random) -> Candidate:
    rank_a = getattr(first, "pareto_rank", float("inf"))
    rank_b = getattr(second, "pareto_rank", float("inf"))
    if rank_a != rank_b:
        return first if rank_a < rank_b else second
    crowd_a = getattr(first, "crowding_distance", 0.0)
    crowd_b = getattr(second, "crowding_distance", 0.0)
    if crowd_a != crowd_b:
        return first if crowd_a > crowd_b else second
    if dominates(first, second):
        return first
    if dominates(second, first):
        return second
    return rng.choice([first, second])


def select_next_generation(
    population: list[Candidate],
    offspring: list[Candidate],
    *,
    population_size: int,
) -> list[Candidate]:
    combined = population + offspring
    fronts = fast_non_dominated_sort(combined)
    next_generation: list[Candidate] = []
    for rank, front in enumerate(fronts):
        calculate_crowding_distance(front)
        for candidate in front:
            object.__setattr__(candidate, "metadata", {**candidate.metadata, "pareto_rank": rank})
        if len(next_generation) + len(front) <= population_size:
            next_generation.extend(front)
            continue
        remaining = population_size - len(next_generation)
        sorted_front = sorted(front, key=lambda item: getattr(item, "crowding_distance", 0.0), reverse=True)
        next_generation.extend(sorted_front[:remaining])
        break
    return next_generation


def assign_rank_and_crowding(population: list[Candidate]) -> list[list[Candidate]]:
    fronts = fast_non_dominated_sort(population)
    for rank, front in enumerate(fronts):
        calculate_crowding_distance(front)
        for candidate in front:
            object.__setattr__(candidate, "metadata", {**candidate.metadata, "pareto_rank": rank})
            object.__setattr__(candidate, "pareto_rank", rank)
    return fronts


def dominates(first: Candidate, second: Candidate) -> bool:
    first_values = first.objective_vector()
    second_values = second.objective_vector()
    no_worse = all(a >= b for a, b in zip(first_values, second_values))
    better_once = any(a > b for a, b in zip(first_values, second_values))
    return no_worse and better_once


def fast_non_dominated_sort(population: list[Candidate]) -> list[list[Candidate]]:
    if not population:
        return []
    domination_count = [0] * len(population)
    dominated_solutions: list[list[int]] = [[] for _ in population]
    fronts: list[list[Candidate]] = []
    for i in range(len(population)):
        for j in range(i + 1, len(population)):
            if dominates(population[i], population[j]):
                dominated_solutions[i].append(j)
                domination_count[j] += 1
            elif dominates(population[j], population[i]):
                dominated_solutions[j].append(i)
                domination_count[i] += 1
    current_front = [i for i, count in enumerate(domination_count) if count == 0]
    while current_front:
        fronts.append([population[i] for i in current_front])
        next_front: list[int] = []
        for i in current_front:
            for j in dominated_solutions[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    next_front.append(j)
        current_front = next_front
    return fronts


def calculate_crowding_distance(front: list[Candidate]) -> list[float]:
    if not front:
        return []
    if len(front) <= 2:
        for candidate in front:
            object.__setattr__(candidate, "crowding_distance", float("inf"))
        return [float("inf")] * len(front)

    distances = {candidate.id: 0.0 for candidate in front}
    objective_count = len(front[0].objective_vector())
    for objective_index in range(objective_count):
        sorted_front = sorted(front, key=lambda item: item.objective_vector()[objective_index])
        distances[sorted_front[0].id] = float("inf")
        distances[sorted_front[-1].id] = float("inf")
        min_value = sorted_front[0].objective_vector()[objective_index]
        max_value = sorted_front[-1].objective_vector()[objective_index]
        denominator = max_value - min_value
        if denominator == 0:
            continue
        for index in range(1, len(sorted_front) - 1):
            candidate = sorted_front[index]
            if math.isinf(distances[candidate.id]):
                continue
            previous_value = sorted_front[index - 1].objective_vector()[objective_index]
            next_value = sorted_front[index + 1].objective_vector()[objective_index]
            distances[candidate.id] += (next_value - previous_value) / denominator

    for candidate in front:
        object.__setattr__(candidate, "crowding_distance", distances[candidate.id])
    return [distances[candidate.id] for candidate in front]


def best_candidate(population: list[Candidate]) -> Candidate | None:
    if not population:
        return None
    assign_rank_and_crowding(population)
    return sorted(
        population,
        key=lambda item: (
            getattr(item, "pareto_rank", float("inf")),
            -sum(item.objective_vector()),
            -getattr(item, "crowding_distance", 0.0),
        ),
    )[0]


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


def append_result(path: Path, evaluation: CandidateEvaluation) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False))
        handle.write("\n")


def write_candidate_artifacts(candidates_dir: Path, evaluation: CandidateEvaluation) -> None:
    candidate_dir = candidates_dir / evaluation.candidate.id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "strategy_prompt.txt").write_text(evaluation.candidate.strategy_prompt, encoding="utf-8")
    if evaluation.agent is not None:
        (candidate_dir / "generated_java_source.java").write_text(evaluation.agent.source, encoding="utf-8")
    write_json(candidate_dir / "compile_result.json", compile_to_dict(evaluation.compile_result))
    write_json(candidate_dir / "raw_microrts_result.json", [match_to_dict(result) for result in evaluation.match_results])
    write_json(
        candidate_dir / "game_metrics.json",
        evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else {},
    )
    write_json(
        candidate_dir / "strategy_alignment.json",
        evaluation.alignment_result.to_json_dict() if evaluation.alignment_result else {},
    )
    write_json(candidate_dir / "objectives.json", evaluation.candidate.fitness_objectives)
    write_json(candidate_dir / "individual.json", evaluation.candidate.to_json_dict())


def write_generation_manifest(run_dir: Path, generation: int, population: list[Candidate]) -> None:
    payload = [candidate.to_json_dict() for candidate in population]
    write_json(run_dir / f"generation_{generation:03d}_population.json", payload)


def write_summary(
    run_dir: Path,
    *,
    config: ExperimentConfig,
    final_population: list[Candidate],
    best_candidate: Candidate | None,
    mock: bool,
) -> None:
    fronts = assign_rank_and_crowding(final_population)
    payload = {
        "mock": mock,
        "generations": config.generations,
        "population_size": config.population_size,
        "objectives": ["game_performance", "strategy_alignment"],
        "best_candidate": None if best_candidate is None else best_candidate.to_json_dict(),
        "pareto_fronts": [[candidate.id for candidate in front] for front in fronts],
        "final_population": [candidate.to_json_dict() for candidate in final_population],
    }
    write_json(run_dir / "summary.json", payload)


def evaluation_to_dict(evaluation: CandidateEvaluation) -> dict:
    return {
        "candidate": evaluation.candidate.to_json_dict(),
        "agent": None
        if evaluation.agent is None
        else {
            "class_name": evaluation.agent.class_name,
            "qualified_class_name": evaluation.agent.qualified_class_name,
            "source_path": str(evaluation.agent.source_path),
        },
        "compile": compile_to_dict(evaluation.compile_result),
        "matches": [match_to_dict(result) for result in evaluation.match_results],
        "game_metrics": evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else None,
        "strategy_alignment": evaluation.alignment_result.to_json_dict() if evaluation.alignment_result else None,
        "objectives": evaluation.candidate.fitness_objectives,
        "error": evaluation.error,
    }


def compile_to_dict(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "status": result.status,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def match_to_dict(result: MatchResult) -> dict:
    return {
        "ok": result.ok,
        "score": result.score,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "raw_result": result.raw_result,
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
