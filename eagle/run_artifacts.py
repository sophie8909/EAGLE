"""Compact canonical run and per-generation artifacts."""
from __future__ import annotations

import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.objectives import OBJECTIVE_DIRECTIONS
from eagle.opponent_cases import FAILED_OPPONENT_SCORE

from .candidate import Candidate
from .config import ExperimentConfig

RUN_SCHEMA_VERSION = "eagle-run-v2"
GENERATION_SCHEMA_VERSION = "eagle-generation-v3"
ERROR_MEMORY_SCHEMA_VERSION = "eagle-error-memory-v1"
GENERATION_POLICY_SCHEMA_VERSION = "eagle-generation-policy-v2"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_run_manifest(run_dir: Path, *, config: ExperimentConfig) -> None:
    for name in (
        "generations", "candidates", "generated_agents", "classes", "archives",
        "llm_logs", "final_test",
    ):
        directory = run_dir / name
        directory.mkdir(parents=True, exist_ok=True)
    (run_dir / "timing.jsonl").touch(exist_ok=True)

    atomic_json(
        run_dir / "manifest.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_dir.name,
            "created_at": utc_now(),
            "status": "initialized",
            "experiment_name": config.experiment_name,
            "model_name": config.model.name,
            "reflection_operator_mode": config.reflection_operator_mode.value,
            "latest_generation": None,
            "updated_at": utc_now(),
        },
    )


def mark_run_interrupted(run_dir: Path) -> None:
    """Mark a run resumable after Ctrl-C without inventing a population snapshot."""

    manifest = load_manifest(run_dir)
    if manifest.get("status") == "complete":
        return
    completed = manifest.get("latest_generation")
    manifest.update(
        status="interrupted",
        resumable=completed is not None,
        interrupted_at=utc_now(),
        updated_at=utc_now(),
    )
    atomic_json(run_dir / "manifest.json", manifest)


def mark_run_failed(run_dir: Path, error: BaseException) -> None:
    """Close a non-complete run after an exception without losing resume state."""

    manifest = load_manifest(run_dir)
    if manifest.get("status") == "complete":
        return
    completed = manifest.get("latest_generation")
    manifest.update(
        status="failed",
        resumable=completed is not None,
        failure_type=type(error).__name__,
        failure_reason=str(error) or type(error).__name__,
        failed_at=utc_now(),
        updated_at=utc_now(),
    )
    atomic_json(run_dir / "manifest.json", manifest)


def record_error_memory(run_dir: Path, candidates: list[Candidate]) -> tuple[dict[str, object], ...]:
    """Merge bounded failure signatures into the canonical archive."""
    path = run_dir / "archives" / "error_memory.jsonl"
    records: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            signature = str(payload.get("signature") or "")
            if signature:
                records[signature] = payload
    changed = False
    for candidate in candidates:
        if candidate.status != "failed" and not candidate.failure_reason and not candidate.failure_stage:
            continue
        category = _error_category(candidate)
        message = normalize_error_message(candidate.failure_reason or candidate.metadata.get("failure_reason") or candidate.failure_stage or "unknown failure")
        signature = f"{category}:{message}"
        item = records.get(signature)
        if item is None:
            records[signature] = {
                "schema_version": ERROR_MEMORY_SCHEMA_VERSION,
                "signature": signature,
                "category": category,
                "normalized_message": message,
                "count": 1,
                "representative_candidate_id": candidate.id,
                "representative_generation": candidate.generation,
            }
        else:
            item["count"] = int(item.get("count") or 0) + 1
        changed = True
    if changed:
        atomic_jsonl(path, sorted(records.values(), key=lambda item: (-int(item.get("count") or 0), str(item.get("signature")))))
    return load_error_memory(run_dir)


def load_error_memory(run_dir: Path, *, limit: int = 3) -> tuple[dict[str, object], ...]:
    path = run_dir / "archives" / "error_memory.jsonl"
    if not path.exists():
        return ()
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    records.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("signature") or "")))
    return tuple(dict(item) for item in records[:limit])


