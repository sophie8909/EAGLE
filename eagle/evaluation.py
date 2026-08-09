"""Shared child pipeline for generated-agent evaluation.

This module owns validation, compilation, MicroRTS evaluation, objective construction,
and candidate artifact persistence. Search owns operator selection and population
updates; this module does not choose parents or survivors.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from evaluation.code_quality import (
    CodeQualityBreakdown,
    StrategyRegionScoreResult,
    analyze_compilation,
    build_failure_code_quality,
    build_successful_code_quality,
)
from evaluation.compiler import CompileResult, compile_generated_agent
from evaluation.game_metrics import GameMetrics, compute_game_metrics
from evaluation.game_performance import GamePerformanceConfig
from evaluation.function_capability import FunctionCapabilityResult, evaluate_function_capability
from evaluation.microrts_runner import (
    IntegrationResult,
    MatchResult,
    integrate_microrts_agent,
    hash_class_directory,
    hash_file,
    run_microrts_match,
)
from evaluation.nsga2_objectives import build_objectives
from evaluation.strategy_alignment import (
    StrategyAlignmentResult,
    build_strategy_alignment_backend,
    evaluate_strategy_alignment,
)
from generation.agent_template import JavaTemplatePaths
from generation.backend import GenerationBackend
from generation.java_agent_generator import (
    GeneratedJavaAgent,
    ValidationResult,
    generate_java_agent_result,
)
from .artifacts import write_candidate_artifacts, write_candidate_inputs
from .candidate import Candidate, compact_candidate_metadata
from .config import ExperimentConfig
from .commentary_aggregation import aggregate_commentaries
from .match_commentator import CommentaryConfig, CommentaryResult, commentate_match
from .mutation import build_reflection_backend
from .final_test.opponents import OpponentSetupError
from .opponents import EVALUATION_ROSTER, OpponentSpec, SEARCH_OPPONENT_REGISTRY, rooted_jar_path
from evaluation.opponent_schedule import EAGLE_OPPONENT_ID
from evaluation.match_matrix import MatrixOpponent, build_match_matrix, canonical_evaluation_maps


WORKER_RUSH_ADAPTER_SOURCE = """package ai.abstraction;

import ai.abstraction.pathfinding.PathFinding;
import rts.units.UnitTypeTable;

/** Compatibility identity for the canonical EAGLE workerrush roster entry. */
public final class WorkerRush extends LightRush {
    public WorkerRush(UnitTypeTable utt) {
        super(utt);
    }

