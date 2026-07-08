"""Run artifact writers for EAGLE searches."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from evaluation.compiler import CompileResult
from evaluation.microrts_runner import MatchResult
from generation.java_agent_generator import ValidationResult

from .candidate import Candidate
from .config import ExperimentConfig

if TYPE_CHECKING:
    from .evaluation import CandidateEvaluation


def append_result(path: Path, evaluation: CandidateEvaluation) -> None:
    """Append one evaluated candidate record to results.jsonl."""

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evaluation_to_dict(evaluation), ensure_ascii=False))
        handle.write("\n")


def write_candidate_artifacts(candidates_dir: Path, evaluation: CandidateEvaluation) -> None:
    """Save the per-candidate prompt, Java source, metrics, and objective files."""

    candidate_dir = candidates_dir / evaluation.candidate.id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    (candidate_dir / "strategy_prompt.txt").write_text(evaluation.candidate.strategy_prompt, encoding="utf-8")
    (candidate_dir / "previous_code.java").write_text(evaluation.candidate.previous_code, encoding="utf-8")
    (candidate_dir / "generation_prompt.txt").write_text(evaluation.candidate.generation_prompt, encoding="utf-8")
    if evaluation.agent is not None:
        (candidate_dir / "generated_java_source.java").write_text(evaluation.agent.source, encoding="utf-8")
    write_json(candidate_dir / "compile_result.json", compile_to_dict(evaluation.compile_result))
    write_json(candidate_dir / "raw_microrts_result.json", [match_to_dict(result) for result in evaluation.match_results])
    write_json(
        candidate_dir / "game_metrics.json",
        evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else {},
    )
    write_json(
        candidate_dir / "strategy_alignment.json",
        evaluation.alignment_result.to_json_dict() if evaluation.alignment_result else {},
    )
    write_json(candidate_dir / "objectives.json", evaluation.candidate.fitness_objectives)
    write_json(candidate_dir / "individual.json", evaluation.candidate.to_json_dict())
    write_json(candidate_dir / "candidate_result.json", candidate_result_to_dict(evaluation.result))
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
    write_json(
        debug_dir / "failure.json",
        {
            "failure_category": result.failure_category,
            "failure_reason": result.failure_reason,
            "validation_result": validation_to_dict(result.validation_result),
            "compile_result": compile_to_dict(result.compile_result),
            "game_metrics": result.game_metrics,
        },
    )


def write_generation_manifest(run_dir: Path, generation: int, population: list[Candidate]) -> None:
    """Save the selected population for one generation."""

    payload = [candidate.to_json_dict() for candidate in population]
    write_json(run_dir / f"generation_{generation:03d}_population.json", payload)


def write_summary(
    run_dir: Path,
    *,
    config: ExperimentConfig,
    final_population: list[Candidate],
    best_candidate: Candidate | None,
    pareto_fronts: list[list[Candidate]],
    mock: bool,
) -> None:
    """Save the final run summary and Pareto front membership."""

    payload = {
        "mock": mock,
        "generations": config.generations,
        "population_size": config.population_size,
        "objectives": ["game_performance", "strategy_alignment", "prompt_length"],
        "best_candidate": None if best_candidate is None else best_candidate.to_json_dict(),
        "pareto_fronts": [[candidate.id for candidate in front] for front in pareto_fronts],
        "final_population": [candidate.to_json_dict() for candidate in final_population],
    }
    write_json(run_dir / "summary.json", payload)


def evaluation_to_dict(evaluation: CandidateEvaluation) -> dict:
    return {
        "candidate": evaluation.candidate.to_json_dict(),
        "candidate_result": candidate_result_to_dict(evaluation.result),
        "agent": None
        if evaluation.agent is None
        else {
            "class_name": evaluation.agent.class_name,
            "qualified_class_name": evaluation.agent.qualified_class_name,
            "source_path": str(evaluation.agent.source_path),
        },
        "compile": compile_to_dict(evaluation.compile_result),
        "matches": [match_to_dict(result) for result in evaluation.match_results],
        "game_metrics": evaluation.game_metrics.to_json_dict() if evaluation.game_metrics else None,
        "strategy_alignment": evaluation.alignment_result.to_json_dict() if evaluation.alignment_result else None,
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
        "validation_result": validation_to_dict(result.validation_result),
        "compile_result": compile_to_dict(result.compile_result),
        "match_result": [match_to_dict(item) for item in result.match_result or []],
        "game_metrics": result.game_metrics,
        "final_score": result.final_score,
        "failure_category": result.failure_category,
        "failure_reason": result.failure_reason,
    }


def validation_to_dict(result: ValidationResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "error": result.error,
    }


def compile_to_dict(result: CompileResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "ok": result.ok,
        "status": result.status,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def match_to_dict(result: MatchResult) -> dict:
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
