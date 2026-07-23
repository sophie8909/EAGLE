"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from evaluation.compiler import CompileResult
from evaluation.code_quality import analyze_compilation
from evaluation.nsga2_objectives import OBJECTIVE_DIRECTIONS
from evaluation.microrts_runner import DEFAULT_MAP_PATH, INTEGRATION_CHECK_NAMES, IntegrationResult, MatchResult
from generation.java_agent_generator import ValidationResult

from .candidate import Candidate
from .opponents import EVALUATION_ROSTER
from .llm_profiles import LLMProfile
from .prompts import DEFAULT_PROMPT_TEMPLATE_PATH, load_prompt_templates
from .config import ExperimentConfig

if TYPE_CHECKING:
    from .evaluation import CandidateEvaluation


ARTIFACT_SCHEMA_VERSION = "phase4-v1"
OBJECTIVE_FORMULA_VERSION = "eagle-objectives-phase4-v1"


def append_result(path: Path, evaluation: CandidateEvaluation) -> None:
    """Append one evaluated candidate record to results.jsonl."""

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False))
        handle.write("\n")


def write_candidate_inputs(candidates_dir: Path, candidate: Candidate) -> None:
    """Persist lineage and the pre-generation genotype before external work."""

    candidate_dir = candidates_dir / candidate.id
    genotype_dir = candidate_dir / "genotype"
    genotype_dir.mkdir(parents=True, exist_ok=True)
    (genotype_dir / "strategy_prompt.txt").write_text(candidate.strategy_prompt, encoding="utf-8")
    (genotype_dir / "previous_code.java").write_text(candidate.previous_code, encoding="utf-8")
    (genotype_dir / "generation_prompt.txt").write_text(candidate.generation_prompt, encoding="utf-8")
    write_json(candidate_dir / "lineage.json", candidate.lineage_to_json_dict())
    if candidate.operator in {"crossover", "crossover+mutation"}:
        crossover_dir = candidate_dir / "crossover"
        crossover_dir.mkdir(exist_ok=True)
        write_json(
            crossover_dir / "provenance.json",
            {
                "lineage_schema_version": candidate.lineage_to_json_dict()["lineage_schema_version"],
                "candidate_id": candidate.candidate_id,
                "strategy_parent_id": candidate.strategy_parent_id,
                "previous_code_parent_id": candidate.previous_code_parent_id,
                "generation_prompt_parent_id": candidate.generation_prompt_parent_id,
            },
        )


