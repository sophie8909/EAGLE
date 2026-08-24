"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from evaluation.compiler import CompileResult
from evaluation.code_quality import OBJECTIVE_FORMULA_VERSION, analyze_compilation
from evaluation.objectives import OBJECTIVE_DIRECTIONS
from evaluation.microrts_runner import INTEGRATION_CHECK_NAMES, IntegrationResult
from evaluation.runtime_evaluation import DEFAULT_MAP_PATH, MatchResult
from generation.java_agent_generator import ValidationResult

from .candidate import Candidate, compact_candidate_metadata
from .config import ExperimentConfig

if TYPE_CHECKING:
    from .evaluation import CandidateEvaluation, GenerationAttemptResult


# Writers are grouped by lifecycle boundary: genotype inputs first,
# stage/evaluation evidence next, and run summaries/configuration last.
ARTIFACT_SCHEMA_VERSION = "phase4-v4"


def write_candidate_inputs(candidates_dir: Path, candidate: Candidate) -> None:
    """Persist lineage and the pre-generation genotype before external work."""

    candidate_dir = candidates_dir / candidate.id
    genotype_dir = candidate_dir / "genotype"
    genotype_dir.mkdir(parents=True, exist_ok=True)
    (genotype_dir / "policy_prompt.txt").write_text(candidate.strategy_prompt, encoding="utf-8")
    write_json(
        genotype_dir / "strategy_signature.json",
        {
            "schema_version": "eagle-strategy-diversity-v1",
            "strategy_signature": dict(candidate.strategy_signature),
            "strategy_niche": candidate.strategy_niche,
            "mutation_intent": candidate.mutation_intent,
            "parent_strategy_niche": candidate.parent_strategy_niche,
            "niche_changed": candidate.niche_changed,
        },
    )
    (genotype_dir / "code_generation_prompt.txt").write_text(candidate.generation_prompt, encoding="utf-8")
    reflection_dir = candidate_dir / "mutation" / "strategy_reflection"
    if (reflection_dir / "metadata.json").is_file():
        # ``Candidate.generation_input`` supplies the strategy placeholder with
        # this stripped value.  Record it at the last persistence boundary
        # before the Generator call, including when Reflection fell back to the
        # inherited strategy after a role failure.
        (reflection_dir / "generator_strategy_input.txt").write_text(
            candidate.strategy_prompt.strip(),
            encoding="utf-8",
        )
    write_json(candidate_dir / "lineage.json", candidate.lineage_to_json_dict())
    if candidate.operator in {"crossover", "crossover+mutation"}:
        crossover_dir = candidate_dir / "crossover"
        crossover_dir.mkdir(exist_ok=True)
        write_json(
            crossover_dir / "provenance.json",
            {
                "lineage_schema_version": candidate.lineage_to_json_dict()["lineage_schema_version"],
                "candidate_id": candidate.id,
                "strategy_parent_id": candidate.strategy_parent_id,
                "generation_prompt_parent_id": candidate.generation_prompt_parent_id,
            },
        )


def write_aos_reward_artifact(candidates_dir: Path, reward: dict) -> None:
    """Persist post-evaluation AOS credit beside the mutated candidate."""

    candidate_id = str(reward.get("offspring_id") or "")
    if not candidate_id:
        return
    write_json(candidates_dir / candidate_id / "aos" / "reward.json", {
        "schema_version": "eagle-aos-reward-v3",
        **reward,
    })


