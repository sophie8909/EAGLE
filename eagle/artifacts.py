"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from evaluation.compiler import CompileResult
from evaluation.code_quality import OBJECTIVE_FORMULA_VERSION, analyze_compilation
from evaluation.nsga2_objectives import OBJECTIVE_DIRECTIONS
from evaluation.microrts_runner import DEFAULT_MAP_PATH, INTEGRATION_CHECK_NAMES, IntegrationResult, MatchResult
from generation.java_agent_generator import ValidationResult

from .candidate import Candidate
from .opponents import EVALUATION_ROSTER, SEARCH_OPPONENT_REGISTRY
from .llm_profiles import LLMClient
from .prompts import DEFAULT_PROMPT_TEMPLATE_PATH, load_prompt_templates
from .config import ExperimentConfig

if TYPE_CHECKING:
    from .evaluation import CandidateEvaluation


ARTIFACT_SCHEMA_VERSION = "phase4-v3"


def write_candidate_inputs(candidates_dir: Path, candidate: Candidate) -> None:
    """Persist lineage and the pre-generation genotype before external work."""

    candidate_dir = candidates_dir / candidate.id
    genotype_dir = candidate_dir / "genotype"
    genotype_dir.mkdir(parents=True, exist_ok=True)
    (genotype_dir / "strategy_prompt.txt").write_text(candidate.strategy_prompt, encoding="utf-8")
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
                "candidate_id": candidate.id,
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
        mutation_path = candidate_dir / "mutation" / "metadata.json"
        if not mutation_path.exists():
            write_json(mutation_path, mutation_record)
            _write_mutation_artifacts(candidate_dir, mutation_record)
    write_json(candidate_dir / "timing.json", evaluation.candidate.timing)
    _write_evaluation_artifacts(candidate_dir, evaluation)
    write_json(candidate_dir / "individual.json", evaluation.candidate.to_individual_dict())
    write_json(candidate_dir / "candidate_result.json", candidate_result_to_dict(evaluation))


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
            "reason": "Strategy Alignment runs only after the complete evaluation matrix.",
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
        "game_performance": evaluation.candidate.fitness_objectives["game_performance"],
        "code_quality": evaluation.candidate.fitness_objectives["code_quality"],
        "opponent_scores": list(game_payload.get("opponent_scores") or []),
        "opponent_results": list(game_payload.get("opponent_results") or []),
        "objective_names": ["game_performance", "code_quality"],
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
    write_json(evaluation_dir / "matches.json", [match_to_dict(result) for result in evaluation.match_results])
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
            "expected_match_count": game_payload.get("expected_match_count"),
            "missing_match_count": max(0, int(game_payload.get("expected_match_count") or 0) - sum(result.ok for result in evaluation.match_results)),
            "opponent_scores": list(game_payload.get("opponent_scores") or []),
            "opponent_results": list(game_payload.get("opponent_results") or []),
            "objectives": objectives_payload,
            "artifacts": {
                "game_performance": "evaluation/game_performance.json",
                "commentary_aggregation": "evaluation/commentary_aggregation.json",
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

    mutation_dir = candidate_dir / "mutation"
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


def write_resolved_config(run_dir: Path, config: ExperimentConfig, *, mock: bool, client: LLMClient | None = None) -> None:
    """Write actual post-default and post-override runtime values."""

    llm_backend = "mock" if mock else config.generation_backend
    is_mock_backend = llm_backend == "mock"
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
        "matches_per_opponent": config.fixed_matches_per_opponent,
        "fixed_matches_per_candidate": config.expected_match_count,
        "dynamic_eagle_matches_from_generation": config.fixed_matches_per_opponent,
        "opponent": config.opponent,
        "evaluation_opponents": [
            {
                "order": order,
                "opponent_id": opponent_id,
                "weight": weight,
                "class_name": next(item.class_name for item in SEARCH_OPPONENT_REGISTRY if item.opponent_id == opponent_id),
            }
            for order, (opponent_id, weight) in enumerate(config.evaluation_opponents, start=1)
        ],
        "fixed_opponent_weight_sum": config.fixed_opponent_weight_sum,
        "eagle_opponent": {
            "enabled": config.eagle_opponent_enabled,
            "source": config.eagle_opponent_source,
            "schedule": config.eagle_opponent_schedule,
            "min_weight": config.eagle_opponent_min_weight,
            "max_weight": config.eagle_opponent_max_weight,
        },
        "objective_directions": OBJECTIVE_DIRECTIONS,
        "map": config.map_path,
        "evaluation_maps": [
            {"map_id": f"map_{index}", "path": path}
            for index, path in enumerate(config.evaluation_maps, start=1)
        ],
        "rounds_per_map": config.rounds_per_map,
        "swap_player_sides": config.swap_player_sides,
        "matrix_order": "opponent-major, map-major, round-major, candidate-player-0-then-1",
        "max_cycles": config.tick_limit,
        "ea_random_seed": config.random_seed,
        "microrts_match_seeds": list(config.resolved_match_seeds),
        "round_seed_schedule": list(config.resolved_match_seeds),
        "eagle_match_seed_policy": "dynamic and historical opponents reuse the canonical round seed schedule",
        "match_timeout_seconds": config.match_timeout_seconds,
        "match_artifact_mode": config.match_artifact_mode,
        "unit_material_values": dict(config.unit_material_values),
        "material_scale": config.material_scale,
        "resource_scale": config.resource_scale,
        "llm_backend": llm_backend,
        "llm_model": None if is_mock_backend else config.llm_model,
        "llm_temperature": None if is_mock_backend else 0.2,
        "llm_roles": {role: {"enabled": enabled, "temperature": temperature} for role, enabled, temperature in config.llm_roles},
        "retry_policy": {
            "max_attempts": 1 if is_mock_backend else 3,
            "mutation_max_attempts": config.mutation_max_attempts,
            "timeout_seconds": None if is_mock_backend else 120,
            "backoff": "none" if is_mock_backend else "exponential_seconds",
        },
        "strategy_alignment_backend": "mock" if mock else config.alignment_backend,
        "strategy_alignment_model": None if mock else config.llm_model,
        "llm": None if client is None else {
            "model": client.model,
            "base_url": client.base_url,
            "timeout_seconds": client.timeout_seconds,
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
        "best_candidate": None if best_candidate is None else best_candidate.to_summary_dict(),
        "pareto_fronts": [[candidate.id for candidate in front] for front in pareto_fronts],
        "final_population": [candidate.to_summary_dict() for candidate in final_population],
    })


def candidate_result_to_dict(evaluation: CandidateEvaluation) -> dict:
    result = evaluation.result
    game_metrics = evaluation.game_metrics
    return {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "objective_formula_version": OBJECTIVE_FORMULA_VERSION,
        "candidate_id": result.candidate_id,
        "generation": evaluation.candidate.generation,
        "parent_ids": list(result.parent_ids),
        "status": evaluation.candidate.status,
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
        "failure_stage": result.failure_stage,
        "objectives": dict(result.final_score or {}),
        "completed_match_count": 0 if game_metrics is None else game_metrics.completed_match_count,
        "attempted_match_count": len(evaluation.match_results),
        "expected_match_count": None if game_metrics is None else game_metrics.expected_match_count,
        "artifacts": {
            "lineage": "lineage.json",
            "genotype": "genotype/",
            "generation": "generation/result.json",
            "validation": "validation/validation_result.json",
            "compilation": "compilation/compilation_result.json",
            "integration": "integration/integration_result.json",
            "matches": "evaluation/matches.json",
            "game_performance": "evaluation/game_performance.json",
            "code_quality": "evaluation/code_quality.json",
            "objectives": "evaluation/objectives.json",
            "timing": "timing.json",
        },
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