def write_candidate_artifacts(candidates_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Save per-candidate state plus the Phase 2A mutation evidence."""

    candidate_dir = candidates_dir / evaluation.candidate.id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    write_candidate_inputs(candidates_dir, evaluation.candidate)
    _write_generation_artifacts(candidate_dir, evaluation)
    validation_payload = validation_to_dict(evaluation.result.validation_result)
    if validation_payload is None:
        validation_payload = {"status": "blocked", "failure_stage": evaluation.result.failure_stage, "failure_reason": evaluation.result.failure_reason}
    validation_payload["timing"] = evaluation.candidate.timing.get("validation")
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
        write_json(candidate_dir / "mutation" / "metadata.json", mutation_record)
        _write_canonical_mutation_artifacts(candidate_dir, mutation_record)
    write_json(candidate_dir / "timing.json", evaluation.candidate.timing)
    _write_evaluation_artifacts(candidate_dir, evaluation)
    write_json(candidate_dir / "prompt.json", {
        "strategy_description": evaluation.candidate.strategy_prompt,
        "generation_guidance": evaluation.candidate.generation_prompt,
        "previous_complete_java": evaluation.candidate.previous_code,
    })
    compile_log = "" if evaluation.compile_result is None else evaluation.compile_result.stdout + evaluation.compile_result.stderr
    (candidate_dir / "compile.log").write_text(compile_log, encoding="utf-8")
    write_json(candidate_dir / "compile_result.json", compile_to_dict(evaluation.compile_result))
    write_json(candidate_dir / "raw_microrts_result.json", [match_to_dict(result) for result in evaluation.match_results])
    write_json(candidate_dir / "game_metrics.json", evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else {})
    write_json(candidate_dir / "code_quality.json", {
        "code_quality": evaluation.code_quality_breakdown.code_quality,
        "code_quality_breakdown": evaluation.code_quality_breakdown.to_json_dict(),
        "strategy_consistency": evaluation.strategy_consistency_result.to_json_dict() if evaluation.strategy_consistency_result else None,
        "function_capability": None if evaluation.function_capability_result is None else evaluation.function_capability_result.to_json_dict(),
        "strategy_alignment": None if evaluation.strategy_alignment_result is None else evaluation.strategy_alignment_result.to_json_dict(),
    })
    write_json(candidate_dir / "objectives.json", evaluation.candidate.fitness_objectives)
    write_json(candidate_dir / "individual.json", evaluation.candidate.to_json_dict())
    write_json(candidate_dir / "candidate_result.json", candidate_result_to_dict(evaluation.result))
    write_json(candidate_dir / "result.json", candidate_result_to_dict(evaluation.result))
    if evaluation.result.failure_category is not None:
        write_failed_candidate_debug(candidates_dir.parent, evaluation)


def _write_evaluation_artifacts(candidate_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Persist canonical post-Integration evaluation evidence and objective values."""

    alignment_dir = candidate_dir / "strategy_alignment"
    alignment_dir.mkdir(parents=True, exist_ok=True)
    alignment = evaluation.strategy_alignment_result
    if alignment is None:
        request = ""
        raw_response = ""
        alignment_payload = {
            "status": "blocked",
            "request": request,
            "raw_response": raw_response,
            "parsed_response": None,
            "score": 0.0,
            "reason": "Strategy Alignment runs only after ten valid matches.",
            "error": evaluation.result.failure_reason,
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
            "reason": "Function Capability runs only after ten valid matches.",
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
        "game_performance": evaluation.candidate.fitness_objectives["game_performance"],
        "code_quality": evaluation.candidate.fitness_objectives["code_quality"],
        "objective_names": ["game_performance", "code_quality"],
    }
    write_json(evaluation_dir / "game_performance.json", game_payload)
    write_json(evaluation_dir / "function_capability.json", capability_payload)
    write_json(evaluation_dir / "code_quality.json", code_quality_payload)
    write_json(evaluation_dir / "objectives.json", objectives_payload)
    write_json(
        evaluation_dir / "summary.json",
        {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "objective_formula_version": OBJECTIVE_FORMULA_VERSION,
            "candidate_id": evaluation.candidate.id,
            "status": evaluation.candidate.status,
            "failure_stage": evaluation.result.failure_stage,
            "failure_category": evaluation.result.failure_category,
            "failure_reason": evaluation.result.failure_reason,
            "completed_match_count": sum(result.ok for result in evaluation.match_results),
            "match_count": len(evaluation.match_results),
            "objectives": objectives_payload,
            "artifacts": {
                "game_performance": "evaluation/game_performance.json",
                "function_capability": "evaluation/function_capability.json",
                "strategy_alignment": "strategy_alignment/result.json",
                "code_quality": "evaluation/code_quality.json",
                "objectives": "evaluation/objectives.json",
                "timing": "timing.json",
            },
        },
    )
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
                "retained_matches": [match_to_dict(result) for result in evaluation.match_results],
            },
        )