def write_candidate_artifacts(candidates_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Save per-candidate state plus the Phase 2A mutation evidence."""

    candidate_dir = candidates_dir / evaluation.candidate.id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    write_candidate_inputs(candidates_dir, evaluation.candidate)
    initial_seed_source = (evaluation.generation_timing or {}).get("operation") == "initial_java_seed"
    if not initial_seed_source:
        for attempt in evaluation.generation_attempts:
            write_generation_attempt_artifacts(
                candidate_dir,
                attempt,
                initial_seed_source=False,
            )
        write_generation_repair_ledger(
            candidate_dir,
            evaluation.generation_attempts,
            initial_seed_source=False,
        )
    _write_generation_artifacts(candidate_dir, evaluation)
    validation_payload = validation_to_dict(evaluation.result.validation_result)
    if validation_payload is None:
        validation_payload = {"status": "blocked", "failure_stage": evaluation.result.failure_stage, "failure_reason": evaluation.result.failure_reason}
    validation_payload["timing"] = evaluation.candidate.timing.get("validation")
    generation_timing = evaluation.generation_timing or {}
    representative_attempt_number = generation_timing.get("selected_attempt") or generation_timing.get("final_attempt")
    representative_attempt_ref = (
        None
        if initial_seed_source or representative_attempt_number is None
        else f"generation/attempts/attempt_{int(representative_attempt_number):03d}"
    )
    validation_payload["attempt_ref"] = representative_attempt_ref
    write_json(candidate_dir / "validation" / "validation_result.json", validation_payload)
    compilation_dir = candidate_dir / "compilation"
    compilation_dir.mkdir(parents=True, exist_ok=True)
    compilation = evaluation.compile_result
    compilation_payload = compile_to_dict(compilation)
    if compilation_payload is None:
        compilation_payload = blocked_compilation_payload(
            evaluation.result.failure_stage,
            evaluation.result.failure_reason or "Compilation was not run because an earlier stage failed.",
        )
    compilation_payload["timing"] = evaluation.candidate.timing.get("compilation")
    compilation_payload["attempt_ref"] = representative_attempt_ref
    write_json(compilation_dir / "compilation_result.json", compilation_payload)
    (compilation_dir / "command.txt").write_text("" if compilation is None else " ".join(compilation.command), encoding="utf-8")
    (compilation_dir / "stdout.txt").write_text("" if compilation is None else compilation.stdout, encoding="utf-8")
    (compilation_dir / "stderr.txt").write_text("" if compilation is None else compilation.stderr, encoding="utf-8")
    integration_dir = candidate_dir / "integration"
    integration_dir.mkdir(parents=True, exist_ok=True)
    integration = evaluation.integration_result
    integration_payload = integration_to_dict(integration)
    if integration_payload is None:
        integration_payload = blocked_integration_payload(
            evaluation.result.failure_stage,
            evaluation.result.failure_reason or "Integration was not run because an earlier stage failed.",
        )
    integration_payload["timing"] = evaluation.candidate.timing.get("integration")
    write_json(integration_dir / "integration_result.json", integration_payload)
    (integration_dir / "stdout.txt").write_text("" if integration is None else integration.stdout, encoding="utf-8")
    (integration_dir / "stderr.txt").write_text("" if integration is None else integration.stderr, encoding="utf-8")
    mutation_record = evaluation.candidate.metadata.get("mutation")
    if mutation_record is not None:
        mutation_type = str(mutation_record.get("type") or evaluation.candidate.mutation_type or "unknown")
        mutation_path = candidate_dir / "mutation" / f"{mutation_type}_reflection" / "metadata.json"
        if not mutation_path.exists():
            _write_mutation_artifacts(candidate_dir, mutation_record)
            write_json(mutation_path, _mutation_metadata_record(mutation_record))
    write_json(candidate_dir / "timing.json", evaluation.candidate.timing)
    _write_evaluation_artifacts(candidate_dir, evaluation)
    write_candidate_snapshot(candidates_dir, evaluation.candidate)


def _write_evaluation_artifacts(candidate_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Persist canonical post-Integration evaluation evidence and objective values."""

    alignment_dir = candidate_dir / "strategy_alignment"
    alignment_dir.mkdir(parents=True, exist_ok=True)
    alignment = evaluation.strategy_alignment_result
    if alignment is None:
        request = ""
        raw_response = ""
        blank_policy = not evaluation.candidate.strategy_prompt.strip()
        alignment_payload = {
            "status": "not_applicable" if blank_policy else "blocked",
            "request": request,
            "raw_response": raw_response,
            "parsed_response": None,
            "score": None if blank_policy else 0.0,
            "reason": (
                "Strategy Alignment is not applicable to an empty policy prompt."
                if blank_policy
                else "Strategy Alignment runs only after the complete evaluation matrix."
            ),
            "error": None if blank_policy else evaluation.result.failure_reason,
            "attempts": [],
        }
    else:
        request = alignment.request
        raw_response = alignment.raw_response
        alignment_payload = alignment.to_json_dict()
    (alignment_dir / "request.txt").write_text(request, encoding="utf-8")
    (alignment_dir / "response_raw.txt").write_text(raw_response, encoding="utf-8")
    write_json(alignment_dir / "result.json", alignment_payload)

    evaluation_dir = candidate_dir / "evaluation"
    game_payload = evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else {}
    capability = evaluation.function_capability_result
    capability_payload = (
        {
            "status": "blocked",
            "function_score": 0,
            "reason": "Function Capability runs only after the complete evaluation matrix.",
            "evidence": {},
        }
        if capability is None
        else {"status": "success", **capability.to_json_dict()}
    )
    code_quality_payload = evaluation.code_quality_breakdown.to_json_dict()
    objectives_payload = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "objective_formula_version": OBJECTIVE_FORMULA_VERSION,
        "candidate_id": evaluation.candidate.id,
        "game_performance": game_payload.get("game_performance"),
        "opponent_scores": (
            dict(game_payload.get("opponent_scores"))
            if isinstance(game_payload.get("opponent_scores"), dict)
            else {
                str(item.get("opponent_id") or "unknown"): float(item.get("score") or 0.0)
                for item in (game_payload.get("opponent_results") or [])
                if isinstance(item, dict)
            }
        ),
        "opponent_results": list(game_payload.get("opponent_results") or []),
        "objective_names": list(evaluation.candidate.fitness_objectives),
    }
    write_json(evaluation_dir / "game_performance.json", game_payload)
    write_json(
        evaluation_dir / "commentary_aggregation.json",
        game_payload.get("commentary_aggregation") or {
            "schema_version": "candidate-commentary-aggregation-v1",
            "candidate_id": evaluation.candidate.id,
            "match_count": len(evaluation.match_results),
            "commented_match_count": 0,
            "failed_commentary_count": 0,
            "opponent_summaries": [],
            "unavailable_commentary": [{"reason": "commentary not run"}],
        },
    )
    write_json(evaluation_dir / "function_capability.json", capability_payload)
    write_json(evaluation_dir / "code_quality.json", code_quality_payload)
    write_json(evaluation_dir / "objectives.json", objectives_payload)
    if evaluation.result.failure_stage == "runtime":
        write_json(
            evaluation_dir / "runtime_failure.json",
            {
                "status": "failed",
                "failure_stage": "runtime",
                "failure_category": evaluation.result.failure_category,
                "failure_reason": evaluation.result.failure_reason,
                "completed_match_count": sum(result.ok for result in evaluation.match_results),
                "attempted_match_count": len(evaluation.match_results),
                "expected_match_count": evaluation.game_metrics.expected_match_count if evaluation.game_metrics else None,
                "missing_match_count": (
                    max(0, evaluation.game_metrics.expected_match_count - sum(result.ok for result in evaluation.match_results))
                    if evaluation.game_metrics else None
                ),
                "retained_matches": [match_to_dict(result) for result in evaluation.match_results],
            },
        )


