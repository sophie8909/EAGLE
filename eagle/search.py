"""Minimal EAGLE search loop for prompt-generated Java agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from shutil import copy2

from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.fitness import calculate_fitness
from evaluation.microrts_runner import MatchResult, run_microrts_match
from generation.backend import GenerationBackend, build_generation_backend
from generation.java_agent import GeneratedJavaAgent, generate_java_agent

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
    error: str | None = None


def run_search(
    config: ExperimentConfig,
    *,
    config_path: Path,
    mock: bool = False,
    run_id: str | None = None,
) -> SearchResult:
    config.validate()
    backend = build_generation_backend(
        "mock" if mock else config.generation_backend,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
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

    population = initialize_population(config)
    evaluated: list[Candidate] = []
    results_path = run_dir / "results.jsonl"
    stopped_reason: str | None = None
    for generation in range(config.generations):
        evaluated = []
        for index, candidate in enumerate(population):
            evaluated_candidate = evaluate_candidate(
                candidate,
                config=config,
                backend=backend,
                generated_agents_dir=generated_agents_dir,
                classes_dir=classes_dir,
                mock=mock,
                ordinal=index,
            )
            write_candidate_record(candidates_dir, evaluated_candidate)
            append_result(results_path, evaluated_candidate)
            evaluated.append(evaluated_candidate.candidate)
            print_progress(
                generation=generation,
                total_generations=config.generations,
                index=index,
                population_size=config.population_size,
                evaluation=evaluated_candidate,
            )
            if is_backend_unavailable(evaluated_candidate):
                stopped_reason = evaluated_candidate.error or "generation backend unavailable"
                best = max(evaluated, key=lambda item: item.fitness or 0.0) if evaluated else None
                write_summary(
                    run_dir,
                    config=config,
                    final_population=evaluated,
                    best_candidate=best,
                    mock=mock,
                    stopped_reason=stopped_reason,
                )
                print(f"stopped_reason={stopped_reason}", flush=True)
                return SearchResult(run_dir=run_dir, final_population=evaluated, best_candidate=best)
        if generation < config.generations - 1:
            population = next_generation(evaluated, config=config, generation=generation + 1)

    best = max(evaluated, key=lambda item: item.fitness or 0.0) if evaluated else None
    write_summary(run_dir, config=config, final_population=evaluated, best_candidate=best, mock=mock)
    return SearchResult(run_dir=run_dir, final_population=evaluated, best_candidate=best)


def initialize_population(config: ExperimentConfig) -> list[Candidate]:
    prompts = [
        Candidate(generation=0, prompt=prompt, metadata={"seed_index": index})
        for index, prompt in enumerate(config.seed_prompts)
    ]
    while len(prompts) < config.population_size:
        source = prompts[len(prompts) % len(config.seed_prompts)]
        prompts.append(
            Candidate(
                generation=0,
                parent_ids=(source.id,),
                prompt=source.prompt,
                metadata={"operator": "clone"},
            )
        )
    return prompts[: config.population_size]


def evaluate_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    ordinal: int,
) -> CandidateEvaluation:
    try:
        agent = generate_java_agent(candidate, backend, generated_agents_dir)
        compile_result = compile_generated_agent(
            agent.source_path,
            microrts_dir=config.microrts_dir,
            output_dir=classes_dir / candidate.id,
            mock=mock,
        )
        match_results: list[MatchResult] = []
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
        fitness = calculate_fitness(compile_result, match_results)
        status = "evaluated" if compile_result.ok and all(result.ok for result in match_results) else "failed"
        return CandidateEvaluation(
            candidate=candidate.with_updates(
                generated_source_path=str(agent.source_path),
                fitness=fitness,
                status=status,
            ),
            agent=agent,
            compile_result=compile_result,
            match_results=match_results,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        return CandidateEvaluation(
            candidate=candidate.with_updates(status="failed", fitness=0.0),
            agent=None,
            compile_result=None,
            match_results=[],
            error=str(exc),
        )


def next_generation(evaluated: list[Candidate], *, config: ExperimentConfig, generation: int) -> list[Candidate]:
    elites = sorted(evaluated, key=lambda item: item.fitness or 0.0, reverse=True)[: config.elite_count]
    next_population = [
        Candidate(
            id=elite.id,
            generation=generation,
            parent_ids=elite.parent_ids,
            prompt=elite.prompt,
            generated_source_path=elite.generated_source_path,
            fitness=elite.fitness,
            status="elite",
            metadata={**elite.metadata, "operator": "elite"},
        )
        for elite in elites
    ]
    while len(next_population) < config.population_size:
        parent = elites[len(next_population) % len(elites)]
        next_population.append(mutate_candidate(parent, config=config, generation=generation))
    return next_population


def mutate_candidate(parent: Candidate, *, config: ExperimentConfig, generation: int) -> Candidate:
    prompt = f"{parent.prompt.rstrip()}\n\nMutation guidance: {config.mutation_suffix}"
    return Candidate(
        generation=generation,
        parent_ids=(parent.id,),
        prompt=prompt,
        metadata={"operator": "mutation"},
    )


def print_progress(
    *,
    generation: int,
    total_generations: int,
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
    elif evaluation.match_results and not all(result.ok for result in evaluation.match_results):
        failed = next((result for result in evaluation.match_results if not result.ok), evaluation.match_results[0])
        stderr = (failed.stderr or "").splitlines()
        detail = f" match_error={stderr[0] if stderr else failed.returncode}"
    print(
        f"[gen {generation + 1}/{total_generations} cand {index + 1}/{population_size}] "
        f"{candidate.id} status={candidate.status} fitness={candidate.fitness}{detail}",
        flush=True,
    )


def append_result(path: Path, evaluation: CandidateEvaluation) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False))
        handle.write("\n")


def write_candidate_record(candidates_dir: Path, evaluation: CandidateEvaluation) -> None:
    path = candidates_dir / f"{evaluation.candidate.id}.json"
    path.write_text(json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary(
    run_dir: Path,
    *,
    config: ExperimentConfig,
    final_population: list[Candidate],
    best_candidate: Candidate | None,
    mock: bool,
    stopped_reason: str | None = None,
) -> None:
    payload = {
        "mock": mock,
        "generations": config.generations,
        "population_size": config.population_size,
        "stopped_reason": stopped_reason,
        "best_candidate": None if best_candidate is None else best_candidate.to_json_dict(),
        "final_population": [candidate.to_json_dict() for candidate in final_population],
    }
    (run_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
        "compile": None
        if evaluation.compile_result is None
        else {
            "ok": evaluation.compile_result.ok,
            "command": evaluation.compile_result.command,
            "stdout": evaluation.compile_result.stdout,
            "stderr": evaluation.compile_result.stderr,
            "returncode": evaluation.compile_result.returncode,
        },
        "matches": [
            {
                "ok": result.ok,
                "score": result.score,
                "command": result.command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
            for result in evaluation.match_results
        ],
        "error": evaluation.error,
    }


def is_backend_unavailable(evaluation: CandidateEvaluation) -> bool:
    return isinstance(evaluation.error, str) and "Generation backend request failed" in evaluation.error