def _write_generation_artifacts(candidate_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Persist the complete final Java-generation request and response envelope."""

    generation_dir = candidate_dir / "generation"
    generation_dir.mkdir(parents=True, exist_ok=True)
    request = evaluation.candidate.generation_input(class_name="CandidateAgent")
    result = evaluation.result
    (generation_dir / "request.txt").write_text(request, encoding="utf-8")
    (generation_dir / "response_raw.txt").write_text(result.raw_llm_output or "", encoding="utf-8")
    (generation_dir / "extracted_candidate.java").write_text(result.extracted_code or "", encoding="utf-8")
    (generation_dir / "normalized_candidate.java").write_text(
        result.assembled_java or evaluation.candidate.generated_java or "",
        encoding="utf-8",
    )
    write_json(generation_dir / "result.json", {
        "status": "success" if evaluation.agent is not None else "failed",
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
        "validation_result": validation_to_dict(result.validation_result),
        "stage": "generation",
        "llm_profile": (evaluation.generation_timing or {}).get("llm_profile"),
        "model": (evaluation.generation_timing or {}).get("model"),
        "attempts": (evaluation.generation_timing or {}).get("attempts", []),
    })


def _write_canonical_mutation_artifacts(candidate_dir: Path, mutation_record: dict) -> None:
    """Expose stage-independent names required by the mutation artifact schema."""

    mutation_dir = candidate_dir / "mutation"
    reflection = mutation_record.get("reflection") or {}
    if reflection:
        (mutation_dir / "reflection_request.txt").write_text(
            str(reflection.get("request") or ""), encoding="utf-8"
        )
        (mutation_dir / "reflection_response_raw.txt").write_text(
            str(reflection.get("raw_response") or ""), encoding="utf-8"
        )
    rewrite = mutation_record.get("rewrite")
    if rewrite:
        (mutation_dir / "rewrite_request.txt").write_text(
            str(rewrite.get("request") or ""), encoding="utf-8"
        )
        (mutation_dir / "rewrite_response_raw.txt").write_text(
            str(rewrite.get("raw_response") or ""), encoding="utf-8"
        )


def write_failed_candidate_debug(run_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Save raw stage outputs for a failed candidate."""

    debug_dir = run_dir / "failed_candidates" / evaluation.candidate.id
    debug_dir.mkdir(parents=True, exist_ok=True)
    result = evaluation.result
    (debug_dir / "raw_llm_output.txt").write_text(result.raw_llm_output or "", encoding="utf-8")
    (debug_dir / "extracted_code.java").write_text(result.extracted_code or "", encoding="utf-8")
    (debug_dir / "assembled_java.java").write_text(result.assembled_java or "", encoding="utf-8")
    write_json(debug_dir / "failure.json", {
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
        "validation_result": validation_to_dict(result.validation_result),
        "compile_result": compile_to_dict(result.compile_result),
        "strategy_region_validation": result.strategy_region_validation or {},
        "strategy_consistency": result.strategy_consistency,
        "code_quality": (result.final_score or {}).get("code_quality"),
        "code_quality_breakdown": result.code_quality_breakdown,
        "game_metrics": result.game_metrics,
    })


def write_resolved_config(run_dir: Path, config: ExperimentConfig, *, mock: bool, profiles: dict[str, LLMProfile] | None = None, stage_routing: dict[str, str] | None = None) -> None:
    """Write actual post-default and post-override runtime values."""

    llm_backend = "mock" if mock else config.generation_backend
    is_mock_backend = llm_backend == "mock"
    resolved_stage_routing = stage_routing or {"reflection": "reflector", "rewrite": "rewriter", "generation": "generator", "strategy_alignment": "reflector"}
    payload = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "objective_formula_version": OBJECTIVE_FORMULA_VERSION,
        "population_size": config.population_size,
        "generation_count": config.generations,
        "crossover_rate": config.crossover_rate,
        "mutation_rate": config.mutation_rate,
        "mutation_selection_policy": "failed_game_to_code_otherwise_seeded_random",
        "front0_stagnation_generations": config.front0_stagnation_generations,
        "matches_per_candidate": config.matches_per_candidate,
        "opponent": config.opponent,
        "evaluation_opponents": [item.__dict__ for item in EVALUATION_ROSTER],
        "objective_directions": OBJECTIVE_DIRECTIONS,
        "map": config.map_path,
        "max_cycles": config.tick_limit,
        "ea_random_seed": config.random_seed,
        "microrts_match_seeds": list(config.resolved_match_seeds),
        "match_timeout_seconds": config.match_timeout_seconds,
        "unit_material_values": dict(config.unit_material_values),
        "material_scale": config.material_scale,
        "resource_scale": config.resource_scale,
        "llm_backend": llm_backend,
        "llm_model": None if is_mock_backend else config.llm_model,
        "llm_temperature": None if is_mock_backend else 0.2,
        "retry_policy": {
            "max_attempts": 1 if is_mock_backend else 3,
            "mutation_max_attempts": config.mutation_max_attempts,
            "timeout_seconds": None if is_mock_backend else 120,
            "backoff": "none" if is_mock_backend else "exponential_seconds",
        },
        "strategy_alignment_backend": "mock" if mock else config.alignment_backend,
        "strategy_alignment_model": None if mock else config.llm_model,
        "endpoint_config_path": str(config.endpoint_config_path),
        "llm_role_topology_path": str(config.llm_role_topology_path),
        "llm_topology": config.llm_topology,
        "stage_routing": {
            stage: None if profiles is None else profiles[profile_name].to_dict()
            for stage, profile_name in resolved_stage_routing.items()
        },
        "prompt_version": None,
        "prompt_template_sha256": prompt_template_digest(),
        "git_commit_hash": git_commit_hash(),
        "unsupported": {
            "prompt_version": "Prompt content is snapshotted and hashed but has no semantic version label.",
        },
    }
    write_json(run_dir / "resolved_config.json", payload)