def _write_mutation_artifacts(candidate_dir: Path, mutation_record: dict) -> None:
    """Persist reflector and rewriter evidence from the canonical mutation record."""

    mutation_type = str(mutation_record.get("type") or "unknown")
    mutation_dir = candidate_dir / "mutation" / f"{mutation_type}_reflection"
    if "evidence" in mutation_record:
        write_json(mutation_dir / "reflection_context.json", mutation_record["evidence"])
    reflection = mutation_record.get("reflection") or {}
    if reflection:
        (mutation_dir / "reflector_request.txt").write_text(
            str(reflection.get("request") or ""), encoding="utf-8"
        )
        (mutation_dir / "reflector_response_raw.txt").write_text(
            str(reflection.get("raw_response") or ""), encoding="utf-8"
        )
    rewrite = mutation_record.get("rewrite")
    if rewrite:
        (mutation_dir / "rewriter_request.txt").write_text(
            str(rewrite.get("request") or ""), encoding="utf-8"
        )
        (mutation_dir / "rewriter_response_raw.txt").write_text(
            str(rewrite.get("raw_response") or ""), encoding="utf-8"
        )


def _mutation_metadata_record(record: dict) -> dict:
    payload = dict(record)
    for key in ("reflection", "rewrite"):
        stage = payload.get(key)
        if isinstance(stage, dict):
            payload[key] = {
                name: value
                for name, value in stage.items()
                if name not in {"request", "raw_response"}
            }
    return payload


