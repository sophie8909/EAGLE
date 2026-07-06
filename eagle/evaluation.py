"""Candidate evaluation for generated-agent searches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.microrts_runner import MatchResult, run_microrts_match
from evaluation.nsga2_objectives import build_objectives
from evaluation.strategy_alignment import StrategyAlignmentResult, evaluate_strategy_alignment
from generation.backend import GenerationBackend
from generation.java_agent_generator import GeneratedJavaAgent, generate_java_agent

from .artifacts import append_result, write_candidate_artifacts
from .candidate import Candidate
from .config import ExperimentConfig


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    agent: GeneratedJavaAgent | None
    compile_result: CompileResult | None
    match_results: list[MatchResult]
    game_metrics: GameMetrics | None
    alignment_result: StrategyAlignmentResult | None
    error: str | None = None


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
        # Java generation turns the strategy prompt into one source file.
        agent = generate_java_agent(candidate, backend, generated_agents_dir)

        # Java compilation decides whether the agent can be evaluated.
        compile_result = compile_generated_agent(
            agent.source_path,
            microrts_dir=config.microrts_dir,
            output_dir=classes_dir / candidate.id,
            mock=mock,
        )
        if compile_result.ok:
            # MicroRTS match execution produces raw match results for scoring.
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
            alignment_result = score_strategy_alignment(
                candidate=candidate,
                agent=agent,
                game_metrics=game_metrics,
                config=config,
                alignment_backend=alignment_backend,
            )
        else:
            game_metrics = compute_game_metrics([])
            alignment_result = StrategyAlignmentResult(score=0.0, rationale="Compile failed; alignment not evaluated.")
    except (RuntimeError, ValueError, OSError) as exc:
        error = str(exc)

    # Objective computation converts compile, match, and alignment results into fitness values.
    objectives = compute_objectives(
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


def score_strategy_alignment(
    *,
    candidate: Candidate,
    agent: GeneratedJavaAgent,
    game_metrics: GameMetrics,
    config: ExperimentConfig,
    alignment_backend: str,
) -> StrategyAlignmentResult:
    try:
        return evaluate_strategy_alignment(
            strategy_prompt=candidate.strategy_prompt,
            generated_java_code=agent.source,
            match_summary=json.dumps(game_metrics.match_summaries, ensure_ascii=False),
            backend=alignment_backend,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        return StrategyAlignmentResult(score=0.0, rationale=f"Alignment evaluation failed: {exc}")


def compute_objectives(
    *,
    compile_result: CompileResult | None,
    game_metrics: GameMetrics | None,
    alignment_result: StrategyAlignmentResult | None,
) -> dict[str, float]:
    return build_objectives(
        compile_result=compile_result,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
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