def write_prompt_snapshot(run_dir: Path, config: ExperimentConfig) -> None:
    """Persist the exact initial and meta-prompt inputs used by a run."""
    templates = load_prompt_templates(DEFAULT_PROMPT_TEMPLATE_PATH)
    write_json(run_dir / "prompt_snapshot.json", {
        "seed_prompts": list(config.seed_prompts),
        "generation_prompt": config.generation_prompt,
        "agent_template_path": str(config.agent_template_path),
        "agent_template_sha256": hashlib.sha256(config.agent_template_path.read_bytes()).hexdigest(),
        "meta_prompt_source": str(DEFAULT_PROMPT_TEMPLATE_PATH),
        "meta_prompt_sha256": prompt_template_digest(),
        "meta_prompts": {
            prompt_id: {
                "role": item.role,
                "stages": list(item.stages),
                "required_variables": list(item.required_variables),
                "template": item.template,
            }
            for prompt_id, item in templates.items()
        },
    })


def prompt_template_digest() -> str:
    return hashlib.sha256(DEFAULT_PROMPT_TEMPLATE_PATH.read_bytes()).hexdigest()


def git_commit_hash() -> str | None:
    """Return the checked-out commit or null when Git identity is unavailable."""

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def write_generation_manifest(run_dir: Path, generation: int, population: list[Candidate]) -> None:
    write_json(run_dir / f"generation_{generation:03d}_population.json", [candidate.to_json_dict() for candidate in population])


def write_summary(
    run_dir: Path,
    *,
    config: ExperimentConfig,
    final_population: list[Candidate],
    best_candidate: Candidate | None,
    pareto_fronts: list[list[Candidate]],
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
        "objectives": ["game_performance", "code_quality"],
        "best_candidate": None if best_candidate is None else best_candidate.to_json_dict(),
        "pareto_fronts": [[candidate.id for candidate in front] for front in pareto_fronts],
        "final_population": [candidate.to_json_dict() for candidate in final_population],
    })


def evaluation_to_dict(evaluation: CandidateEvaluation) -> dict:
    return {
        "candidate": evaluation.candidate.to_json_dict(),
        "candidate_result": candidate_result_to_dict(evaluation.result),
        "agent": None if evaluation.agent is None else {"class_name": evaluation.agent.class_name, "qualified_class_name": evaluation.agent.qualified_class_name, "source_path": str(evaluation.agent.source_path)},
        "compile": compile_to_dict(evaluation.compile_result),
        "integration": integration_to_dict(evaluation.integration_result),
        "matches": [match_to_dict(result) for result in evaluation.match_results],
        "game_metrics": evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else None,
        "code_quality": {"code_quality": evaluation.code_quality_breakdown.code_quality, "code_quality_breakdown": evaluation.code_quality_breakdown.to_json_dict()},
        "strategy_consistency": evaluation.strategy_consistency_result.to_json_dict() if evaluation.strategy_consistency_result else None,
        "function_capability": None if evaluation.function_capability_result is None else evaluation.function_capability_result.to_json_dict(),
        "strategy_alignment": None if evaluation.strategy_alignment_result is None else evaluation.strategy_alignment_result.to_json_dict(),
        "objectives": evaluation.candidate.fitness_objectives,
        "error": evaluation.error,
        "generation_timing": evaluation.generation_timing,
    }


def candidate_result_to_dict(result) -> dict:
    return {
        "candidate_id": result.candidate_id,
        "parent_ids": list(result.parent_ids),
        "raw_llm_output": result.raw_llm_output,
        "extracted_code": result.extracted_code,
        "assembled_java": result.assembled_java,
        "strategy_region": result.strategy_region,
        "validation_result": validation_to_dict(result.validation_result),
        "compile_result": compile_to_dict(result.compile_result),
        "strategy_region_validation": result.strategy_region_validation or {},
        "strategy_consistency": result.strategy_consistency,
        "code_quality": (result.final_score or {}).get("code_quality"),
        "function_capability": result.function_capability,
        "strategy_alignment": result.strategy_alignment,
        "code_quality_breakdown": result.code_quality_breakdown,
        "match_result": [match_to_dict(item) for item in result.match_result or []],
        "game_metrics": result.game_metrics,
        "final_score": result.final_score,
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
        "failure_stage": result.failure_stage,
        "integration_result": integration_to_dict(result.integration_result),
    }


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
