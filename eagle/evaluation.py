"""Candidate evaluation with explicit generation, validation, compilation, and integration boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
import tempfile
import time
from pathlib import Path
from typing import Iterable

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
from .artifacts import append_result, write_candidate_artifacts, write_candidate_inputs
from .candidate import Candidate
from .config import ExperimentConfig
from .final_test.opponents import (
    OpponentSetupError,
    ResolvedOpponent,
    compile_opponent_probe,
    load_resolved_opponents,
    verify_resolved_opponent,
)
from .opponents import EVALUATION_ROSTER, EXTERNAL_OPPONENTS, HISTORICAL_SELF_OPPONENTS, OpponentSpec, rooted_jar_path


RESOLVED_EXTERNAL_OPPONENTS_MANIFEST = Path("third_party/final_test_opponents/resolved_manifest.json")


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
    results_path: Path,
    mock: bool,
    alignment_profile: object | None = None,
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
            alignment_profile=alignment_profile,
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
    alignment_profile: object | None = None,
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
            )
        else:
            match_error = integration_result.failure_reason or "MicroRTS integration failed."

    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    completed_matches = sum(result.ok for result in matches)
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
    elif match_error or completed_matches != 10:
        failed_match = next((result for result in matches if not result.ok), None)
        failure_category = (
            failed_match.failure_category
            if failed_match is not None and failed_match.failure_category
            else "partial_evaluation"
        )
        failure_reason = match_error or f"partial evaluation: completed {completed_matches} of 10 matches"
        failure_stage = "runtime"

    objective_started_at = _utc_now()
    objective_started = time.monotonic()
    game_metrics = compute_game_metrics(matches)
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
        quality = build_successful_code_quality(compiler, capability_result, alignment_result)
    else:
        quality = build_failure_code_quality(
            failure_stage,
            compiler=compiler,
            integration_pass_ratio=(
                0.0 if integration_result is None else integration_result.integration_pass_ratio
            ),
            completed_matches=completed_matches,
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
        function_capability=None if capability_result is None else capability_result.to_json_dict(),
        strategy_alignment=None if alignment_result is None else alignment_result.to_json_dict(),
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
        function_capability_result=capability_result,
        strategy_alignment_result=alignment_result,
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


def preflight_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    repository_root: Path | None = None,
) -> None:
    """Fail early when real evolution needs unavailable external opponents."""

    if mock:
        return
    repository_root = (repository_root or _repository_root()).resolve()
    resolved = _load_resolved_external_opponents(repository_root)
    _verify_external_opponent_classes(resolved.values(), config=config, repository_root=repository_root)


def evaluate_matches(*, candidate: Candidate, agent: GeneratedJavaAgent, config: ExperimentConfig, classes_dir: Path, match_artifacts_dir: Path | None, mock: bool, ordinal: int) -> tuple[list[MatchResult], str | None]:
    """Run the ten-match evolution protocol against the fixed evaluation roster."""
    match_results: list[MatchResult] = []
    source_hash = hash_file(agent.source_path)
    candidate_classes_dir = classes_dir / candidate.id
    class_hash = hash_class_directory(candidate_classes_dir)
    seeds = config.resolved_match_seeds
    try:
        opponents = [
            *_resolved_static_evaluation_opponents(config, mock=mock),
            *_prepare_historical_self_opponents(
                candidate=candidate,
                agent=agent,
                config=config,
                classes_dir=classes_dir,
                match_artifacts_dir=match_artifacts_dir,
                mock=mock,
            ),
        ]
        if len(opponents) != config.matches_per_candidate:
            return match_results, (
                f"evaluation roster has {len(opponents)} opponents; "
                f"expected {config.matches_per_candidate}"
            )
        for match_index, opponent in enumerate(opponents):
            result = run_microrts_match(
                microrts_dir=config.microrts_dir, classes_dir=candidate_classes_dir,
                agent_class=agent.qualified_class_name, opponent=opponent.class_name,
                tick_limit=config.tick_limit, match_index=match_index,
                match_artifacts_dir=match_artifacts_dir,
                scoring_config=scoring_config_from_experiment(config), mock=mock,
                mock_score=config.mock_score_base + config.mock_score_step * (ordinal + match_index),
                seed=seeds[match_index], timeout_seconds=config.match_timeout_seconds,
                map_path=config.map_path, candidate_id=candidate.id,
                source_hash=source_hash, class_hash=class_hash,
                extra_classpath_entries=opponent.classpath_entries,
            )
            result = replace(result, opponent_id=opponent.opponent_id)
            match_results.append(result)
            if not result.ok:
                return match_results, match_error_message(result)
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)
    if len(match_results) != config.matches_per_candidate:
        return match_results, f"partial evaluation: completed {len(match_results)} of {config.matches_per_candidate} matches"
    return match_results, None


def _resolved_static_evaluation_opponents(
    config: ExperimentConfig,
    *,
    mock: bool,
    repository_root: Path | None = None,
) -> tuple[EvaluationOpponent, ...]:
    repository_root = (repository_root or _repository_root()).resolve()
    if mock:
        return tuple(
            EvaluationOpponent(
                item.opponent_id,
                item.class_name,
                () if item.kind != "external" else _mock_external_classpath(repository_root, item),
            )
            for item in EVALUATION_ROSTER
            if item.kind != "historical_self"
        )

    resolved = _load_resolved_external_opponents(repository_root)
    opponents: list[EvaluationOpponent] = []
    for item in EVALUATION_ROSTER:
        if item.kind == "historical_self":
            continue
        if item.kind == "external":
            external = resolved[item.opponent_id]
            jar_path = (repository_root / external.jar_path).resolve()
            if not jar_path.is_file():
                raise OpponentSetupError(
                    f"Opponent JAR is missing for evolution evaluation: {jar_path}. "
                    "Run python3 scripts/setup_final_test_opponents.py first."
                )
            opponents.append(EvaluationOpponent(item.opponent_id, external.class_name, (jar_path,)))
        else:
            opponents.append(EvaluationOpponent(item.opponent_id, item.class_name))
    return tuple(opponents)


def _load_resolved_external_opponents(repository_root: Path) -> dict[str, ResolvedOpponent]:
    return load_resolved_opponents(
        repository_root / RESOLVED_EXTERNAL_OPPONENTS_MANIFEST,
        expected_ids=tuple(item.opponent_id for item in EXTERNAL_OPPONENTS),
    )


def _verify_external_opponent_classes(
    opponents: Iterable[ResolvedOpponent],
    *,
    config: ExperimentConfig,
    repository_root: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix="eagle-opponent-probe-") as probe_dir:
        probe_classes = compile_opponent_probe(
            Path(probe_dir) / "classes",
            _resolved_config_path(repository_root, config.microrts_dir),
        )
        for opponent in opponents:
            verify_resolved_opponent(
                opponent,
                repository_root=repository_root,
                microrts_dir=_resolved_config_path(repository_root, config.microrts_dir),
                probe_classes=probe_classes,
            )


def _mock_external_classpath(repository_root: Path, opponent: OpponentSpec) -> tuple[Path, ...]:
    jar_path = rooted_jar_path(repository_root, opponent)
    return () if jar_path is None else (jar_path,)


def _prepare_historical_self_opponents(
    *,
    candidate: Candidate,
    agent: GeneratedJavaAgent,
    config: ExperimentConfig,
    classes_dir: Path,
    match_artifacts_dir: Path | None,
    mock: bool,
) -> tuple[EvaluationOpponent, ...]:
    source_root = (
        match_artifacts_dir.parent / "historical_self_sources"
        if match_artifacts_dir is not None
        else classes_dir / candidate.id / "historical_self_sources"
    )
    source_root.mkdir(parents=True, exist_ok=True)
    source_candidates = _historical_self_sources(candidate, agent)
    opponents: list[EvaluationOpponent] = []
    for index, spec in enumerate(HISTORICAL_SELF_OPPONENTS):
        class_name = spec.class_name.rsplit(".", 1)[-1]
        source_path = source_root / f"{class_name}.java"
        source_path.write_text(
            _retarget_candidate_source(source_candidates[index], package_name="ai.historical", class_name=class_name),
            encoding="utf-8",
        )
        output_dir = classes_dir / candidate.id / f"{spec.opponent_id}_classes"
        compile_result = compile_generated_agent(
            source_path,
            microrts_dir=config.microrts_dir,
            output_dir=output_dir,
            mock=mock,
        )
        if not compile_result.ok:
            raise RuntimeError(
                f"historical self opponent {spec.opponent_id} compile failed: "
                f"{compile_error_message(compile_result)}"
            )
        opponents.append(EvaluationOpponent(spec.opponent_id, spec.class_name, (output_dir,)))
    return tuple(opponents)


def _historical_self_sources(candidate: Candidate, agent: GeneratedJavaAgent) -> tuple[str, str]:
    parent_source = candidate.previous_code.strip()
    if parent_source:
        return parent_source, agent.source
    return agent.source, agent.source


def _retarget_candidate_source(source: str, *, package_name: str, class_name: str) -> str:
    retargeted = re.sub(r"^\s*package\s+ai\.generated\s*;", f"package {package_name};", source, count=1, flags=re.MULTILINE)
    if retargeted == source:
        retargeted = f"package {package_name};\n" + source
    return re.sub(r"\bCandidateAgent\b", class_name, retargeted)


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
    match_scores = [] if game_metrics is None else [
        summary.get("performance")
        for summary in game_metrics.match_summaries
        if summary.get("performance") is not None
    ]
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
        f"code_quality_total={quality.code_quality} "
        f"code_quality_components=("
        f"successful_base={quality.successful_base} + "
        f"compilation={quality.compilation_score} + "
        f"function={quality.function_score} + "
        f"strategy_alignment={quality.strategy_alignment_score} = "
        f"{quality.code_quality}){detail}",
        flush=True,
    )