def write_generation_attempt_artifacts(
    candidate_dir: Path,
    attempt: "GenerationAttemptResult",
    *,
    initial_seed_source: bool,
) -> None:
    """Persist one decoder attempt without overwriting sibling evidence."""

    attempt_dir = (
        candidate_dir
        / "generation"
        / "attempts"
        / f"attempt_{attempt.attempt:03d}"
    )
    attempt_dir.mkdir(parents=True, exist_ok=True)
    generation = attempt.generation
    (attempt_dir / "request.txt").write_text(
        "" if initial_seed_source else attempt.request,
        encoding="utf-8",
    )
    (attempt_dir / "response_raw.txt").write_text(
        "" if initial_seed_source else generation.raw_llm_output,
        encoding="utf-8",
    )
    (attempt_dir / "extracted_candidate.java").write_text(
        generation.extracted_code,
        encoding="utf-8",
    )
    (attempt_dir / "normalized_candidate.java").write_text(
        generation.assembled_java,
        encoding="utf-8",
    )
    validation_dir = attempt_dir / "validation"
    validation_payload = validation_to_dict(generation.validation_result) or {
        "status": "blocked",
        "failure_reason": generation.failure_reason,
    }
    validation_payload["timing"] = generation.validation_timing
    write_json(validation_dir / "validation_result.json", validation_payload)
    compilation_dir = attempt_dir / "compilation"
    compilation = attempt.compile_result
    compilation_payload = compile_to_dict(compilation)
    if compilation_payload is None:
        compilation_payload = blocked_compilation_payload(
            generation.failure_stage,
            attempt.compile_error
            or generation.failure_reason
            or "Compilation was not run because source validation failed.",
        )
    compilation_payload["timing"] = attempt.compilation_timing
    write_json(compilation_dir / "compilation_result.json", compilation_payload)
    (compilation_dir / "command.txt").write_text(
        "" if compilation is None else " ".join(compilation.command),
        encoding="utf-8",
    )
    (compilation_dir / "stdout.txt").write_text(
        "" if compilation is None else compilation.stdout,
        encoding="utf-8",
    )
    (compilation_dir / "stderr.txt").write_text(
        "" if compilation is None else compilation.stderr,
        encoding="utf-8",
    )
    write_json(
        attempt_dir / "timing.json",
        {
            "generation": attempt.generation_timing,
            "validation": generation.validation_timing,
            "compilation": attempt.compilation_timing,
        },
    )
    write_json(
        attempt_dir / "result.json",
        {
            "attempt": attempt.attempt,
            "generation_attempt_id": attempt.generation_timing.get("generation_attempt_id"),
            "request_sha256": attempt.generation_timing.get("request_sha256"),
            "request_kind": attempt.request_kind,
            "repair_parent_attempt": attempt.repair_parent_attempt,
            "repair_of_attempt": attempt.repair_parent_attempt,
            "previous_source_sha256": attempt.generation_timing.get("previous_source_sha256"),
            "status": (
                "success"
                if attempt.compile_result is not None and attempt.compile_result.ok
                else "failed"
            ),
            "failure_stage": (
                None
                if attempt.compile_result is not None and attempt.compile_result.ok
                else "compilation"
                if generation.agent is not None
                else generation.failure_stage
            ),
            "failure_category": (
                None
                if attempt.compile_result is not None and attempt.compile_result.ok
                else "Java compile failure"
                if generation.agent is not None
                else generation.failure_category
            ),
            "failure_reason": (
                None
                if attempt.compile_result is not None and attempt.compile_result.ok
                else attempt.compile_error
                or (compilation.stderr if compilation is not None else None)
                or generation.failure_reason
            ),
            "selected": attempt.selected,
            "final": attempt.final,
        },
    )
    if attempt.repair_evidence is not None:
        write_json(attempt_dir / "repair_input.json", attempt.repair_evidence)


