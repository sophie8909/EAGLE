"""Bounded Java generation, validation, compilation, and repair."""
from __future__ import annotations

from dataclasses import replace
from difflib import SequenceMatcher
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from eagle.artifacts import (
    write_generation_attempt_artifacts, write_generation_attempt_result,
    write_generation_repair_ledger,
)
from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.evaluation.compiler import normalize_compiler_paths
from eagle.evaluation.compiler import CompileResult, compile_generated_agent
from eagle.generation.agent_template import (
    JavaTemplatePaths,
    extract_strategy_region,
    load_java_template,
)
from eagle.generation.backend import GenerationBackend
from eagle.generation.java_agent_generator import (
    GeneratedJavaAgent,
    JavaAgentGenerationResult,
    ValidationResult,
    generate_java_agent_result,
)
from eagle.prompts import load_prompt, render_prompt
from eagle.timing import utc_now

from .records import BoundedGenerationResult, GenerationAttemptResult


class _DirectCodeReflectionBackend(GenerationBackend):
    """Expose an already-produced Code Reflection source to validation."""

    operation = "code_reflection_direct"
    model = None

    def __init__(self, source: str) -> None:
        self.source = source

    def generate(self, candidate: Candidate, class_name: str) -> str:
        if class_name != "CandidateAgent":
            raise ValueError("Code Reflection produces only CandidateAgent.")
        return self.source


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

    Attempt one normally uses the authoritative two-gene generation request.
    A Code Reflection child instead validates the Java already returned by its
    mutation and does not invoke the final Generator again. After a
    complete source fails validation or javac, later attempts receive a
    separate compile-repair request containing that phenotype and structured
    failure evidence. Extraction failures have no repairable complete source
    and therefore resample the base request. The first validation+javac success
    is promoted to the sole canonical class directory. This helper deliberately
    stops before Integration and matches so production smoke uses this path.
    """

    _validate_candidate_path_component(candidate.id)
    operation = getattr(backend, "operation", None)
    initial_seed_source = operation == "initial_java_seed"
    source_without_generation = operation in {
        "initial_java_seed",
        "self_play_fitness_refresh",
    }
    direct_code_source = (
        candidate.generated_java
        if candidate.mutation_type == "code" and candidate.generated_java
        else ""
    )
    max_attempts = 1 if source_without_generation else config.generation_max_attempts
    if max_attempts < 1:
        raise ValueError("generation_max_attempts must be at least 1.")
    base_request = (
        ""
        if source_without_generation
        else "Direct Java source from mutation/code_reflection/reflected_candidate.java"
        if direct_code_source
        else backend.authoritative_request(candidate, "CandidateAgent")
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
    source_template_path: Path | None = None
    if operation == "self_play_fitness_refresh":
        source_template_path = generated_agents_dir / candidate.id / "self_play_source_template.java"
        source_template_path.parent.mkdir(parents=True, exist_ok=True)
        source_template_path.write_text(candidate.generated_java, encoding="utf-8")
    attempts: list[GenerationAttemptResult] = []
    selected_attempt: int | None = None
    repair_parent: GenerationAttemptResult | None = None

    try:
        for attempt_number in range(1, max_attempts + 1):
            attempt_name = f"attempt_{attempt_number:03d}"
            request_kind = (
                "code_reflection_output"
                if direct_code_source and attempt_number == 1
                else "compile_repair"
                if not source_without_generation and repair_parent is not None
                else "initial_decode_retry"
                if not source_without_generation and attempt_number > 1
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
            if attempt_artifact_dir is not None and not source_without_generation:
                attempt_artifact_dir.mkdir(parents=True, exist_ok=True)
                (attempt_artifact_dir / "request.txt").write_text(request, encoding="utf-8")
            attempt_backend = (
                _DirectCodeReflectionBackend(direct_code_source)
                if direct_code_source and attempt_number == 1
                else backend
            )
            if hasattr(attempt_backend, "set_generation_attempt_context"):
                attempt_backend.set_generation_attempt_context(
                    attempt_number,
                    f"{candidate.id}:generation:{attempt_number:03d}",
                )
            if hasattr(attempt_backend, "set_generation_request_kind"):
                attempt_backend.set_generation_request_kind(request_kind)
            generation_started_at = utc_now()
            generation_started = time.monotonic()
            generation = generate_java_agent_result(
                candidate,
                attempt_backend,
                generated_agents_dir,
                template_paths=JavaTemplatePaths(
                    config.initial_java_seed_path
                    if initial_seed_source
                    else source_template_path
                    if source_template_path is not None
                    else config.agent_template_path
                ),
                authoritative_request=request,
                output_dir=candidate_source_root / attempt_name,
                attempt_artifact_dir=None if source_without_generation else attempt_artifact_dir,
            )
            if request_kind == "compile_repair" and repair_parent is not None:
                generation = _enforce_compile_repair_delta(
                    generation,
                    previous_source=repair_parent.generation.assembled_java,
                    parent_validation=repair_parent.generation.validation_result,
                )
            generation_finished_at = utc_now()
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
                "started_at": None if source_without_generation else generation_started_at,
                "finished_at": None if source_without_generation else generation_finished_at,
                "duration_seconds": None if source_without_generation else generation_duration,
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
                compilation_started_at = utc_now()
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
                compilation_finished_at = utc_now()
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
            if candidate_artifact_dir is not None and not source_without_generation:
                write_generation_attempt_artifacts(
                    candidate_artifact_dir,
                    attempt,
                    initial_seed_source=source_without_generation,
                )
                write_generation_repair_ledger(
                    candidate_artifact_dir,
                    attempts,
                    initial_seed_source=source_without_generation,
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
    if candidate_artifact_dir is not None and not source_without_generation:
        write_generation_attempt_result(candidate_artifact_dir, attempts[-1])
        write_generation_repair_ledger(
            candidate_artifact_dir,
            attempts,
            initial_seed_source=source_without_generation,
        )
    return BoundedGenerationResult(
        attempts=tuple(attempts),
        selected_attempt=selected_attempt,
        final_attempt=final_attempt,
        max_attempts=max_attempts,
        initial_seed_source=initial_seed_source,
        source_without_generation=source_without_generation,
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
            "compile_evidence": normalize_compiler_paths(json.dumps(evidence, ensure_ascii=False, indent=2)),
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


def compile_agent_source(
    agent: GeneratedJavaAgent,
    *,
    config: ExperimentConfig,
    classes_dir: Path,
    candidate_id: str,
    mock: bool,
) -> CompileResult:
    return compile_generated_agent(
        agent.source_paths,
        microrts_dir=config.microrts_dir,
        output_dir=classes_dir / candidate_id,
        mock=mock,
    )


def compile_error_message(result: CompileResult) -> str:
    diagnostics = result.errors if result is not None else ()
    if diagnostics:
        return diagnostics[0].message
    stderr = (result.stderr or "").strip() if result is not None else ""
    if stderr:
        return stderr.splitlines()[0]
    return f"javac returned {result.returncode}" if result is not None else "Compilation was not run."