    public WorkerRush(UnitTypeTable utt, PathFinding pathFinding) {
        super(utt, pathFinding);
    }
}
"""


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
    function_capability_result: FunctionCapabilityResult | None = None
    strategy_alignment_result: StrategyAlignmentResult | None = None
    generation_timing: dict[str, object] | None = None


@dataclass(frozen=True)
class EvaluationOpponent:
    opponent_id: str
    class_name: str
    classpath_entries: tuple[Path, ...] = ()
    weight: float = 1.0
    source_generation: int | None = None
    source_candidate_id: str | None = None
    source_game_performance: float | None = None
    source_classes_dir: Path | None = None


def prepare_eagle_opponent(
    champion: Candidate,
    *,
    generation: int,
    config: ExperimentConfig,
    classes_dir: Path,
    mock: bool,
) -> EvaluationOpponent:
    """Create a loadable alias for the frozen prior champion's compiled phenotype.

    Both the candidate and champion implement ``ai.generated.CandidateAgent``. A
    JVM cannot load two definitions with that name, so the persisted champion
    source is compiled once under an adapter identity; no LLM generation occurs.
    """

    source = champion.generated_java
    if not source and champion.generated_java_path:
        source_path = Path(champion.generated_java_path)
        if source_path.is_file():
            source = source_path.read_text(encoding="utf-8")
    if mock and (not source or not re.search(r"\bCandidateAgent\b", source)):
        return EvaluationOpponent(
            EAGLE_OPPONENT_ID,
            "ai.generated.EaglePreviousBest",
            classpath_entries=(),
            weight=0.0,
            source_generation=generation - 1,
            source_candidate_id=champion.id,
            source_game_performance=float(champion.fitness_objectives.get("game_performance", -1000.0)),
        )
    if not source or not re.search(r"\bCandidateAgent\b", source):
        raise OpponentSetupError(
            f"Previous-generation champion {champion.id} has no persisted generated Java source."
        )
    alias = "EaglePreviousBest"
    opponent_root = classes_dir.parent / "eagle_opponents" / f"generation_{generation:04d}_{champion.id}"
    alias_source = opponent_root / f"{alias}.java"
    alias_classes = opponent_root / "classes"
    alias_source.parent.mkdir(parents=True, exist_ok=True)
    alias_source.write_text(re.sub(r"\bCandidateAgent\b", alias, source), encoding="utf-8")
    if not mock:
        alias_classes.mkdir(parents=True, exist_ok=True)
        microrts_dir = config.microrts_dir.resolve()
        classpath = os.pathsep.join([
            str(microrts_dir / "bin"),
            str(microrts_dir / "lib" / "*"),
        ])
        completed = subprocess.run(
            ["javac", "-cp", classpath, "-d", str(alias_classes), str(alias_source)],
            cwd=microrts_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise OpponentSetupError(
                f"Previous-generation champion {champion.id} could not be compiled as {alias}: "
                f"{(completed.stderr or completed.stdout).strip()}"
            )
        (opponent_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "eagle-dynamic-opponent-v1",
                    "opponent_id": EAGLE_OPPONENT_ID,
                    "source_generation": generation - 1,
                    "source_candidate_id": champion.id,
                    "source_game_performance": champion.fitness_objectives.get("game_performance"),
                    "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    "alias_class": f"ai.generated.{alias}",
                    "source_path": str(alias_source),
                    "classes_dir": str(alias_classes),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return EvaluationOpponent(
        EAGLE_OPPONENT_ID,
        f"ai.generated.{alias}",
        classpath_entries=(alias_classes,),
        weight=0.0,
        source_generation=generation - 1,
        source_candidate_id=champion.id,
        source_game_performance=float(champion.fitness_objectives.get("game_performance", -1000.0)),
        source_classes_dir=alias_classes,
    )


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
    function_capability: dict | None = None
    strategy_alignment: dict | None = None
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
    mock: bool,
    alignment_profile: object | None = None,
    eagle_opponent: EvaluationOpponent | None = None,
) -> list[Candidate]:
    evaluated = []
    for index, candidate in enumerate(population):
        print(
            f"[gen {generation} cand {index + 1}/{len(population)}] "
            f"{candidate.id} stage=generation status=started",
            flush=True,
        )
        write_candidate_inputs(candidates_dir, candidate)
        evaluation = evaluate_candidate(
            candidate,
            config=config,
            backend=backend,
            generated_agents_dir=generated_agents_dir,
            classes_dir=classes_dir,
            match_artifacts_dir=candidates_dir / candidate.id / "matches",
            mock=mock,
            alignment_profile=alignment_profile,
            ordinal=index,
            eagle_opponent=eagle_opponent,
        )
        write_candidate_artifacts(candidates_dir, evaluation)
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
    alignment_profile: object | None = None,
    ordinal: int,
    match_artifacts_dir: Path | None = None,
    eagle_opponent: EvaluationOpponent | None = None,
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
        "stage": "generation",
        "llm_profile": getattr(backend, "llm_profile", None),
        "model": getattr(backend, "model", None),
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
    integration_result: IntegrationResult | None = None
    matches: list[MatchResult] = []
    match_error: str | None = None
    evaluation_started_at: str | None = None
    evaluation_finished_at: str | None = None
    evaluation_started: float | None = None

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
            evaluation_started_at = _utc_now()
            evaluation_started = time.monotonic()
            matches, match_error = evaluate_matches(
                candidate=candidate,
                agent=agent,
                config=config,
                classes_dir=classes_dir,
                match_artifacts_dir=match_artifacts_dir,
                mock=mock,
                ordinal=ordinal,
                eagle_opponent=eagle_opponent,
            )
        else:
            match_error = integration_result.failure_reason or "MicroRTS integration failed."

    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    completed_matches = sum(result.ok for result in matches)
    expected_match_count = config.expected_match_count + (
        config.fixed_matches_per_opponent if eagle_opponent is not None else 0
    )
    if agent is None:
        validation_failed = bool(generation.validation_result.failed_checks)
        failure_stage = generation.failure_stage or ("validation" if validation_failed else "generation")
        failure_category = generation.failure_category or f"{failure_stage}_failure"
        failure_reason = generation.failure_reason or "Java generation did not produce a valid agent."
    elif not compiler.compile_success:
        failure_category = "Java compile failure"
        failure_reason = (
            compile_error or compile_error_message(compile_result)
            if compile_result
            else compile_error or "Compilation was not run."
        )
        failure_stage = "compilation"
    elif integration_result is not None and not integration_result.ok:
        failure_category = "MicroRTS integration failure"
        failure_reason = integration_result.failure_reason
        failure_stage = "integration"
    elif match_error or completed_matches != expected_match_count:
        failed_match = next((result for result in matches if not result.ok), None)
        failure_category = (
            failed_match.failure_category
            if failed_match is not None and failed_match.failure_category
            else "partial_evaluation"
        )
        failure_reason = match_error or f"partial evaluation: completed {completed_matches} of {expected_match_count} matches"
        failure_stage = "runtime"

    objective_started_at = _utc_now()
    objective_started = time.monotonic()
    game_metrics = compute_game_metrics(
        matches,
        fixed_opponent_weights=dict(config.evaluation_opponents),
        eagle_weight=0.0 if eagle_opponent is None else eagle_opponent.weight,
        expected_match_count=config.expected_match_count + (
            config.fixed_matches_per_opponent if eagle_opponent is not None else 0
        ),
        expected_matches_per_opponent=config.fixed_matches_per_opponent,
        evaluation_maps=config.evaluation_maps,
        eagle_reference=None if eagle_opponent is None else {
            "generation": eagle_opponent.source_generation,
            "candidate_id": eagle_opponent.source_candidate_id,
            "game_performance": eagle_opponent.source_game_performance,
        },
    )
    capability_result: FunctionCapabilityResult | None = None
    alignment_result: StrategyAlignmentResult | None = None
    if failure_stage is None:
        capability_result = evaluate_function_capability(generation.assembled_java, matches)
        alignment_backend = build_strategy_alignment_backend(
            "mock" if mock else config.alignment_backend,
            base_url=getattr(alignment_profile, "base_url", config.llm_base_url),
            model=getattr(alignment_profile, "model", config.llm_model),
            timeout_seconds=getattr(alignment_profile, "timeout_seconds", 120.0),
            temperature=getattr(alignment_profile, "temperature", 0.0),
            max_output_tokens=getattr(alignment_profile, "max_output_tokens", None),
        )
        alignment_dir = None if match_artifacts_dir is None else match_artifacts_dir.parent / "strategy_alignment"
        alignment_result = evaluate_strategy_alignment(
            strategy_prompt=candidate.strategy_prompt,
            generated_java=generation.assembled_java,
            behavior_summary=game_metrics.behavior_summary,
            backend=alignment_backend,
            artifact_dir=alignment_dir,
        )
        quality = build_successful_code_quality(
            compiler,
            capability_result,
            alignment_result,
            strategy_regions={"candidate_generated_methods": generation.strategy_region},
            strategy_region=region_score,
        )
    else:
        quality = build_failure_code_quality(
            failure_stage,
            compiler=compiler,
            integration_pass_ratio=(
                0.0 if integration_result is None else integration_result.integration_pass_ratio
            ),
            completed_matches=completed_matches,
            strategy_regions={"candidate_generated_methods": generation.strategy_region},
            strategy_region=region_score,
        )
    objectives = build_objectives(
        game_metrics=game_metrics,
        code_quality=quality,
        game_failure=failure_stage is not None,
    )
    objective_finished_at = _utc_now()
    objective_duration = max(0.0, time.monotonic() - objective_started)

    evaluation_duration: float | None = None
    if evaluation_started is not None:
        evaluation_finished_at = _utc_now()
        evaluation_duration = max(0.0, time.monotonic() - evaluation_started)
    match_durations = [max(0.0, result.duration_seconds) for result in matches]
    alignment_timing = {
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "attempts": [],
    } if alignment_result is None else {
        "started_at": alignment_result.started_at,
        "finished_at": alignment_result.finished_at,
        "duration_seconds": alignment_result.duration_seconds,
        "attempts": [dict(item) for item in alignment_result.attempts],
    }
    quality_payload = {
        "code_quality": quality.code_quality,
        "code_quality_breakdown": quality.to_json_dict(),
        "function_capability": None if capability_result is None else capability_result.to_json_dict(),
        "strategy_alignment": None if alignment_result is None else alignment_result.to_json_dict(),
        "strategy_region_validation": region_score.to_json_dict(),
    }
    game_payload = game_metrics.to_json_dict()
    game_payload["evaluation_configuration"] = {
        "maps": list(config.evaluation_maps),
        "rounds_per_map": config.rounds_per_map,
        "swap_player_sides": config.swap_player_sides,
        "expected_match_count": config.expected_match_count,
    }
    commentary_results: list[CommentaryResult] = []
    commentator_backend = None
    if config.match_commentator_enabled:
        commentator_backend = build_reflection_backend(
            "mock" if mock else config.generation_backend,
            base_url=config.llm_base_url,
            model=config.llm_model,
            llm_profile="match_commentator",
            temperature=config.match_commentator_temperature,
            max_output_tokens=config.llm_max_tokens,
        )
    commentator_config = CommentaryConfig(
        enabled=config.match_commentator_enabled,
        temperature=config.match_commentator_temperature,
        chunk_ticks=config.match_commentator_chunk_ticks,
        max_attempts=config.mutation_max_attempts,
    )
    for match in matches:
        if match.match_dir:
            commentary_results.append(
                commentate_match(match, backend=commentator_backend, config=commentator_config)
            )
    commentary_aggregation = aggregate_commentaries(
        matches,
        commentary_results,
        candidate_id=candidate.id,
    )
    game_payload["commentary_aggregation"] = commentary_aggregation
    compact_matches = [_compact_match_result(result) for result in matches]
    # This is the hand-off consumed by the next generation's Reflection stage.
    # Keep the exact evaluated values together so mutation never reconstructs
    # evidence from legacy metadata keys or recalculates an objective.
    reflection_evidence = {
        "schema_version": "phase4-reflection-context-v1",
        "candidate_id": candidate.id,
        "objectives": dict(objectives),
        "evaluation_status": "failed" if failure_category else "evaluated",
        "failure_stage": failure_stage,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "eagle_reference": None if eagle_opponent is None else {
            "generation": eagle_opponent.source_generation,
            "candidate_id": eagle_opponent.source_candidate_id,
            "game_performance": eagle_opponent.source_game_performance,
            "weight": eagle_opponent.weight,
        },
        "generation": {
            "raw_response": generation.raw_llm_output,
            "extracted_code": generation.extracted_code,
            "assembled_java": generation.assembled_java,
            "validation": generation.validation_result.to_json_dict(),
            "strategy_region_validation": {
                key: value.to_json_dict()
                for key, value in region_score.strategy_region_validation.items()
            },
        },
        "compilation": _compact_compilation_evidence(compile_result),
        "integration": _compact_integration_evidence(integration_result),
        "commentary_aggregation": commentary_aggregation,
    }
    timing = {
        **candidate.timing,
        "generation_llm": generation_timing,
        "validation_duration_seconds": generation.validation_timing.get("duration_seconds") or 0.0,
        "compilation_duration_seconds": compilation_duration or 0.0,
        "integration_duration_seconds": 0.0 if integration_result is None else integration_result.duration_seconds,
        "evaluation_duration_seconds": evaluation_duration,
        "matches_total_duration_seconds": round(sum(match_durations), 9),
        "match_durations_seconds": match_durations,
        "strategy_alignment_llm": alignment_timing,
        "objective_calculation_duration_seconds": objective_duration,
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
        "evaluation": {
            "started_at": evaluation_started_at,
            "finished_at": evaluation_finished_at,
            "duration_seconds": evaluation_duration,
            "status": (
                "blocked" if evaluation_started_at is None else "success" if failure_stage is None else "failed"
            ),
            "error": failure_reason,
        },
        "objective_calculation": {
            "started_at": objective_started_at,
            "finished_at": objective_finished_at,
            "duration_seconds": objective_duration,
            "status": "success",
            "error": None,
        },
    }
    mutation_generation = timing.get("mutation", {}).get("generation_only_duration_seconds", 0.0)
    crossover_generation = timing.get("crossover", {}).get("generation_only_duration_seconds", 0.0)
    validation_duration = timing["validation"].get("duration_seconds") or 0.0
    compilation_duration_value = timing["compilation"].get("duration_seconds") or 0.0
    evaluation_duration_value = timing["evaluation"].get("duration_seconds") or 0.0
    operation_generation = float(mutation_generation or 0.0) + float(crossover_generation or 0.0)
    timing["mutation_generation"] = timing.get("mutation") if timing.get("mutation") else None
    timing["crossover_generation"] = timing.get("crossover") if timing.get("crossover") else None
    timing["child_generation"] = {
        "operation_type": candidate.operator,
        "started_at": (timing.get("mutation") or timing.get("crossover") or {}).get("started_at"),
        "finished_at": (timing.get("mutation") or timing.get("crossover") or {}).get("finished_at"),
        "duration_seconds": operation_generation,
    }
    timing["child_total"] = {
        "duration_seconds": operation_generation + validation_duration + compilation_duration_value + float(timing["integration"].get("duration_seconds") or 0.0) + evaluation_duration_value,
        "includes": ["mutation_generation", "crossover_generation", "validation", "compilation", "integration", "evaluation"],
        "status": "failed" if failure_stage else "success",
        "failure_stage": failure_stage,
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
        game_eval_result=game_payload,
        code_quality_result=quality_payload,
        fitness_objectives=objectives,
        status="failed" if failure_category else "evaluated",
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        artifacts=candidate.artifacts,
        timing=timing,
        metadata=compact_candidate_metadata(
            {
                **candidate.metadata,
                "failure_category": failure_category,
                "failure_reason": failure_reason,
                "reflection_evidence": reflection_evidence,
            },
            preserve_unpersisted_mutation=True,
        ),
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
        function_capability=None if capability_result is None else capability_result.to_json_dict(),
        strategy_alignment=None if alignment_result is None else alignment_result.to_json_dict(),
        match_result=compact_matches,
        game_metrics=game_payload,
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
        match_results=compact_matches,
        game_metrics=game_metrics,
        strategy_consistency_result=None,
        code_quality_breakdown=quality,
        strategy_region_score_result=region_score,
        function_capability_result=capability_result,
        strategy_alignment_result=alignment_result,
        error=failure_reason,
        generation_timing=generation_timing,
    )


def _compact_match_result(result: MatchResult) -> MatchResult:
    """Release large process/telemetry payloads after canonical persistence."""

    return replace(
        result,
        command=[],
        stdout="",
        stderr="",
        raw_result={},
        telemetry=None,
    )


def _compact_compilation_evidence(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    payload = result.to_json_dict()
    payload.pop("command", None)
    payload.pop("stdout", None)
    payload.pop("stderr", None)
    return payload


def _compact_integration_evidence(result: IntegrationResult | None) -> dict | None:
    if result is None:
        return None
    payload = result.to_json_dict()
    payload.pop("commands", None)
    payload.pop("stdout", None)
    payload.pop("stderr", None)
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compile_agent_source(agent: GeneratedJavaAgent, *, config: ExperimentConfig, classes_dir: Path, candidate_id: str, mock: bool) -> CompileResult:
    return compile_generated_agent(
        agent.source_paths,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir / candidate_id,
        mock=mock,
    )


def preflight_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    repository_root: Path | None = None,
) -> None:
    """Fail early when real evolution needs unavailable bundled opponents."""

    if mock:
        return
    repository_root = (repository_root or _repository_root()).resolve()
    for item in SEARCH_OPPONENT_REGISTRY:
        if not item.enabled or not item.jar_path:
            continue
        jar_path = rooted_jar_path(repository_root, item)
        if jar_path is not None and not jar_path.is_file():
            raise OpponentSetupError(f"Bundled evolution opponent JAR is missing: {jar_path}")
        if item.opponent_id == "allibot":
            manifest_path = repository_root / "third_party" / "gui_opponents" / "resolved_allibot.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OpponentSetupError(f"AlliBot resolution manifest is missing or invalid: {manifest_path}") from exc
            if manifest.get("schema_version") != "eagle-allibot-v2" or manifest.get("class_name") != item.class_name:
                raise OpponentSetupError(f"AlliBot resolution manifest does not match {item.class_name}: {manifest_path}")
            digest = hashlib.sha256(jar_path.read_bytes()).hexdigest() if jar_path is not None else ""
            if digest != manifest.get("jar_sha256"):
                raise OpponentSetupError(f"AlliBot JAR hash does not match its resolution manifest: {jar_path}")
            source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
            if not any(path.is_file() and path.suffix == ".jar" for path in source_lib.glob("*.jar")):
                raise OpponentSetupError(f"AlliBot upstream libraries are missing: {source_lib}")


def evaluate_matches(*, candidate: Candidate, agent: GeneratedJavaAgent, config: ExperimentConfig, classes_dir: Path, match_artifacts_dir: Path | None, mock: bool, ordinal: int, eagle_opponent: EvaluationOpponent | None = None, historical_opponents: tuple[EvaluationOpponent, ...] = ()) -> tuple[list[MatchResult], str | None]:
    """Run fixed opponents plus one frozen previous-generation champion when available."""
    match_results: list[MatchResult] = []
    source_hash = hash_file(agent.source_path)
    candidate_classes_dir = classes_dir / candidate.id
    class_hash = hash_class_directory(candidate_classes_dir)
    first_error: str | None = None
    try:
        opponents = list(
            _resolved_static_evaluation_opponents(
                config,
                mock=mock,
                classes_dir=classes_dir,
            )
        )
        if eagle_opponent is not None:
            opponents.append(eagle_opponent)
        opponents.extend(historical_opponents)
        matrix_opponents = tuple(
            MatrixOpponent(
                item.opponent_id,
                item.weight,
                item.source_generation,
                item.source_candidate_id,
                item.source_game_performance,
            )
            for item in opponents
        )
        specifications = build_match_matrix(
            matrix_opponents,
            canonical_evaluation_maps(config.evaluation_maps),
            rounds_per_map=config.rounds_per_map,
            swap_player_sides=config.swap_player_sides,
            round_seeds=config.resolved_match_seeds,
        )
        expected_matches = len(specifications)
        if len(opponents) != len(config.evaluation_opponents) + (1 if eagle_opponent is not None else 0) + len(historical_opponents):
            return match_results, (
                f"evaluation roster has {len(opponents)} opponents; "
                f"expected {len(config.evaluation_opponents) + (1 if eagle_opponent is not None else 0) + len(historical_opponents)}"
            )
        opponent_by_id = {item.opponent_id: item for item in opponents}
        for specification in specifications:
            opponent = opponent_by_id[specification.opponent_id]
            try:
                result = run_microrts_match(
                    microrts_dir=config.microrts_dir, classes_dir=candidate_classes_dir,
                    agent_class=agent.qualified_class_name, opponent=opponent.class_name,
                    tick_limit=config.tick_limit, match_index=specification.match_index,
                    match_artifacts_dir=match_artifacts_dir,
                    scoring_config=scoring_config_from_experiment(config), mock=mock,
                    mock_score=config.mock_score_base + config.mock_score_step * (ordinal + specification.match_index),
                    seed=specification.seed, timeout_seconds=config.match_timeout_seconds,
                    map_path=specification.map_path, candidate_id=candidate.id,
                    generation=candidate.generation,
                    candidate_player=specification.candidate_player,
                    source_hash=source_hash, class_hash=class_hash,
                    extra_classpath_entries=opponent.classpath_entries,
                    artifact_mode=config.match_artifact_mode,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    opponent_source_generation=specification.opponent_source_generation,
                    opponent_source_candidate_id=specification.opponent_source_candidate_id,
                    opponent_weight=specification.opponent_weight,
                )
            except (RuntimeError, OSError) as exc:
                result = MatchResult(
                    ok=False,
                    score=0.0,
                    command=[],
                    match_index=specification.match_index,
                    generation=candidate.generation,
                    seed=specification.seed,
                    opponent=opponent.class_name,
                    candidate_player=specification.candidate_player,
                    map_path=specification.map_path,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    status="failed",
                    failure_category="runtime_match_failure",
                    failure_reason=str(exc),
                )
            result = replace(
                result,
                generation=candidate.generation,
                opponent_id=opponent.opponent_id,
                opponent_name=_opponent_display_name(opponent.opponent_id),
                map_id=specification.map_id,
                round_index=specification.round_index,
                opponent_source_generation=specification.opponent_source_generation,
                opponent_source_candidate_id=specification.opponent_source_candidate_id,
                opponent_weight=specification.opponent_weight,
            )
            match_results.append(result)
            if not result.ok and first_error is None:
                first_error = match_error_message(result)
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)
    expected_matches = config.expected_match_count + (
        config.fixed_matches_per_opponent if eagle_opponent is not None else 0
    ) + config.fixed_matches_per_opponent * len(historical_opponents)
    if len(match_results) != expected_matches:
        return match_results, f"partial evaluation: completed {len(match_results)} of {expected_matches} matches"
    return match_results, first_error


def _resolved_static_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    classes_dir: Path | None = None,
    repository_root: Path | None = None,
) -> tuple[EvaluationOpponent, ...]:
    repository_root = (repository_root or _repository_root()).resolve()
    opponents: list[EvaluationOpponent] = []
    configured_weights = dict(config.evaluation_opponents)
    registry = {item.opponent_id: item for item in SEARCH_OPPONENT_REGISTRY}
    worker_rush_classes = (
        _prepare_worker_rush_adapter(config, classes_dir=classes_dir)
        if not mock and classes_dir is not None
        else None
    )
    for opponent_id in config.evaluation_opponent_ids:
        item = registry.get(opponent_id)
        if item is None:
            raise OpponentSetupError(f"Configured search opponent is unavailable: {opponent_id}")
        if not item.enabled:
            continue
        classpath_entries: tuple[Path, ...] = ()
        if opponent_id == "workerrush" and worker_rush_classes is not None:
            classpath_entries = (worker_rush_classes,)
        jar_path = rooted_jar_path(repository_root, item)
        if jar_path is not None:
            if not mock and not jar_path.is_file():
                raise OpponentSetupError(f"Bundled evolution opponent JAR is missing: {jar_path}")
            if jar_path.is_file() and not mock:
                classpath_entries = (jar_path,)
                if item.opponent_id == "allibot":
                    source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
                    libraries = tuple(sorted(path.resolve() for path in source_lib.glob("*.jar") if path.is_file()))
                    if not mock and not libraries:
                        raise OpponentSetupError(f"AlliBot upstream libraries are missing: {source_lib}")
                    classpath_entries = (jar_path, *libraries)
        opponents.append(EvaluationOpponent(item.opponent_id, item.class_name, classpath_entries, configured_weights[item.opponent_id]))
    return tuple(opponents)


def _prepare_worker_rush_adapter(config: ExperimentConfig, *, classes_dir: Path) -> Path:
    """Compile the missing vendored WorkerRush identity once per run.

    The checked-in MicroRTS runtime provides LightRush and HeavyRush but no
    WorkerRush class. The canonical EAGLE ID is retained by a small Java
    compatibility subclass so the roster remains loadable and deterministic.
    """

    root = classes_dir.resolve().parent / "opponent_adapters" / "worker_rush"
    source = root / "WorkerRush.java"
    output = root / "classes"
    class_file = output / "ai" / "abstraction" / "WorkerRush.class"
    if class_file.is_file():
        return output
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    source.write_text(WORKER_RUSH_ADAPTER_SOURCE, encoding="utf-8")
    microrts_dir = config.microrts_dir.resolve()
    classpath = os.pathsep.join((str(microrts_dir / "bin"), str(microrts_dir / "lib" / "*")))
    completed = subprocess.run(
        ["javac", "-cp", classpath, "-d", str(output), str(source)],
        cwd=microrts_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not class_file.is_file():
        raise OpponentSetupError(
            "Canonical workerrush adapter could not be compiled: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "eagle-search-opponent-adapter-v1",
                "opponent_id": "workerrush",
                "class_name": "ai.abstraction.WorkerRush",
                "implementation": "subclass of vendored ai.abstraction.LightRush",
                "classes_dir": str(output),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def _opponent_display_name(opponent_id: str) -> str:
    for item in SEARCH_OPPONENT_REGISTRY:
        if item.opponent_id == opponent_id:
            return item.display_name
    return opponent_id


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolved_config_path(repository_root: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repository_root / path).resolve()


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
    game_metrics = evaluation.game_metrics
    match_scores = [] if game_metrics is None else list(
        getattr(game_metrics, "opponent_scores", ())
        or [
            summary.get("performance")
            for summary in getattr(game_metrics, "match_summaries", ())
            if summary.get("performance") is not None
        ]
    )
    game_performance_detail = (
        f" game_performance_matches={match_scores}"
        f" game_performance_fitness={candidate.fitness_objectives.get('game_performance')}"
    )
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
        f"{game_performance_detail} "
        f"code_quality_simplicity={quality.code_quality} "
        f"complexity_penalty={quality.complexity_penalty} "
        f"(cyclomatic={quality.cyclomatic_penalty}, nesting={quality.nesting_penalty}, "
        f"logical_loc={quality.logical_loc_penalty}, longest_function={quality.longest_function_penalty}){detail}",
        flush=True,
    )
