"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from evaluation.compiler import CompileResult
from evaluation.code_quality import analyze_compilation
from evaluation.microrts_runner import DEFAULT_MAP_PATH, MatchResult
from generation.java_agent_generator import ValidationResult

from .candidate import Candidate
from .config import ExperimentConfig

if TYPE_CHECKING:
    from .evaluation import CandidateEvaluation


ARTIFACT_SCHEMA_VERSION = "phase2a-v1"
OBJECTIVE_FORMULA_VERSION = "legacy-current-v1"


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
    generation_dir = candidate_dir / "generation"
    generation_dir.mkdir(exist_ok=True)
    (generation_dir / "normalized_candidate.java").write_text(evaluation.candidate.generated_java, encoding="utf-8")
    mutation_record = evaluation.candidate.metadata.get("mutation")
    if mutation_record is not None:
        write_json(candidate_dir / "mutation" / "metadata.json", mutation_record)
    write_json(candidate_dir / "timing.json", evaluation.candidate.timing)
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
    })
    write_json(candidate_dir / "objectives.json", evaluation.candidate.fitness_objectives)
    write_json(candidate_dir / "individual.json", evaluation.candidate.to_json_dict())
    write_json(candidate_dir / "candidate_result.json", candidate_result_to_dict(evaluation.result))
    write_json(candidate_dir / "result.json", candidate_result_to_dict(evaluation.result))
    if evaluation.result.failure_category is not None:
        write_failed_candidate_debug(candidates_dir.parent, evaluation)


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


def write_resolved_config(run_dir: Path, config: ExperimentConfig, *, mock: bool) -> None:
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
        "matches_per_candidate": config.matches_per_candidate,
        "opponent": config.opponent,
        "map": DEFAULT_MAP_PATH,
        "max_cycles": config.tick_limit,
        "ea_random_seed": config.random_seed,
        "microrts_match_seeds": None,
        "llm_backend": llm_backend,
        "llm_model": None if is_mock_backend else config.llm_model,
        "llm_temperature": None if is_mock_backend else 0.2,
        "retry_policy": {
            "max_attempts": 1 if is_mock_backend else 3,
            "mutation_max_attempts": config.mutation_max_attempts,
            "timeout_seconds": None if is_mock_backend else 120,
            "backoff": "none" if is_mock_backend else "exponential_seconds",
        },
        "prompt_version": None,
        "git_commit_hash": git_commit_hash(),
        "unsupported": {
            "microrts_match_seeds": "The current runner does not accept match seeds.",
            "prompt_version": "The current configurable generation prompt is not versioned.",
        },
    }
    write_json(run_dir / "resolved_config.json", payload)


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


def write_summary(run_dir: Path, *, config: ExperimentConfig, final_population: list[Candidate], best_candidate: Candidate | None, pareto_fronts: list[list[Candidate]], mock: bool) -> None:
    write_json(run_dir / "summary.json", {
        "mock": mock,
        "generations": config.generations,
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
        "matches": [match_to_dict(result) for result in evaluation.match_results],
        "game_metrics": evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else None,
        "code_quality": {"code_quality": evaluation.code_quality_breakdown.code_quality, "code_quality_breakdown": evaluation.code_quality_breakdown.to_json_dict()},
        "strategy_consistency": evaluation.strategy_consistency_result.to_json_dict() if evaluation.strategy_consistency_result else None,
        "objectives": evaluation.candidate.fitness_objectives,
        "error": evaluation.error,
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
        "code_quality_breakdown": result.code_quality_breakdown,
        "match_result": [match_to_dict(item) for item in result.match_result or []],
        "game_metrics": result.game_metrics,
        "final_score": result.final_score,
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
    }


def validation_to_dict(result: ValidationResult | None) -> dict | None:
    return None if result is None else {"ok": result.ok, "error": result.error}


def compile_to_dict(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    return {"ok": result.ok, "status": result.status, "command": result.command, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode, **analyze_compilation(result).to_json_dict()}


def match_to_dict(result: MatchResult) -> dict:
    return {
        "ok": result.ok,
        "score": result.score,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "player0_resource": result.player0_resource,
        "player1_resource": result.player1_resource,
        "weighted_resource_difference": result.weighted_resource_difference,
        "winner": result.winner,
        "final_cycle": result.final_cycle,
        "performance_breakdown": None if result.performance_breakdown is None else result.performance_breakdown.to_json_dict(),
        "replay_path": result.replay_path,
        "telemetry_path": result.telemetry_path,
        "summary_path": result.summary_path,
        "persistence_error": result.persistence_error,
        "raw_result": result.raw_result,
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