def write_generation_repair_ledger(
    candidate_dir: Path,
    attempts: list["GenerationAttemptResult"] | tuple["GenerationAttemptResult", ...],
    *,
    initial_seed_source: bool,
) -> None:
    """Project the bounded decoder chain without duplicating large evidence."""

    if initial_seed_source:
        return
    write_json(
        candidate_dir / "generation" / "repair_ledger.json",
        {
            "schema_version": "eagle-java-compile-repair-ledger-v1",
            "selected_attempt": next(
                (item.attempt for item in attempts if item.selected),
                None,
            ),
            "final_attempt": next(
                (item.attempt for item in reversed(attempts) if item.final),
                attempts[-1].attempt if attempts else None,
            ),
            "attempts": [
                {
                    "attempt": item.attempt,
                    "request_kind": item.request_kind,
                    "request_sha256": item.generation_timing.get("request_sha256"),
                    "repair_parent_attempt": item.repair_parent_attempt,
                    "repair_of_attempt": item.repair_parent_attempt,
                    "previous_source_sha256": item.generation_timing.get("previous_source_sha256"),
                    "request_artifact": (
                        f"generation/attempts/attempt_{item.attempt:03d}/request.txt"
                    ),
                    "source_artifact": (
                        f"generation/attempts/attempt_{item.attempt:03d}/normalized_candidate.java"
                    ),
                    "repair_evidence_artifact": (
                        None
                        if item.repair_evidence is None
                        else f"generation/attempts/attempt_{item.attempt:03d}/repair_input.json"
                    ),
                    "validation_artifact": (
                        f"generation/attempts/attempt_{item.attempt:03d}/validation/validation_result.json"
                    ),
                    "compilation_artifact": (
                        f"generation/attempts/attempt_{item.attempt:03d}/compilation/compilation_result.json"
                    ),
                    "status": (
                        "success"
                        if item.compile_result is not None and item.compile_result.ok
                        else "failed"
                    ),
                    "selected": item.selected,
                    "final": item.final,
                }
                for item in attempts
            ],
        },
    )

