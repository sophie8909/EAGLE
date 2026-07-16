"""Candidate evaluation with explicit generation, validation, compilation, and integration boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from pathlib import Path

from evaluation.code_quality import (
    CodeQualityBreakdown,
    StrategyRegionScoreResult,
    analyze_compilation,
    build_code_quality,
)
from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.game_performance import GamePerformanceConfig
from evaluation.microrts_runner import (
    IntegrationResult,
    MatchResult,
    integrate_microrts_agent,
    hash_class_directory,
    hash_file,
    run_microrts_match,
)
from evaluation.nsga2_objectives import build_objectives
from generation.agent_template import JavaTemplatePaths
from generation.backend import GenerationBackend
from generation.java_agent_generator import (
    GeneratedJavaAgent,
    ValidationResult,
    generate_java_agent_result,
)
from .artifacts import append_result, write_candidate_artifacts, write_candidate_inputs
from .candidate import Candidate
from .config import ExperimentConfig


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    result: "CandidateResult"
    agent: GeneratedJavaAgent | None
    compile_result: CompileResult | None
    integration_result: IntegrationResult | None
    match_results: list[MatchResult]
    game_metrics: GameMetrics | None
    strategy_consistency_result: object | None
    code_quality_breakdown: CodeQualityBreakdown
    strategy_region_score_result: StrategyRegionScoreResult | None
    error: str | None = None
    generation_timing: dict[str, object] | None = None


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    parent_ids: tuple[str, ...]
    raw_llm_output: str = ""
    extracted_code: str = ""
    assembled_java: str = ""
    strategy_region: str = ""
    validation_result: ValidationResult | None = None
    strategy_region_validation: dict[str, dict] | None = None
    compile_result: CompileResult | None = None
    strategy_consistency: dict | None = None
    code_quality_breakdown: dict | None = None
    match_result: list[MatchResult] | None = None
    game_metrics: dict[str, object] | None = None
    final_score: dict[str, float] | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    integration_result: IntegrationResult | None = None
    failure_stage: str | None = None


def evaluate_population(
    population: list[Candidate],
    *,
    generation: int,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    candidates_dir: Path,
    results_path: Path,
    mock: bool,
) -> list[Candidate]:
    evaluated = []
    for index, candidate in enumerate(population):
        write_candidate_inputs(candidates_dir, candidate)
        evaluation = evaluate_candidate(
            candidate,
            config=config,
            backend=backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            match_artifacts_dir=candidates_dir / candidate.id / "matches",
            mock=mock,
            ordinal=index,
        )
        write_candidate_artifacts(candidates_dir, evaluation)
        append_result(results_path, evaluation)
        evaluated.append(evaluation.candidate)
        print_progress(generation=generation, index=index, population_size=len(population), evaluation=evaluation)
    return evaluated


def evaluate_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    ordinal: int,
    match_artifacts_dir: Path | None = None,
) -> CandidateEvaluation:
    generation_started_at = _utc_now()
    generation_monotonic_started = time.monotonic()
    generation = generate_java_agent_result(
        candidate,
        backend,
        generated_agents_dir,
        template_paths=JavaTemplatePaths(config.agent_template_path),
    )
    generation_finished_at = _utc_now()
    generation_timing = {
        "started_at": generation_started_at,
        "finished_at": generation_finished_at,
        "duration_seconds": max(0.0, time.monotonic() - generation_monotonic_started),
        "attempts": [{
            "attempt": 1,
            "started_at": generation_started_at,
            "finished_at": generation_finished_at,
            "duration_seconds": max(0.0, time.monotonic() - generation_monotonic_started),
            "status": "success" if generation.raw_llm_output else "error",
            "error": generation.failure_reason,
        }],
    }

    agent = generation.agent
    region_score = generation.strategy_region_score_result
    if region_score is None:
        from evaluation.code_quality import evaluate_agent_strategy_region
        region_score = evaluate_agent_strategy_region(
            "",
            error=generation.failure_reason or "Complete Java validation did not run.",
        )

    compile_result: CompileResult | None = None
    compile_error: str | None = None
    compilation_started_at: str | None = None
    compilation_finished_at: str | None = None
    compilation_duration: float | None = None
    if agent is not None:
        compilation_started_at = _utc_now()
        compilation_started = time.monotonic()
        try:
            compile_result = compile_agent_source(
                agent,
                config=config,
                classes_dir=classes_dir,
                candidate_id=candidate.id,
                mock=mock,
            )
        except (RuntimeError, OSError, ValueError) as exc:
            compile_error = str(exc)
        compilation_finished_at = _utc_now()
        compilation_duration = max(0.0, time.monotonic() - compilation_started)

    compiler = analyze_compilation(compile_result)
    quality = build_code_quality(
        compiler,
        region_score,
        {"agent_strategy_region": generation.strategy_region} if generation.strategy_region else {},
    )

    integration_result: IntegrationResult | None = None
    matches: list[MatchResult] = []
    game_metrics: GameMetrics | None = None
    match_error: str | None = None
    if compiler.compile_success and agent is not None:
        integration_dir = None if match_artifacts_dir is None else match_artifacts_dir.parent / "integration"
        integration_result = integrate_microrts_agent(
            microrts_dir=config.microrts_dir,
            classes_dir=classes_dir / candidate.id,
            agent_class=agent.qualified_class_name,
            integration_artifacts_dir=integration_dir,
            mock=mock,
        )
        if integration_result.ok:
            matches, match_error = evaluate_matches(
                candidate=candidate,
                agent=agent,
                config=config,
                classes_dir=classes_dir,
                match_artifacts_dir=match_artifacts_dir,
                mock=mock,
                ordinal=ordinal,
            )
            if not match_error:
                game_metrics = compute_game_metrics(matches)
        else:
            match_error = integration_result.failure_reason or "MicroRTS integration failed."

    game_failure = not compiler.compile_success or integration_result is not None and not integration_result.ok or match_error is not None
    if game_failure:
        game_metrics = compute_game_metrics(matches)

    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    if generation.failure_category and agent is None:
        failure_category = generation.failure_category
        failure_reason = generation.failure_reason
        failure_stage = generation.failure_stage or ("validation" if generation.validation_result.failed_checks else "generation")
    elif not compiler.compile_success:
        failure_category = "Java compile failure"
        failure_reason = (compile_error or compile_error_message(compile_result)) if compile_result else (compile_error or "Compilation was not run.")
        failure_stage = "compilation"
    elif integration_result is not None and not integration_result.ok:
        failure_category = "MicroRTS integration failure"
        failure_reason = integration_result.failure_reason
        failure_stage = "integration"
    elif match_error:
        failed_match = next((result for result in matches if not result.ok), None)
        failure_category = (
            failed_match.failure_category
            if failed_match is not None and failed_match.failure_category
            else "partial_evaluation"
        )
        failure_reason = match_error
        failure_stage = "runtime"

    objectives = build_objectives(game_metrics=game_metrics, code_quality=quality, game_failure=game_failure)
    quality_payload = {
        "code_quality": quality.code_quality,
        "code_quality_breakdown": quality.to_json_dict(),
        "strategy_consistency": None,
        "strategy_region_validation": region_score.to_json_dict(),
    }
    timing = {
        **candidate.timing,
        "generation_llm": generation_timing,
        "validation_duration_seconds": generation.validation_timing.get("duration_seconds") or 0.0,
        "compilation_duration_seconds": compilation_duration or 0.0,
        "integration_duration_seconds": 0.0 if integration_result is None else integration_result.duration_seconds,
        "validation": generation.validation_timing,
        "compilation": {
            "started_at": compilation_started_at,
            "finished_at": compilation_finished_at,
            "duration_seconds": compilation_duration,
            "status": "success" if compile_result is not None and compile_result.ok else ("failed" if compile_result is not None else "blocked"),
            "error": compile_error or (failure_reason if compile_result is None else None),
        },
        "integration": {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "status": "blocked",
            "error": failure_reason or "Integration was not run because an earlier stage failed.",
        } if integration_result is None else {
            "started_at": integration_result.started_at,
            "finished_at": integration_result.finished_at,
            "duration_seconds": integration_result.duration_seconds,
            "status": integration_result.status,
            "error": integration_result.failure_reason,
        },
    }
    evaluated_candidate = Candidate(
        id=candidate.id,
        generation=candidate.generation,
        parent_ids=candidate.parent_ids,
        strategy_prompt=candidate.strategy_prompt,
        previous_code=candidate.previous_code,
        generation_prompt=candidate.generation_prompt,
        generated_java=generation.assembled_java,
        generated_java_path=str(agent.source_path) if agent else None,
        operator=candidate.operator,
        mutation_type=candidate.mutation_type,
        strategy_parent_id=candidate.strategy_parent_id,
        previous_code_parent_id=candidate.previous_code_parent_id,
        generation_prompt_parent_id=candidate.generation_prompt_parent_id,
        source_candidate_ids=candidate.source_candidate_ids,
        compile_status=compile_result.status if compile_result else "not_run",
        game_eval_result=game_metrics.to_json_dict() if game_metrics else {},
        code_quality_result=quality_payload,
        fitness_objectives=objectives,
        status="failed" if failure_category else "evaluated",
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        artifacts=candidate.artifacts,
        timing=timing,
        metadata={
            **candidate.metadata,
            "failure_category": failure_category,
            "failure_reason": failure_reason,
        },
    )
    result = CandidateResult(
        candidate_id=candidate.id,
        parent_ids=candidate.parent_ids,
        raw_llm_output=generation.raw_llm_output,
        extracted_code=generation.extracted_code,
        assembled_java=generation.assembled_java,
        strategy_region=generation.strategy_region,
        validation_result=generation.validation_result,
        strategy_region_validation={k: v.to_json_dict() for k, v in region_score.strategy_region_validation.items()},
        compile_result=compile_result,
        code_quality_breakdown=quality.to_json_dict(),
        match_result=matches,
        game_metrics=game_metrics.to_json_dict() if game_metrics else None,
        final_score=objectives,
        failure_category=failure_category,
        failure_reason=failure_reason,
        integration_result=integration_result,
        failure_stage=failure_stage,
    )
    return CandidateEvaluation(
        candidate=evaluated_candidate,
        result=result,
        agent=agent,
        compile_result=compile_result,
        integration_result=integration_result,
        match_results=matches,
        game_metrics=game_metrics,
        strategy_consistency_result=None,
        code_quality_breakdown=quality,
        strategy_region_score_result=region_score,
        error=failure_reason,
        generation_timing=generation_timing,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compile_agent_source(agent: GeneratedJavaAgent, *, config: ExperimentConfig, classes_dir: Path, candidate_id: str, mock: bool) -> CompileResult:
    return compile_generated_agent(
        agent.source_paths,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir / candidate_id,
        mock=mock,
    )


def evaluate_matches(*, candidate: Candidate, agent: GeneratedJavaAgent, config: ExperimentConfig, classes_dir: Path, match_artifacts_dir: Path | None, mock: bool, ordinal: int) -> tuple[list[MatchResult], str | None]:
    match_results: list[MatchResult] = []
    source_hash = hash_file(agent.source_path)
    candidate_classes_dir = classes_dir / candidate.id
    class_hash = hash_class_directory(candidate_classes_dir)
    seeds = config.resolved_match_seeds
    try:
        for match_index in range(10):
            result = run_microrts_match(
                microrts_dir=config.microrts_dir,
                classes_dir=candidate_classes_dir,
                agent_class=agent.qualified_class_name,
                opponent=config.opponent,
                tick_limit=config.tick_limit,
                match_index=match_index,
                match_artifacts_dir=match_artifacts_dir,
                scoring_config=scoring_config_from_experiment(config),
                mock=mock,
                mock_score=config.mock_score_base + config.mock_score_step * (ordinal + match_index),
                seed=seeds[match_index],
                timeout_seconds=config.match_timeout_seconds,
                map_path=config.map_path,
                candidate_id=candidate.id,
                source_hash=source_hash,
                class_hash=class_hash,
            )
            match_results.append(result)
            if not result.ok:
                return match_results, match_error_message(result)
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)

    if len(match_results) != 10:
        return match_results, f"partial evaluation: completed {len(match_results)} of 10 matches"
    return match_results, None


def scoring_config_from_experiment(config: ExperimentConfig) -> GamePerformanceConfig:
    return GamePerformanceConfig(
        result_win_score=config.result_win_score,
        result_draw_score=config.result_draw_score,
        result_loss_score=config.result_loss_score,
        material_scale=config.material_scale,
        resource_scale=config.resource_scale,
        unit_values=dict(config.unit_material_values),
    )


def compile_error_message(result: CompileResult) -> str:
    diagnostics = result.errors if result is not None else ()
    if diagnostics:
        return diagnostics[0].message
    stderr = (result.stderr or "").strip() if result is not None else ""
    if stderr:
        return stderr.splitlines()[0]
    return f"javac returned {result.returncode}" if result is not None else "Compilation was not run."


def match_error_message(result: MatchResult) -> str:
    stderr = (result.stderr or "").strip()
    if result.failure_reason:
        return result.failure_reason
    if stderr:
        return stderr.splitlines()[0]
    return f"match returned {result.returncode}"


def match_failure_category(reason: str) -> str:
    lowered = reason.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Timeout"
    return "Runtime match failure"


def print_progress(*, generation: int, index: int, population_size: int, evaluation: CandidateEvaluation) -> None:
    candidate = evaluation.candidate
    quality = evaluation.code_quality_breakdown
    detail = ""
    if evaluation.error:
        detail = f" error={evaluation.error}"
    elif evaluation.compile_result is not None and not evaluation.compile_result.ok:
        diagnostics = evaluation.compile_result.errors
        detail = f" compile_error={(diagnostics[0].message if diagnostics else evaluation.compile_result.returncode)}"
    print(
        f"[gen {generation} cand {index + 1}/{population_size}] "
        f"{candidate.id} status={candidate.status} "
        f"objectives={candidate.fitness_objectives} "
        f"code_quality_total={quality.code_quality} "
        f"code_quality_components=("
        f"successful_base={quality.successful_base} + "
        f"compilation={quality.compilation_score} + "
        f"function={quality.function_score} + "
        f"strategy_alignment={quality.strategy_alignment_score} = "
        f"{quality.code_quality}){detail}",
        flush=True,
    )