def normalize_error_message(value: object) -> str:
    text = re.sub(r"(?:[A-Za-z]:)?[/\\][^\s:]+", "<path>", str(value))
    text = re.sub(r"\bline\s+\d+\b|:\d+(?::\d+)?", ":<line>", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()[:600]


def _error_category(candidate: Candidate) -> str:
    stage = str(candidate.failure_stage or candidate.metadata.get("failure_category") or "").lower()
    reason = str(candidate.failure_reason or "").lower()
    if "timeout" in stage or "timeout" in reason:
        return "timeout"
    if "backend" in stage or "llm" in stage or "backend" in reason:
        return "backend_failure"
    if "runtime" in stage:
        return "runtime_failure"
    if "compile" in stage or "compil" in stage or "javac" in reason:
        return "compile_failure"
    if "valid" in stage:
        return "validation_failure"
    return "generation_failure"


def record_generation(
    run_dir: Path,
    generation: int,
    population: list[Candidate],
    *,
    diversity: dict[str, Any] | None = None,
    aos: dict[str, Any] | None = None,
) -> None:
    """Record the surviving population after selection exactly once."""
    metrics = generation_metrics(generation, population, diversity=diversity)
    snapshot = {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "generation": generation,
        "population": [
            {
                "candidate_id": candidate.id,
                "fitness_objectives": dict(candidate.fitness_objectives),
                "status": candidate.status,
            }
            for candidate in population
        ],
        "best_candidate_id": _best_candidate_id(population),
        "metrics": metrics,
        "aos": None if aos is None else dict(aos),
        "timing": {
            "artifact": "../timing.jsonl",
            "event_type": "generation",
            "generation": generation,
        },
    }
    generations_dir = run_dir / "generations"
    generations_dir.mkdir(parents=True, exist_ok=True)
    policy_index_path = generations_dir / f"generation_{generation:04d}_policies.jsonl"
    atomic_jsonl(
        policy_index_path,
        generation_policy_records(run_dir, generation, population),
    )
    snapshot_path = generations_dir / f"generation_{generation:04d}.json"
    atomic_json(snapshot_path, snapshot)
    manifest = load_manifest(run_dir)
    manifest.update(
        status="running",
        latest_generation=generation,
        updated_at=utc_now(),
    )
    atomic_json(run_dir / "manifest.json", manifest)


def generation_policy_records(
    run_dir: Path,
    generation: int,
    population: list[Candidate],
) -> list[dict[str, Any]]:
    """Build stable references to every current population strategy prompt."""

    records: list[dict[str, Any]] = []
    for candidate in population:
        if not candidate.strategy_prompt.strip():
            continue
        record: dict[str, Any] = {
            "schema_version": GENERATION_POLICY_SCHEMA_VERSION,
            "generation": generation,
            "candidate_id": candidate.id,
            "strategy_parent_id": candidate.strategy_parent_id,
            "operator": candidate.operator,
            "mutation_type": candidate.mutation_type,
            "policy_prompt_artifact": (
                f"candidates/{candidate.id}/genotype/policy_prompt.txt"
            ),
        }
        if candidate.strategy_parent_id is not None:
            record["parent_policy_prompt_artifact"] = (
                "candidates/"
                f"{candidate.strategy_parent_id}/genotype/policy_prompt.txt"
            )
        reflection_metadata = (
            run_dir / "candidates" / candidate.id / "mutation" / "strategy_reflection" / "metadata.json"
        )
        if reflection_metadata.is_file():
            record["strategy_reflection_artifact"] = (
                f"candidates/{candidate.id}/mutation/strategy_reflection/metadata.json"
            )
        balance_metadata = (
            run_dir / "candidates" / candidate.id / "mutation" / "balance_reflection" / "metadata.json"
        )
        if balance_metadata.is_file():
            record["balance_reflection_artifact"] = (
                f"candidates/{candidate.id}/mutation/balance_reflection/metadata.json"
            )
        records.append(record)
    return records


def finalize_run(run_dir: Path, population: list[Candidate], *, stop_reason: str | None) -> None:
    manifest = load_manifest(run_dir)
    manifest.update(status="complete", stop_reason=stop_reason, updated_at=utc_now())
    atomic_json(run_dir / "manifest.json", manifest)


def generation_metrics(
    generation: int,
    population: list[Candidate],
    *,
    diversity: dict[str, Any] | None = None,
    aos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    objectives: dict[str, Any] = {}
    opponent_by_candidate: dict[str, Any] = {}
    opponent_values: dict[str, list[float]] = {}
    opponent_failures: dict[str, int] = {}
    for objective_id, direction in OBJECTIVE_DIRECTIONS.items():
        values = [
            float(candidate.fitness_objectives[objective_id])
            for candidate in population
            if objective_id in candidate.fitness_objectives
            and math.isfinite(float(candidate.fitness_objectives[objective_id]))
            and candidate.status != "failed"
            and candidate.failure_reason is None
            and float(candidate.fitness_objectives[objective_id]) != FAILED_OPPONENT_SCORE
        ]
        missing = sum(objective_id not in candidate.fitness_objectives for candidate in population)
        failures = sum(
            candidate.status == "failed"
            or candidate.failure_reason is not None
            or candidate.fitness_objectives.get(objective_id) == FAILED_OPPONENT_SCORE
            for candidate in population
        )
        if values:
            objectives[objective_id] = {
                "objective_id": objective_id,
                "direction": direction,
                "best": max(values) if direction == "maximize" else min(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "worst": min(values) if direction == "maximize" else max(values),
                "minimum": min(values),
                "maximum": max(values),
                "standard_deviation": statistics.pstdev(values),
                "valid_count": len(values),
                "missing_count": missing,
                "failure_count": failures,
            }
        else:
            objectives[objective_id] = {
                "objective_id": objective_id,
                "direction": direction,
                "best": None, "mean": None, "median": None, "worst": None,
                "minimum": None, "maximum": None, "standard_deviation": None,
                "valid_count": 0, "missing_count": missing, "failure_count": failures,
            }
    for candidate in population:
        game = candidate.game_eval_result or {}
        results = game.get("opponent_results") or []
        if isinstance(results, list) and results:
            rows = [item for item in results if isinstance(item, dict)]
            scores = [float(item.get("score") or 0.0) for item in rows]
            best = max(rows, key=lambda item: float(item.get("score") or 0.0)) if rows else None
            worst = min(rows, key=lambda item: float(item.get("score") or 0.0)) if rows else None
            opponent_by_candidate[candidate.id] = {
                "aggregate_game_performance": game.get("game_performance"),
                "expected_match_count": game.get("expected_match_count"),
                "completed_match_count": game.get("completed_match_count"),
                "evaluation_maps": game.get("evaluation_maps"),
                "rounds_per_map": game.get("rounds_per_map"),
                "swap_player_sides": game.get("swap_player_sides"),
                "opponent_scores": {str(item.get("opponent_id") or "unknown"): float(item.get("score") or 0.0) for item in rows},
                "fixed_weight_sum": game.get("fixed_weight_sum"),
                "total_weight": game.get("total_weight"),
                "weighted_numerator": game.get("weighted_numerator"),
                "opponent_results": rows,
                "best_matchup": None if best is None else {
                    "opponent_id": best.get("opponent_id"), "score": best.get("score")
                },
                "worst_matchup": None if worst is None else {
                    "opponent_id": worst.get("opponent_id"), "score": worst.get("score")
                },
            }
            for item in rows:
                opponent_id = str(item.get("opponent_id") or "unknown")
                opponent_values.setdefault(opponent_id, []).append(float(item.get("score") or 0.0))
                if item.get("status") != "completed" or float(item.get("score") or 0.0) == FAILED_OPPONENT_SCORE:
                    opponent_failures[opponent_id] = opponent_failures.get(opponent_id, 0) + 1
        else:
            # Older generation snapshots remain valid; they simply have no detail.
            opponent_by_candidate.setdefault(candidate.id, {
                "aggregate_game_performance": game.get("game_performance"),
                "opponent_scores": dict(game.get("opponent_scores") or {}),
                "best_matchup": None,
                "worst_matchup": None,
            })
    opponent_summary = {
        opponent_id: {
            "game_performance": statistics.fmean(scores),
            "mean_score": statistics.fmean(scores),
            "failure_count": opponent_failures.get(opponent_id, 0),
            "sample_count": len(scores),
        }
        for opponent_id, scores in sorted(opponent_values.items())
    }
    first_game = next(
        (candidate.game_eval_result or {} for candidate in population if candidate.game_eval_result),
        {},
    )
    expected_match_count = sum(
        int((candidate.game_eval_result or {}).get("expected_match_count") or 0)
        for candidate in population
    )
    completed_match_count = sum(
        int((candidate.game_eval_result or {}).get("completed_match_count") or 0)
        for candidate in population
    )
    aggregate_values = [
        float((candidate.game_eval_result or {}).get("game_performance"))
        for candidate in population
        if (candidate.game_eval_result or {}).get("game_performance") is not None
    ]
    quality_values = [
        float((candidate.code_quality_result or {}).get("code_quality"))
        for candidate in population
        if (candidate.code_quality_result or {}).get("code_quality") is not None
    ]

    def summary(values: list[float]) -> dict[str, Any]:
        return {
            "best": max(values) if values else None,
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "worst": min(values) if values else None,
            "count": len(values),
        }

    light_rush_wins = sum(_candidate_beats_opponent(candidate, "lightrush") for candidate in population)
    heavy_rush_wins = sum(_candidate_beats_opponent(candidate, "heavyrush") for candidate in population)
    population_size = len(population)

    payload = {
        "schema_version": "eagle-generation-metrics-v1",
        "generation": generation,
        "population_size": population_size,
        "light_rush_win_rate": light_rush_wins / population_size if population_size else 0.0,
        "heavy_rush_win_rate": heavy_rush_wins / population_size if population_size else 0.0,
        "fixed_weight_sum": first_game.get("fixed_weight_sum"),
        "total_weight": first_game.get("total_weight"),
        "weighted_numerator": first_game.get("weighted_numerator"),
        "expected_match_count": expected_match_count,
        "completed_match_count": completed_match_count,
        "evaluation_maps": first_game.get("evaluation_maps"),
        "rounds_per_map": first_game.get("rounds_per_map"),
        "swap_player_sides": first_game.get("swap_player_sides"),
        "failure_count": sum(candidate.status == "failed" or candidate.failure_reason is not None for candidate in population),
        "objectives": objectives,
        "game_performance": summary(aggregate_values),
        "code_quality_diagnostic": summary(quality_values),
        "opponent_scores": {
            "by_candidate": opponent_by_candidate,
            "by_opponent": opponent_summary,
        },
    }
    if diversity is not None:
        payload["strategy_diversity"] = dict(diversity)
    if aos is not None:
        payload["aos"] = dict(aos)
    return payload


def load_aos_state(run_dir: Path) -> dict[str, Any] | None:
    """Load the latest persisted AOS state for deterministic resume."""

    generations = sorted((run_dir / "generations").glob("generation_*.json"))
    if not generations:
        return None
    payload = json.loads(generations[-1].read_text(encoding="utf-8"))
    aos = payload.get("aos") or (payload.get("metrics") or {}).get("aos")
    return dict(aos["state"]) if isinstance(aos, dict) and isinstance(aos.get("state"), dict) else None


def _candidate_beats_opponent(candidate: Candidate, opponent_id: str) -> bool:
    """Return whether the canonical opponent-level result is a winning record."""

    game = candidate.game_eval_result or {}
    rows = game.get("opponent_results") or []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("opponent_id") or "") != opponent_id:
            continue
        if str(row.get("status") or "").lower() != "completed":
            return False
        try:
            return int(row.get("wins") or 0) > int(row.get("losses") or 0)
        except (TypeError, ValueError):
            return False
    return False


def load_resume_population(run_dir: Path) -> tuple[int, list[Candidate]]:
    manifest = load_manifest(run_dir)
    latest = manifest.get("latest_generation")
    if latest is None:
        raise ValueError(f"Run has no completed generation to resume: {run_dir}")
    generation = int(latest)
    path = run_dir / "generations" / f"generation_{generation:04d}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    population = payload.get("population")
    if not isinstance(population, list):
        raise ValueError(f"Invalid generation snapshot: {path}")
    candidates = []
    for item in population:
        candidate_id = str(item.get("candidate_id") or item.get("id") or "")
        if not candidate_id:
            raise ValueError(f"Generation snapshot contains an invalid candidate reference: {path}")
        candidates.append(load_candidate(run_dir, candidate_id))
    return generation, candidates


def load_candidate(run_dir: Path, candidate_id: str) -> Candidate:
    candidate_dir = run_dir / "candidates" / candidate_id
    path = candidate_dir / "candidate.json"
    if not path.is_file():
        raise ValueError(f"Candidate snapshot is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))

    def text(relative: str) -> str:
        target = candidate_dir / relative
        return target.read_text(encoding="utf-8") if target.is_file() else ""

    def object_json(relative: str) -> dict[str, Any]:
        target = candidate_dir / relative
        if not target.is_file():
            return {}
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}

    artifact_refs = payload.get("artifacts") or {}
    failed_source_is_evidence_only = "failed_generation_source" in artifact_refs
    phenotype_path = candidate_dir / "phenotype" / "CandidateAgent.java"
    legacy_generation_path = candidate_dir / "generation" / "normalized_candidate.java"

    return Candidate(
        id=candidate_id,
        generation=int(payload.get("generation") or 0),
        parent_ids=tuple(payload.get("parent_ids") or ()),
        strategy_prompt=(
            text("genotype/policy_prompt.txt")
            or text("genotype/strategy_prompt.txt")
        ),
        generation_prompt=(
            text("genotype/code_generation_prompt.txt")
            or text("genotype/generation_prompt.txt")
        ),
        inherited_java=text("genotype/inherited_java.java"),
        java_parent_id=payload.get("java_parent_id"),
        generated_java=(
            text("phenotype/CandidateAgent.java")
            or (
                ""
                if failed_source_is_evidence_only
                else text("generation/normalized_candidate.java")
            )
        ),
        generated_java_path=(
            str(phenotype_path)
            if phenotype_path.is_file()
            else None
            if failed_source_is_evidence_only
            else str(legacy_generation_path)
        ),
        operator=str(payload.get("operator") or "seed"),
        mutation_type=payload.get("mutation_type"),
        strategy_parent_id=payload.get("strategy_parent_id"),
        generation_prompt_parent_id=payload.get("generation_prompt_parent_id"),
        source_candidate_ids=tuple(payload.get("source_candidate_ids") or ()),
        compile_status=str(payload.get("compile_status") or "pending"),
        game_eval_result=object_json("evaluation/game_performance.json"),
        code_quality_result=object_json("evaluation/code_quality.json"),
        fitness_objectives={str(k): float(v) for k, v in (payload.get("fitness_objectives") or {}).items()},
        strategy_signature=dict(payload.get("strategy_signature") or {}),
        strategy_niche=str(payload.get("strategy_niche") or "unknown"),
        mutation_intent=payload.get("mutation_intent"),
        parent_strategy_niche=payload.get("parent_strategy_niche"),
        niche_changed=payload.get("niche_changed"),
        status=str(payload.get("status") or "pending"),
        failure_stage=payload.get("failure_stage"),
        failure_reason=payload.get("failure_reason"),
        artifacts=dict(payload.get("artifacts") or {}),
        timing=object_json("timing.json"),
        metadata=dict(payload.get("metadata") or {}),
    )


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Unsupported run manifest schema in {path}.")
    return payload


def _best_candidate_id(population: list[Candidate]) -> str | None:
    valid = [candidate for candidate in population if candidate.status != "failed"]
    if not valid:
        return None
    return max(valid, key=lambda item: tuple(item.objective_vector())).id


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    temporary.replace(path)
