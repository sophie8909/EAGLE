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
from generation.java_agent_generator import GeneratedJavaAgent, ValidationResult, generate_java_agent_result

from .artifacts import append_result, write_candidate_artifacts
from .candidate import Candidate
from .config import ExperimentConfig
from .offspring import prompt_length


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    result: "CandidateResult"
    agent: GeneratedJavaAgent | None
    compile_result: CompileResult | None
    match_results: list[MatchResult]
    game_metrics: GameMetrics | None
    alignment_result: StrategyAlignmentResult | None
    error: str | None = None


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    parent_ids: tuple[str, ...]
    raw_llm_output: str = ""
    extracted_code: str = ""
    assembled_java: str = ""
    validation_result: ValidationResult | None = None
    compile_result: CompileResult | None = None
    match_result: list[MatchResult] | None = None
    final_score: dict[str, float] | None = None
    failure_category: str | None = None
    failure_reason: str | None = None


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
    failure_category: str | None = None
    failure_reason: str | None = None

    # LLM generation, extraction, scaffold assembly, and Java validation.
    generation_result = generate_java_agent_result(candidate, backend, generated_agents_dir)
    agent = generation_result.agent
    failure_category = generation_result.failure_category
    failure_reason = generation_result.failure_reason

    if agent is not None:
        # Java compilation decides whether the agent can be evaluated.
        try:
            compile_result = compile_agent_source(
                agent,
                config=config,
                classes_dir=classes_dir,
                candidate_id=candidate.id,
                mock=mock,
            )
        except (RuntimeError, OSError) as exc:
            failure_category = "Other"
            failure_reason = str(exc)
        if compile_result is not None and not compile_result.ok:
            failure_category = "Java compile failure"
            failure_reason = compile_error_message(compile_result)

    if agent is not None and compile_result is not None and compile_result.ok:
        # MicroRTS match execution produces raw match results for scoring.
        match_results, match_error = evaluate_matches(
            candidate=candidate,
            agent=agent,
            config=config,
            classes_dir=classes_dir,
            mock=mock,
            ordinal=ordinal,
        )
        if match_error is not None:
            failure_category = match_failure_category(match_error)
            failure_reason = match_error

    if failure_category is None and match_results:
        game_metrics = compute_game_metrics(match_results)
        alignment_result = score_strategy_alignment(
            candidate=candidate,
            agent=agent,
            game_metrics=game_metrics,
            config=config,
            alignment_backend=alignment_backend,
        )
    elif failure_category is not None:
        game_metrics = compute_game_metrics([])
        alignment_result = StrategyAlignmentResult(score=0.0, rationale=f"{failure_category}; alignment not evaluated.")

    # Objective computation converts compile, match, and alignment results into fitness values.
    length = prompt_length(candidate.strategy_prompt)
    objectives = compute_objectives(
        compile_result=compile_result,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
        prompt_chars=length["chars"],
        max_prompt_chars=config.max_prompt_chars,
        failure_category=failure_category,
    )
    status = "failed" if failure_category is not None else "evaluated"
    previous_code = agent.source if agent is not None else generation_result.assembled_java or candidate.previous_code
    evaluated_candidate = Candidate(
        id=candidate.id,
        generation=candidate.generation,
        parent_ids=candidate.parent_ids,
        strategy_prompt=candidate.strategy_prompt,
        previous_code=previous_code,
        generation_prompt=candidate.generation_prompt,
        generated_java_agent_path=str(agent.source_path) if agent else None,
        compile_status=compile_result.status if compile_result else "not_run",
        game_eval_result=game_metrics.to_json_dict() if game_metrics else {},
        strategy_alignment_result=alignment_result.to_json_dict() if alignment_result else {},
        fitness_objectives=objectives,
        status=status,
        metadata={
            **candidate.metadata,
            "prompt_chars": length["chars"],
            "prompt_lines": length["lines"],
            "failure_category": failure_category,
        },
    )
    result = CandidateResult(
        candidate_id=candidate.id,
        parent_ids=candidate.parent_ids,
        raw_llm_output=generation_result.raw_llm_output,
        extracted_code=generation_result.extracted_code,
        assembled_java=generation_result.assembled_java,
        validation_result=generation_result.validation_result,
        compile_result=compile_result,
        match_result=match_results,
        final_score=objectives,
        failure_category=failure_category,
        failure_reason=failure_reason,
    )
    return CandidateEvaluation(
        candidate=evaluated_candidate,
        result=result,
        agent=agent,
        compile_result=compile_result,
        match_results=match_results,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
        error=failure_reason,
    )


def compile_agent_source(
    agent: GeneratedJavaAgent,
    *,
    config: ExperimentConfig,
    classes_dir: Path,
    candidate_id: str,
    mock: bool,
) -> CompileResult:
    return compile_generated_agent(
        agent.source_path,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir / candidate_id,
        mock=mock,
    )


def evaluate_matches(
    *,
    candidate: Candidate,
    agent: GeneratedJavaAgent,
    config: ExperimentConfig,
    classes_dir: Path,
    mock: bool,
    ordinal: int,
) -> tuple[list[MatchResult], str | None]:
    match_results: list[MatchResult] = []
    try:
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
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)

    failed_matches = [result for result in match_results if not result.ok]
    if failed_matches:
        return match_results, match_error_message(failed_matches[0])
    return match_results, None


def compile_error_message(result: CompileResult) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr.splitlines()[0]
    return f"javac returned {result.returncode}"


def match_error_message(result: MatchResult) -> str:
    stderr = (result.stderr or "").strip()
    if stderr:
        return stderr.splitlines()[0]
    return f"match returned {result.returncode}"


def match_failure_category(reason: str) -> str:
    lowered = reason.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Timeout"
    return "Runtime match failure"


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
    prompt_chars: int,
    max_prompt_chars: int,
    failure_category: str | None,
) -> dict[str, float]:
    return build_objectives(
        compile_result=compile_result,
        game_metrics=game_metrics,
        alignment_result=alignment_result,
        prompt_chars=prompt_chars,
        max_prompt_chars=max_prompt_chars,
        failure_category=failure_category,
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
        f"{candidate.id} status={candidate.status} "
        f"prompt_chars={candidate.metadata.get('prompt_chars', 0)} "
        f"prompt_lines={candidate.metadata.get('prompt_lines', 0)} "
        f"objectives={candidate.fitness_objectives}{detail}",
        flush=True,
    )
