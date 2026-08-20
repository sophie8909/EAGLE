"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

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
    from .evaluation import CandidateEvaluation


# Writers are grouped by lifecycle boundary: genotype inputs first,
# stage/evaluation evidence next, and run summaries/configuration last.
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
    write_candidate_snapshot(candidates_dir, evaluation.candidate)


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
        "operation": (evaluation.generation_timing or {}).get("operation"),
        "model": (evaluation.generation_timing or {}).get("model"),
        "attempts": (evaluation.generation_timing or {}).get("attempts", []),
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
    payload = {
        "candidate_schema_version": "eagle-candidate-v3",
        "candidate_id": candidate.id,
        "generation": candidate.generation,
        "parent_ids": list(candidate.parent_ids),
        "operator": candidate.operator,
        "mutation_type": candidate.mutation_type,
        "strategy_parent_id": candidate.strategy_parent_id,
        "previous_code_parent_id": candidate.previous_code_parent_id,
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
        "artifacts": {
            "lineage": "lineage.json",
            "strategy_prompt": "genotype/strategy_prompt.txt",
            "previous_code": "genotype/previous_code.java",
            "generation_prompt": "genotype/generation_prompt.txt",
            "generated_java": "generation/normalized_candidate.java",
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
        },
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