def _write_generation_artifacts(candidate_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Persist the complete final Java-generation request and response envelope."""

    generation_dir = candidate_dir / "generation"
    generation_dir.mkdir(parents=True, exist_ok=True)
    result = evaluation.result
    generation_timing = evaluation.generation_timing or {}
    initial_seed_source = generation_timing.get("operation") == "initial_java_seed"
    representative_attempt = next(
        (
            item
            for item in evaluation.generation_attempts
            if item.attempt
            == (generation_timing.get("selected_attempt") or generation_timing.get("final_attempt"))
        ),
        None,
    )
    request = "" if initial_seed_source else (
        representative_attempt.request
        if representative_attempt is not None
        else evaluation.candidate.generation_input(class_name="CandidateAgent")
    )
    (generation_dir / "request.txt").write_text(request, encoding="utf-8")
    (generation_dir / "response_raw.txt").write_text(
        "" if initial_seed_source else result.raw_llm_output or "",
        encoding="utf-8",
    )
    (generation_dir / "extracted_candidate.java").write_text(result.extracted_code or "", encoding="utf-8")
    (generation_dir / "normalized_candidate.java").write_text(
        result.assembled_java or evaluation.candidate.generated_java or "",
        encoding="utf-8",
    )
    if evaluation.compile_result is not None and evaluation.compile_result.ok:
        phenotype_dir = candidate_dir / "phenotype"
        phenotype_dir.mkdir(parents=True, exist_ok=True)
        (phenotype_dir / "CandidateAgent.java").write_text(
            result.assembled_java or evaluation.candidate.generated_java or "",
            encoding="utf-8",
        )
    write_json(generation_dir / "result.json", {
        "status": (
            "success"
            if evaluation.compile_result is not None and evaluation.compile_result.ok
            else "failed"
        ),
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
        "validation_result": validation_to_dict(result.validation_result),
        "stage": "generation",
        "operation": generation_timing.get("operation"),
        "model": generation_timing.get("model"),
        "attempts": generation_timing.get("attempts", []),
        "max_attempts": generation_timing.get("max_attempts", 1),
        "selected_attempt": generation_timing.get("selected_attempt"),
        "final_attempt": generation_timing.get("final_attempt", 1),
        "representative_failure_attempt": (
            generation_timing.get("final_attempt")
            if generation_timing.get("selected_attempt") is None and not initial_seed_source
            else None
        ),
        "canonical_attempt_artifact": (
            None
            if initial_seed_source or generation_timing.get("selected_attempt") is None
            else "generation/attempts/"
            f"attempt_{int(generation_timing['selected_attempt']):03d}"
        ),
        "representative_attempt_artifact": (
            None
            if initial_seed_source
            else "generation/attempts/"
            f"attempt_{int(generation_timing.get('selected_attempt') or generation_timing.get('final_attempt') or 1):03d}"
        ),
        "request_sha256": (
            None
            if initial_seed_source
            else hashlib.sha256(request.encode("utf-8")).hexdigest()
        ),
        "source": generation_timing.get("source"),
    })


def write_run_config(run_dir: Path, config: ExperimentConfig, *, mock: bool) -> None:
    """Write the one immutable, fully resolved experiment configuration."""

    path = run_dir / "config.yaml"
    if path.exists():
        raise ValueError(f"Run config is immutable and already exists: {path}")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        yaml.safe_dump(config.to_mapping(mock=mock), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_summary(
    run_dir: Path,
    *,
    config: ExperimentConfig,
    final_population: list[Candidate],
    best_candidate: Candidate | None,
    mock: bool,
    completed_generation: int | None = None,
    stop_reason: str | None = None,
) -> None:
    write_json(run_dir / "summary.json", {
        "mock": mock,
        "generations": config.generations,
        "completed_generation": completed_generation,
        "stop_reason": stop_reason,
        "population_size": config.population_size,
        "objectives": list(OBJECTIVE_DIRECTIONS),
        "reporting_metrics": ["game_performance"],
        "best_candidate": None if best_candidate is None else {
            "candidate_id": best_candidate.id,
            "candidate": f"candidates/{best_candidate.id}/candidate.json",
            "fitness_objectives": dict(best_candidate.fitness_objectives),
        },
        "final_population_ids": [candidate.id for candidate in final_population],
        "final_generation": (
            None if completed_generation is None
            else f"generations/generation_{completed_generation:04d}.json"
        ),
    })


def write_candidate_snapshot(candidates_dir: Path, candidate: Candidate) -> None:
    """Write the lightweight canonical candidate index and resumable references."""

    game = candidate.game_eval_result or {}
    artifact_references = {
        "lineage": "lineage.json",
        "policy_prompt": "genotype/policy_prompt.txt",
        "code_generation_prompt": "genotype/code_generation_prompt.txt",
        "generation": "generation/result.json",
        "validation": "validation/validation_result.json",
        "compilation": "compilation/compilation_result.json",
        "integration": "integration/integration_result.json",
        "matches": "matches/",
        "game_performance": "evaluation/game_performance.json",
        "function_capability": "evaluation/function_capability.json",
        "strategy_alignment": "strategy_alignment/result.json",
        "code_quality": "evaluation/code_quality.json",
        "objectives": "evaluation/objectives.json",
        "timing": "timing.json",
    }
    candidate_dir = candidates_dir / candidate.id
    if (candidate_dir / "phenotype" / "CandidateAgent.java").is_file():
        artifact_references["generated_java"] = "phenotype/CandidateAgent.java"
    else:
        artifact_references["failed_generation_source"] = "generation/normalized_candidate.java"
    if (candidate_dir / "mutation" / "strategy_reflection" / "metadata.json").is_file():
        artifact_references.update({
            "strategy_reflection": "mutation/strategy_reflection/metadata.json",
            "generator_strategy_input": "mutation/strategy_reflection/generator_strategy_input.txt",
        })
    payload = {
        "candidate_schema_version": "eagle-candidate-v4",
        "candidate_id": candidate.id,
        "generation": candidate.generation,
        "parent_ids": list(candidate.parent_ids),
        "operator": candidate.operator,
        "mutation_type": candidate.mutation_type,
        "strategy_parent_id": candidate.strategy_parent_id,
        "generation_prompt_parent_id": candidate.generation_prompt_parent_id,
        "source_candidate_ids": list(candidate.resolved_source_candidate_ids()),
        "compile_status": candidate.compile_status,
        "status": candidate.status,
        "failure_stage": candidate.failure_stage,
        "failure_reason": candidate.failure_reason,
        "fitness_objectives": dict(candidate.fitness_objectives),
        "aggregate_game_performance": game.get("game_performance"),
        "opponent_scores": dict(game.get("opponent_scores") or {}),
        "strategy_signature": dict(candidate.strategy_signature),
        "strategy_niche": candidate.strategy_niche,
        "mutation_intent": candidate.mutation_intent,
        "parent_strategy_niche": candidate.parent_strategy_niche,
        "niche_changed": candidate.niche_changed,
        "metadata": compact_candidate_metadata(candidate.metadata),
        "timing_summary": dict(candidate.timing),
        "artifacts": artifact_references,
    }
    write_json(candidates_dir / candidate.id / "candidate.json", payload)


def validation_to_dict(result: ValidationResult | None) -> dict | None:
    return None if result is None else result.to_json_dict()


def integration_to_dict(result: IntegrationResult | None) -> dict | None:
    return None if result is None else result.to_json_dict()


def blocked_compilation_payload(failure_stage: str | None, reason: str) -> dict:
    return {
        "ok": False, "status": "blocked", "command": [], "stdout": "", "stderr": "", "returncode": None, "diagnostics": [], "warning_count": 0, "error_count": 0, "failure_stage": failure_stage, "failure_reason": reason,
    }

def blocked_integration_payload(failure_stage: str | None, reason: str) -> dict:
    return {
        "status": "blocked",
        "ordered_checks": [{"check": name, "status": "blocked", "reason": reason} for name in INTEGRATION_CHECK_NAMES],
        "integration_pass_ratio": 0.0,
        "failure_stage": failure_stage,
        "failure_reason": reason,
    }


def compile_to_dict(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    analysis = analyze_compilation(result)
    return {"ok": result.ok, "status": result.status, "command": result.command, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode, "diagnostics": [item.to_json_dict() for item in result.diagnostics], "warning_count": len(result.warnings), "error_count": len(result.errors), **analysis.to_json_dict()}


def match_to_dict(result: MatchResult) -> dict:
    if hasattr(result, "to_json_dict"):
        return result.to_json_dict()
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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
