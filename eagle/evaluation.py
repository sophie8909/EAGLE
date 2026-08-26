"""Shared child pipeline for generated-agent evaluation.

This module owns validation, compilation, MicroRTS evaluation, objective construction,
and candidate artifact persistence. Search owns operator selection and population
updates; this module does not choose parents or survivors.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import shutil
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
    integrate_microrts_agent,
)
from evaluation.runtime_evaluation import (
    MatchResult,
    hash_class_directory,
    hash_file,
    run_microrts_match,
)
from evaluation.objectives import build_objectives, reporting_game_performance
from evaluation.strategy_alignment import (
    StrategyAlignmentResult,
    build_strategy_alignment_backend,
    evaluate_strategy_alignment,
)
from generation.agent_template import (
    JavaTemplatePaths,
    extract_strategy_region,
    load_java_template,
)
from generation.backend import GenerationBackend
from generation.java_agent_generator import (
    GeneratedJavaAgent,
    JavaAgentGenerationResult,
    ValidationResult,
    generate_java_agent_result,
)
from .artifacts import (
    write_candidate_artifacts,
    write_candidate_inputs,
    write_generation_attempt_artifacts,
    write_generation_repair_ledger,
)
from .candidate import Candidate, compact_candidate_metadata
from .config import ExperimentConfig
from .prompts import load_prompt, render_prompt
from .opponents import (
    ALLINBOT_UPSTREAM_CLASS_NAME,
    EVALUATION_ROSTER,
    OpponentSetupError,
    OpponentSpec,
    SEARCH_OPPONENT_REGISTRY,
    SAFE_ALLINBOT_CLASS_NAME,
    rooted_jar_path,
)
from evaluation.match_matrix import MatrixOpponent, build_match_matrix, canonical_evaluation_maps


@dataclass(frozen=True)
class CandidateEvaluation:
    """In-memory envelope joining stage results for one evaluated candidate.

    ``candidate`` is the compact state passed back to search. The remaining
    fields are typed evidence needed by artifact writers and progress reports
    before large runtime payloads are compacted.
    """

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
    generation_attempts: tuple["GenerationAttemptResult", ...] = ()


@dataclass(frozen=True)
class GenerationAttemptResult:
    """One decoder-chain step with validation and at-most-once javac."""

    attempt: int
    request: str
    generation: JavaAgentGenerationResult
    compile_result: CompileResult | None
    compile_error: str | None
    generation_timing: dict[str, object]
    compilation_timing: dict[str, object]
    request_kind: str = "initial_decode"
    repair_parent_attempt: int | None = None
    repair_evidence: dict[str, object] | None = None
    selected: bool = False
    final: bool = False


@dataclass(frozen=True)
class BoundedGenerationResult:
    """Production result shared by smoke checks and full evaluation."""

    attempts: tuple[GenerationAttemptResult, ...]
    selected_attempt: int | None
    final_attempt: int
    max_attempts: int
    initial_seed_source: bool

    @property
    def representative_attempt(self) -> GenerationAttemptResult:
        """Return the selected success or, on exhaustion, the final failure."""

        number = self.selected_attempt or self.final_attempt
        return next(item for item in self.attempts if item.attempt == number)

    @property
    def generation(self) -> JavaAgentGenerationResult:
        return self.representative_attempt.generation

    @property
    def compile_result(self) -> CompileResult | None:
        return self.representative_attempt.compile_result

    @property
    def compile_error(self) -> str | None:
        return self.representative_attempt.compile_error


@dataclass(frozen=True)
class EvaluationOpponent:
    opponent_id: str
    class_name: str
    classpath_entries: tuple[Path, ...] = ()
    weight: float = 1.0


@dataclass(frozen=True)
class CandidateResult:
    """Persistable result record produced by the complete child pipeline."""

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
    llm_client: object | None = None,
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
            llm_client=llm_client,
            ordinal=index,
        )
        write_candidate_artifacts(candidates_dir, evaluation)
        evaluated.append(evaluation.candidate)
        print_progress(generation=generation, index=index, population_size=len(population), evaluation=evaluation)
    return evaluated


def decode_validate_compile_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    candidate_artifact_dir: Path | None = None,
) -> BoundedGenerationResult:
    """Run bounded compile-guided decoding and compile valid sources once.

    Attempt one uses the authoritative two-gene generation request. After a
    complete source fails validation or javac, later attempts receive a
    separate compile-repair request containing that phenotype and structured
    failure evidence. Extraction failures have no repairable complete source
    and therefore resample the base request. The first validation+javac success
    is promoted to the sole canonical class directory. This helper deliberately
    stops before Integration and matches so production smoke uses this path.
    """

    _validate_candidate_path_component(candidate.id)
    initial_seed_source = getattr(backend, "operation", None) == "initial_java_seed"
    max_attempts = 1 if initial_seed_source else config.generation_max_attempts
    if max_attempts < 1:
        raise ValueError("generation_max_attempts must be at least 1.")
    base_request = "" if initial_seed_source else (
        backend.authoritative_request(candidate, "CandidateAgent")
        if hasattr(backend, "authoritative_request")
        else candidate.generation_input(class_name="CandidateAgent")
    )
    candidate_source_root = generated_agents_dir / candidate.id / "attempts"
    scratch_root = classes_dir / ".generation_attempts" / candidate.id
    canonical_classes = classes_dir / candidate.id
    if candidate_artifact_dir is not None:
        persisted_attempts = candidate_artifact_dir / "generation" / "attempts"
        if persisted_attempts.is_dir() and any(persisted_attempts.iterdir()):
            raise RuntimeError(
                "Refusing to overwrite persisted decoder attempts; "
                f"partial candidate evidence is audit-only: {persisted_attempts}"
            )
    _safe_remove_candidate_tree(
        candidate_source_root,
        generated_agents_dir / candidate.id,
    )
    _safe_remove_candidate_tree(canonical_classes, classes_dir)
    _safe_remove_candidate_tree(scratch_root, classes_dir / ".generation_attempts")
    attempts: list[GenerationAttemptResult] = []
    selected_attempt: int | None = None
    repair_parent: GenerationAttemptResult | None = None

    try:
        for attempt_number in range(1, max_attempts + 1):
            attempt_name = f"attempt_{attempt_number:03d}"
            request_kind = (
                "compile_repair"
                if not initial_seed_source and repair_parent is not None
                else "initial_decode_retry"
                if not initial_seed_source and attempt_number > 1
                else "initial_decode"
            )
            repair_evidence = (
                _compile_repair_evidence(repair_parent)
                if repair_parent is not None
                else None
            )
            request = (
                _compile_repair_request(
                    candidate,
                    config=config,
                    backend=backend,
                    previous_source=repair_parent.generation.assembled_java,
                    evidence=repair_evidence or {},
                )
                if request_kind == "compile_repair" and repair_parent is not None
                else base_request
            )
            request_sha256 = hashlib.sha256(request.encode("utf-8")).hexdigest()
            attempt_artifact_dir = (
                None
                if candidate_artifact_dir is None
                else candidate_artifact_dir / "generation" / "attempts" / attempt_name
            )
            if attempt_artifact_dir is not None and not initial_seed_source:
                attempt_artifact_dir.mkdir(parents=True, exist_ok=True)
                (attempt_artifact_dir / "request.txt").write_text(request, encoding="utf-8")
                for filename in (
                    "response_raw.txt",
                    "extracted_candidate.java",
                    "normalized_candidate.java",
                ):
                    (attempt_artifact_dir / filename).write_text("", encoding="utf-8")
            if hasattr(backend, "set_generation_attempt_context"):
                backend.set_generation_attempt_context(
                    attempt_number,
                    f"{candidate.id}:generation:{attempt_number:03d}",
                )
            if hasattr(backend, "set_generation_request_kind"):
                backend.set_generation_request_kind(request_kind)
            generation_started_at = _utc_now()
            generation_started = time.monotonic()
            generation = generate_java_agent_result(
                candidate,
                backend,
                generated_agents_dir,
                template_paths=JavaTemplatePaths(
                    config.initial_java_seed_path if initial_seed_source else config.agent_template_path
                ),
                authoritative_request=request,
                output_dir=candidate_source_root / attempt_name,
                attempt_artifact_dir=None if initial_seed_source else attempt_artifact_dir,
            )
            if request_kind == "compile_repair" and repair_parent is not None:
                generation = _enforce_compile_repair_delta(
                    generation,
                    previous_source=repair_parent.generation.assembled_java,
                    parent_validation=repair_parent.generation.validation_result,
                )
            generation_finished_at = _utc_now()
            generation_duration = max(0.0, time.monotonic() - generation_started)
            generation_timing = {
                "attempt": attempt_number,
                "generation_attempt_id": f"{candidate.id}:generation:{attempt_number:03d}",
                "request_sha256": request_sha256,
                "request_kind": request_kind,
                "repair_parent_attempt": (
                    None if repair_parent is None else repair_parent.attempt
                ),
                "repair_of_attempt": (
                    None if repair_parent is None else repair_parent.attempt
                ),
                "previous_source_sha256": (
                    None
                    if repair_parent is None
                    else hashlib.sha256(
                        repair_parent.generation.assembled_java.encode("utf-8")
                    ).hexdigest()
                ),
                "started_at": None if initial_seed_source else generation_started_at,
                "finished_at": None if initial_seed_source else generation_finished_at,
                "duration_seconds": None if initial_seed_source else generation_duration,
                "status": (
                    "source_validated"
                    if generation.agent is not None
                    else "failed"
                ),
                "error": generation.failure_reason,
            }

            compile_result: CompileResult | None = None
            compile_error: str | None = None
            compilation_started_at: str | None = None
            compilation_finished_at: str | None = None
            compilation_duration: float | None = None
            if generation.agent is not None:
                attempt_classes = scratch_root / attempt_name
                compilation_started_at = _utc_now()
                compilation_started = time.monotonic()
                try:
                    compile_result = compile_agent_source(
                        generation.agent,
                        config=config,
                        classes_dir=scratch_root,
                        candidate_id=attempt_name,
                        mock=mock,
                    )
                except (RuntimeError, OSError, ValueError) as exc:
                    compile_error = str(exc)
                compilation_finished_at = _utc_now()
                compilation_duration = max(0.0, time.monotonic() - compilation_started)
                if compile_result is not None and compile_result.ok:
                    attempt_classes.mkdir(parents=True, exist_ok=True)
                    canonical_classes.parent.mkdir(parents=True, exist_ok=True)
                    attempt_classes.replace(canonical_classes)
                    selected_attempt = attempt_number

            compilation_timing = {
                "started_at": compilation_started_at,
                "finished_at": compilation_finished_at,
                "duration_seconds": compilation_duration,
                "status": (
                    "success"
                    if compile_result is not None and compile_result.ok
                    else "failed"
                    if generation.agent is not None
                    else "blocked"
                ),
                "error": compile_error or (
                    compile_error_message(compile_result)
                    if compile_result is not None and not compile_result.ok
                    else generation.failure_reason if generation.agent is None else None
                ),
            }
            attempt = GenerationAttemptResult(
                attempt=attempt_number,
                request=request,
                generation=generation,
                compile_result=compile_result,
                compile_error=compile_error,
                generation_timing=generation_timing,
                compilation_timing=compilation_timing,
                request_kind=request_kind,
                repair_parent_attempt=(
                    None if repair_parent is None else repair_parent.attempt
                ),
                repair_evidence=repair_evidence,
                selected=selected_attempt == attempt_number,
            )
            attempts.append(attempt)
            if candidate_artifact_dir is not None:
                write_generation_attempt_artifacts(
                    candidate_artifact_dir,
                    attempt,
                    initial_seed_source=initial_seed_source,
                )
                write_generation_repair_ledger(
                    candidate_artifact_dir,
                    attempts,
                    initial_seed_source=initial_seed_source,
                )
            if selected_attempt is not None:
                break
            repair_parent = (
                attempt
                if generation.assembled_java
                and (
                    not generation.validation_result.ok
                    or compile_result is not None and not compile_result.ok
                    or compile_error is not None
                )
                else None
            )
    finally:
        _safe_remove_candidate_tree(scratch_root, classes_dir / ".generation_attempts")

    final_attempt = attempts[-1].attempt
    attempts[-1] = replace(attempts[-1], final=True)
    if candidate_artifact_dir is not None:
        write_generation_attempt_artifacts(
            candidate_artifact_dir,
            attempts[-1],
            initial_seed_source=initial_seed_source,
        )
        write_generation_repair_ledger(
            candidate_artifact_dir,
            attempts,
            initial_seed_source=initial_seed_source,
        )
    return BoundedGenerationResult(
        attempts=tuple(attempts),
        selected_attempt=selected_attempt,
        final_attempt=final_attempt,
        max_attempts=max_attempts,
        initial_seed_source=initial_seed_source,
    )


def _compile_repair_request(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    previous_source: str,
    evidence: dict[str, object],
) -> str:
    prompt_id = (
        "java_compile_repair_inherited"
        if candidate.inherited_java
        else "java_compile_repair"
    )
    rendered = render_prompt(
        prompt_id,
        {
            "policy_prompt": candidate.strategy_prompt.strip(),
            "code_generation_prompt": candidate.generation_prompt.strip(),
            "action_api_guide": load_prompt("action_api_guide"),
            "java_scaffold": load_java_template(JavaTemplatePaths(config.agent_template_path)),
            "previous_complete_source": previous_source,
            "compile_evidence": json.dumps(evidence, ensure_ascii=False, indent=2),
            "inherited_java": candidate.inherited_java,
        },
    )
    return (
        backend.prepare_request(rendered)
        if hasattr(backend, "prepare_request")
        else rendered
    )


def _compile_repair_evidence(
    attempt: GenerationAttemptResult,
) -> dict[str, object]:
    compilation = attempt.compile_result
    return {
        "schema_version": "eagle-java-compile-repair-v1",
        "source_attempt": attempt.attempt,
        "failure_stage": (
            "compilation"
            if attempt.generation.agent is not None
            else attempt.generation.failure_stage
        ),
        "validation": attempt.generation.validation_result.to_json_dict(),
        "compilation": (
            {
                "status": "blocked",
                "error": attempt.compile_error or attempt.generation.failure_reason,
            }
            if compilation is None
            else {
                "status": compilation.status,
                "returncode": compilation.returncode,
                "diagnostics": [item.to_json_dict() for item in compilation.diagnostics],
                "stderr": compilation.stderr,
            }
        ),
    }


def _enforce_compile_repair_delta(
    generation: JavaAgentGenerationResult,
    *,
    previous_source: str,
    parent_validation: ValidationResult,
) -> JavaAgentGenerationResult:
    """Reject repair responses that broadly replace unreported strategy code."""

    if not generation.assembled_java:
        return generation
    try:
        previous_region = extract_strategy_region(previous_source)
        repaired_region = extract_strategy_region(generation.assembled_java)
    except ValueError:
        return generation
    previous_tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+|\S", previous_region)
    repaired_tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+|\S", repaired_region)
    failed_check_names = {
        str(item.get("check") or "") for item in parent_validation.failed_checks
    }
    delta_error: str | None = None
    if failed_check_names == {"fixed_scaffold"} and previous_tokens != repaired_tokens:
        delta_error = (
            "compile repair for a fixed_scaffold-only failure must preserve "
            "the strategy region token-for-token"
        )
    elif previous_tokens and repaired_tokens:
        similarity = SequenceMatcher(None, previous_tokens, repaired_tokens).ratio()
        if similarity < 0.45:
            delta_error = (
                "compile repair changed the strategy region too broadly for "
                f"diagnostic-only repair (token similarity {similarity:.3f} < 0.450)"
            )
    if delta_error is None:
        return generation
    validation = generation.validation_result
    failed_checks = (*validation.failed_checks, {
        "check": "compile_repair_delta",
        "reason": delta_error,
    })
    guarded_validation = ValidationResult(
        ok=False,
        error=delta_error,
        passed_checks=tuple(
            name for name in validation.passed_checks if name != "compile_repair_delta"
        ),
        failed_checks=failed_checks,
        blocked_checks=validation.blocked_checks,
        failure_reason=delta_error,
    )
    guarded_timing = {
        **generation.validation_timing,
        "status": "failed",
        "error": delta_error,
    }
    return replace(
        generation,
        validation_result=guarded_validation,
        agent=None,
        failure_category="Java validation failure",
        failure_reason=delta_error,
        failure_stage="validation",
        validation_timing=guarded_timing,
    )


def _validate_candidate_path_component(candidate_id: str) -> None:
    if not candidate_id or candidate_id in {".", ".."} or Path(candidate_id).name != candidate_id:
        raise ValueError(f"Unsafe candidate id for owned artifact paths: {candidate_id!r}")


def _safe_remove_candidate_tree(path: Path, owner: Path) -> None:
    """Remove one exact candidate-owned directory without broad/glob deletion."""

    resolved_path = path.resolve()
    resolved_owner = owner.resolve()
    if resolved_path.parent != resolved_owner:
        raise ValueError(f"Refusing to clean non-candidate directory: {resolved_path}")
    if resolved_path.exists():
        shutil.rmtree(resolved_path)


def evaluate_candidate(
    candidate: Candidate,
    *,
    config: ExperimentConfig,
    backend: GenerationBackend,
    generated_agents_dir: Path,
    classes_dir: Path,
    mock: bool,
    llm_client: object | None = None,
    ordinal: int,
    match_artifacts_dir: Path | None = None,
) -> CandidateEvaluation:
    """Evaluate one candidate through the canonical child pipeline.

    The stages are ordered and failure-aware: generate Java, validate it,
    compile it, integrate it with MicroRTS, run the complete match matrix,
    calculate both objectives, and return one candidate/artifact envelope.
    A failed stage stops only dependent later stages; the candidate still
    receives explicit failure scores and remains available to lexicase.
    """

    genotype_before = (
        candidate.strategy_prompt,
        candidate.generation_prompt,
        candidate.inherited_java,
    )

    # Stages 1-2 use the same bounded decoder helper as production smoke
    # checks. Only its selected (or, when exhausted, final) attempt becomes
    # the canonical phenotype and compilation evidence below.
    bounded_generation = decode_validate_compile_candidate(
        candidate,
        config=config,
        backend=backend,
        generated_agents_dir=generated_agents_dir,
        classes_dir=classes_dir,
        mock=mock,
        candidate_artifact_dir=None if match_artifacts_dir is None else match_artifacts_dir.parent,
    )
    generation = bounded_generation.generation
    initial_seed_source = bounded_generation.initial_seed_source
    generation_attempts = bounded_generation.attempts
    representative_attempt = bounded_generation.representative_attempt
    compile_result = bounded_generation.compile_result
    compile_error = bounded_generation.compile_error
    compilation_started_at = representative_attempt.compilation_timing.get("started_at")
    compilation_finished_at = representative_attempt.compilation_timing.get("finished_at")
    representative_compilation_duration = representative_attempt.compilation_timing.get("duration_seconds")
    compilation_duration = sum(
        float(item.compilation_timing.get("duration_seconds") or 0.0)
        for item in generation_attempts
    )
    source_provenance = None
    if initial_seed_source:
        source_path = getattr(backend, "source_path", None)
        source_provenance = {
            "kind": "checked_in_java_seed",
            "path": None if source_path is None else str(Path(source_path).resolve()),
            "sha256": (
                hashlib.sha256(generation.assembled_java.encode("utf-8")).hexdigest()
                if generation.assembled_java
                else None
            ),
        }
    generation_timing = {
        "stage": "generation",
        "operation": getattr(backend, "operation", None),
        "model": getattr(backend, "model", None),
        "started_at": None if initial_seed_source else generation_attempts[0].generation_timing.get("started_at"),
        "finished_at": None if initial_seed_source else generation_attempts[-1].generation_timing.get("finished_at"),
        "duration_seconds": None if initial_seed_source else sum(
            float(item.generation_timing.get("duration_seconds") or 0.0)
            for item in generation_attempts
        ),
        "attempts": [] if initial_seed_source else [
            {
                **item.generation_timing,
                "status": "success" if item.generation.raw_llm_output else "error",
                "validation_status": item.generation.validation_result.status,
                "compilation_status": item.compilation_timing.get("status"),
                "selected": item.selected,
                "final": item.final,
            }
            for item in generation_attempts
        ],
        "max_attempts": bounded_generation.max_attempts,
        "selected_attempt": None if initial_seed_source else bounded_generation.selected_attempt,
        "final_attempt": None if initial_seed_source else bounded_generation.final_attempt,
        "source": source_provenance,
    }

    agent = generation.agent
    region_score = generation.strategy_region_score_result
    if region_score is None:
        from evaluation.code_quality import evaluate_agent_strategy_region
        region_score = evaluate_agent_strategy_region(
            "",
            error=generation.failure_reason or "Complete Java validation did not run.",
        )

    compiler = analyze_compilation(compile_result)
    integration_result: IntegrationResult | None = None
    matches: list[MatchResult] = []
    match_error: str | None = None
    evaluation_started_at: str | None = None
    evaluation_finished_at: str | None = None
    evaluation_started: float | None = None

    # Stages 3-4: integrate the class, then execute the full configured
    # opponent/map/round/side matrix. This is the sole owner of match count.
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

    # Stage 5: classify the first blocking failure without discarding partial
    # diagnostics or successful match records.
    failure_category: str | None = None
    failure_reason: str | None = None
    failure_stage: str | None = None
    completed_matches = sum(result.ok for result in matches)
    expected_match_count = config.expected_match_count
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

    # Stage 6: aggregate game telemetry and calculate one objective per fixed
    # opponent. The weighted aggregate is reporting-only and never enters
    # parent or survivor selection.
    objective_started_at = _utc_now()
    objective_started = time.monotonic()
    game_metrics = compute_game_metrics(
        matches,
        fixed_opponent_weights=dict(config.evaluation_opponents),
        expected_match_count=config.expected_match_count,
        expected_matches_per_opponent=config.fixed_matches_per_opponent,
        evaluation_maps=config.evaluation_maps,
    )
    capability_result: FunctionCapabilityResult | None = None
    alignment_result: StrategyAlignmentResult | None = None
    if failure_stage is None:
        capability_result = evaluate_function_capability(generation.assembled_java, matches)
        if candidate.strategy_prompt.strip():
            alignment_backend = build_strategy_alignment_backend(
                "mock" if mock else config.execution_mode,
                base_url=getattr(llm_client, "base_url", config.llm_base_url),
                model=getattr(llm_client, "model", config.llm_model),
                timeout_seconds=getattr(llm_client, "timeout_seconds", 120.0),
                temperature=getattr(llm_client, "temperature", 0.0),
                max_output_tokens=getattr(llm_client, "max_output_tokens", None),
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
    game_payload["opponent_scores"] = {
        result.opponent_id: float(result.score)
        for result in game_metrics.opponent_results
    }
    game_payload["game_performance"] = reporting_game_performance(objectives)
    game_payload["evaluation_configuration"] = {
        "maps": list(config.evaluation_maps),
        "rounds_per_map": config.rounds_per_map,
        "swap_player_sides": config.swap_player_sides,
        "expected_match_count": config.expected_match_count,
    }
    compact_matches = [_compact_match_result(result) for result in matches]
    # This is the hand-off consumed by the next generation's Reflection stage.
    # Keep the exact evaluated values together so mutation never reconstructs
    # evidence from legacy metadata keys or recalculates an objective.
    reflection_evidence = {
        "schema_version": "phase4-reflection-context-v1",
        "candidate_id": candidate.id,
        "objectives": dict(objectives),
        "game_performance": game_payload["game_performance"],
        "evaluation_status": "failed" if failure_category else "evaluated",
        "failure_stage": failure_stage,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "generation": {
            "phenotype_artifact": (
                "phenotype/CandidateAgent.java" if compiler.compile_success else None
            ),
            "failure_source_artifact": (
                None if compiler.compile_success else "generation/normalized_candidate.java"
            ),
            "validation": generation.validation_result.to_json_dict(),
            "strategy_region_validation": {
                key: value.to_json_dict()
                for key, value in region_score.strategy_region_validation.items()
            },
        },
        "compilation": _compact_compilation_evidence(compile_result),
        "integration": _compact_integration_evidence(integration_result),
    }
    timing = {
        **candidate.timing,
        "generation_llm": generation_timing,
        "validation_duration_seconds": sum(
            float(item.generation.validation_timing.get("duration_seconds") or 0.0)
            for item in generation_attempts
        ),
        "compilation_duration_seconds": compilation_duration or 0.0,
        "integration_duration_seconds": 0.0 if integration_result is None else integration_result.duration_seconds,
        "evaluation_duration_seconds": evaluation_duration,
        "matches_total_duration_seconds": round(sum(match_durations), 9),
        "match_durations_seconds": match_durations,
        "strategy_alignment_llm": alignment_timing,
        "objective_calculation_duration_seconds": objective_duration,
        "validation": {
            **generation.validation_timing,
            "attempts": [
                {
                    "attempt": item.attempt,
                    **item.generation.validation_timing,
                }
                for item in generation_attempts
            ],
        },
        "compilation": {
            "started_at": compilation_started_at,
            "finished_at": compilation_finished_at,
            "duration_seconds": representative_compilation_duration,
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
    generation_llm_duration = timing["generation_llm"].get("duration_seconds") or 0.0
    validation_duration = timing["validation_duration_seconds"]
    compilation_duration_value = timing["compilation_duration_seconds"]
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
        "duration_seconds": operation_generation + float(generation_llm_duration) + validation_duration + compilation_duration_value + float(timing["integration"].get("duration_seconds") or 0.0) + evaluation_duration_value,
        "includes": ["mutation_generation", "crossover_generation", "generation_llm", "validation", "compilation", "integration", "evaluation"],
        "status": "failed" if failure_stage else "success",
        "failure_stage": failure_stage,
    }
    # Stage 7: rebuild the candidate with evaluated phenotype, objectives,
    # lineage, failure state, reflection evidence, and timing.
    evaluated_candidate = Candidate(
        id=candidate.id,
        generation=candidate.generation,
        parent_ids=candidate.parent_ids,
        strategy_prompt=candidate.strategy_prompt,
        generation_prompt=candidate.generation_prompt,
        inherited_java=candidate.inherited_java,
        java_parent_id=candidate.java_parent_id,
        generated_java=generation.assembled_java if compiler.compile_success else "",
        generated_java_path=(
            str(agent.source_path) if agent is not None and compiler.compile_success else None
        ),
        operator=candidate.operator,
        mutation_type=candidate.mutation_type,
        strategy_parent_id=candidate.strategy_parent_id,
        generation_prompt_parent_id=candidate.generation_prompt_parent_id,
        source_candidate_ids=candidate.source_candidate_ids,
        compile_status=compile_result.status if compile_result else "not_run",
        game_eval_result=game_payload,
        code_quality_result=quality_payload,
        fitness_objectives=objectives,
        strategy_signature=dict(candidate.strategy_signature),
        strategy_niche=candidate.strategy_niche,
        mutation_intent=candidate.mutation_intent,
        parent_strategy_niche=candidate.parent_strategy_niche,
        niche_changed=candidate.niche_changed,
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
    assert (
        evaluated_candidate.strategy_prompt,
        evaluated_candidate.generation_prompt,
        evaluated_candidate.inherited_java,
    ) == genotype_before
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
        generation_attempts=generation_attempts,
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
        if item.opponent_id == "allinbot":
            manifest_path = repository_root / "third_party" / "gui_opponents" / "resolved_allibot.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OpponentSetupError(f"AlliBot resolution manifest is missing or invalid: {manifest_path}") from exc
            if (
                manifest.get("schema_version") != "eagle-allibot-v2"
                or manifest.get("class_name") != ALLINBOT_UPSTREAM_CLASS_NAME
            ):
                raise OpponentSetupError(
                    "AllInBot resolution manifest does not match its pinned upstream "
                    f"class {ALLINBOT_UPSTREAM_CLASS_NAME}: {manifest_path}"
                )
            digest = hashlib.sha256(jar_path.read_bytes()).hexdigest() if jar_path is not None else ""
            if digest != manifest.get("jar_sha256"):
                raise OpponentSetupError(f"AllInBot JAR hash does not match its resolution manifest: {jar_path}")
            source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
            if not any(path.is_file() and path.suffix == ".jar" for path in source_lib.glob("*.jar")):
                raise OpponentSetupError(f"AllInBot upstream libraries are missing: {source_lib}")


def evaluate_matches(*, candidate: Candidate, agent: GeneratedJavaAgent, config: ExperimentConfig, classes_dir: Path, match_artifacts_dir: Path | None, mock: bool, ordinal: int) -> tuple[list[MatchResult], str | None]:
    """Run the complete fixed seven-opponent evaluation matrix."""
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
        matrix_opponents = tuple(
            MatrixOpponent(
                item.opponent_id,
                item.weight,
            )
            for item in opponents
        )
        specifications = build_match_matrix(
            matrix_opponents,
            canonical_evaluation_maps(config.evaluation_maps),
            rounds_per_map=config.rounds_per_map,
            swap_player_sides=config.swap_player_sides,
        )
        expected_matches = len(specifications)
        if len(opponents) != len(config.evaluation_opponents):
            return match_results, (
                f"evaluation roster has {len(opponents)} opponents; "
                f"expected {len(config.evaluation_opponents)}"
            )
        opponent_by_id = {item.opponent_id: item for item in opponents}
        for specification in specifications:
            opponent = opponent_by_id[specification.opponent_id]
            try:
                result = run_microrts_match(
                    microrts_dir=config.microrts_dir, classes_dir=candidate_classes_dir,
                    agent_class=agent.qualified_class_name, opponent=opponent.class_name,
                    opponent_id=opponent.opponent_id,
                    opponent_name=_opponent_display_name(opponent.opponent_id),
                    tick_limit=config.tick_limit, match_index=specification.match_index,
                    match_artifacts_dir=match_artifacts_dir,
                    scoring_config=scoring_config_from_experiment(config), mock=mock,
                    mock_score=config.mock_score_base + config.mock_score_step * (
                        ordinal + specification.match_index
                    ),
                    timeout_seconds=config.match_timeout_seconds,
                    map_path=specification.map_path, candidate_id=candidate.id,
                    generation=candidate.generation,
                    candidate_player=specification.candidate_player,
                    generation_index=candidate.generation,
                    source_hash=source_hash, class_hash=class_hash,
                    extra_classpath_entries=opponent.classpath_entries,
                    artifact_mode=config.match_artifact_mode,
                    map_id=specification.map_id,
                    round_index=specification.round_index,
                    opponent_weight=specification.opponent_weight,
                )
            except (RuntimeError, OSError) as exc:
                result = MatchResult(
                    ok=False,
                    score=0.0,
                    command=[],
                    match_index=specification.match_index,
                    generation=candidate.generation,
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
                opponent_weight=specification.opponent_weight,
            )
            match_results.append(result)
            if not result.ok and first_error is None:
                first_error = match_error_message(result)
    except (RuntimeError, OSError) as exc:
        return match_results, str(exc)
    expected_matches = config.expected_match_count
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
        _prepare_worker_rush_opponent(config, classes_dir=classes_dir)
        if not mock and classes_dir is not None
        else None
    )
    safe_allinbot_classes = (
        _prepare_safe_allinbot_opponent(
            config,
            classes_dir=classes_dir,
            repository_root=repository_root,
        )
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
                if item.opponent_id == "allinbot":
                    source_lib = repository_root / "third_party" / "gui_opponents" / "src" / "allibot" / "lib"
                    libraries = tuple(sorted(path.resolve() for path in source_lib.glob("*.jar") if path.is_file()))
                    if not mock and not libraries:
                        raise OpponentSetupError(f"AlliBot upstream libraries are missing: {source_lib}")
                    if safe_allinbot_classes is None:
                        raise OpponentSetupError("SafeAllInBot adapter was not prepared for real evaluation.")
                    classpath_entries = (safe_allinbot_classes, jar_path, *libraries)
        opponents.append(EvaluationOpponent(item.opponent_id, item.class_name, classpath_entries, configured_weights[item.opponent_id]))
    return tuple(opponents)


def _prepare_safe_allinbot_opponent(
    config: ExperimentConfig,
    *,
    classes_dir: Path,
    repository_root: Path | None = None,
) -> Path:
    """Compile the fault-containing reflection adapter once per run/final test.

    The adapter deliberately imports no AlliBot classes. The original pinned JAR
    is verified in preflight and stays on the match classpath only for reflective
    runtime delegation.
    """

    repository_root = (repository_root or _repository_root()).resolve()
    root = classes_dir.resolve() / "_opponent_adapters" / "safe_allinbot"
    source = repository_root / "eagle" / "opponent_adapters" / "SafeAllInBot.java"
    output = root / "classes"
    class_file = output / "ai" / "eagle" / "SafeAllInBot.class"
    manifest_path = root / "manifest.json"
    jar_path = repository_root / "third_party" / "gui_opponents" / "jars" / "allibot.jar"
    if not source.is_file():
        raise OpponentSetupError(f"SafeAllInBot adapter source is missing: {source}")
    if not jar_path.is_file():
        raise OpponentSetupError(f"Pinned AllInBot JAR is missing: {jar_path}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    jar_hash = hashlib.sha256(jar_path.read_bytes()).hexdigest()
    if class_file.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if (
            manifest.get("source_sha256") == source_hash
            and manifest.get("delegate_class") == ALLINBOT_UPSTREAM_CLASS_NAME
            and manifest.get("upstream_jar_sha256") == jar_hash
        ):
            return output
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
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
            "SafeAllInBot adapter could not be compiled: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "eagle-search-opponent-source-v1",
                "opponent_id": "allinbot",
                "class_name": SAFE_ALLINBOT_CLASS_NAME,
                "delegate_class": ALLINBOT_UPSTREAM_CLASS_NAME,
                "implementation": "reflection adapter with permanent passive fallback",
                "source_path": str(source),
                "source_sha256": source_hash,
                "upstream_jar_path": str(jar_path),
                "upstream_jar_sha256": jar_hash,
                "classes_dir": str(output),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return output


def _prepare_worker_rush_opponent(config: ExperimentConfig, *, classes_dir: Path) -> Path:
    """Compile the vendored upstream WorkerRush implementation once per run."""

    root = classes_dir.resolve() / "_opponent_adapters" / "worker_rush"
    source = (
        Path(__file__).resolve().parents[1]
        / "third_party" / "microrts" / "src" / "ai" / "abstraction" / "WorkerRush.java"
    )
    output = root / "classes"
    class_file = output / "ai" / "abstraction" / "WorkerRush.class"
    manifest_path = root / "manifest.json"
    if not source.is_file():
        raise OpponentSetupError(f"Canonical WorkerRush source is missing: {source}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if class_file.is_file() and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if manifest.get("source_sha256") == source_hash:
            return output
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
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
            "Canonical WorkerRush implementation could not be compiled: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "eagle-search-opponent-source-v1",
                "opponent_id": "workerrush",
                "class_name": "ai.abstraction.WorkerRush",
                "implementation": "vendored drchangliu/MicroRTS WorkerRush",
                "source_url": (
                    "https://github.com/drchangliu/MicroRTS/blob/master/"
                    "src/ai/abstraction/WorkerRush.java"
                ),
                "source_path": str(source),
                "source_sha256": source_hash,
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
        f" aggregate_game_performance={getattr(game_metrics, 'objective', None) if game_metrics else None}"
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
        f"opponent_scores={candidate.fitness_objectives} "
        f"{game_performance_detail} "
        f"code_quality_simplicity={quality.code_quality} "
        f"complexity_penalty={quality.complexity_penalty} "
        f"(cyclomatic={quality.cyclomatic_penalty}, nesting={quality.nesting_penalty}, "
        f"logical_loc={quality.logical_loc_penalty}, longest_function={quality.longest_function_penalty}){detail}",
        flush=True,
    )
