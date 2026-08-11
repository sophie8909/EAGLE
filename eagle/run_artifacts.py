"""Compact canonical run and per-generation artifacts."""
from __future__ import annotations

import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE, OBJECTIVE_DIRECTIONS

from .candidate import Candidate

from .selection import assign_rank_and_crowding
RUN_SCHEMA_VERSION = "eagle-run-v1"
GENERATION_SCHEMA_VERSION = "eagle-generation-v2"
ERROR_MEMORY_SCHEMA_VERSION = "eagle-error-memory-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_run_manifest(run_dir: Path, *, config_path: Path) -> None:
    for directory in (run_dir / "generations",):
        directory.mkdir(parents=True, exist_ok=True)
    for artifact in (run_dir / "generation_metrics.jsonl", run_dir / "errors.jsonl"):
        artifact.touch(exist_ok=True)

    atomic_json(
        run_dir / "manifest.json",
        {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_dir.name,
            "status": "initialized",
            "configuration": "resolved_config.json",
            "source_config": str(config_path.resolve()),
            "completed_generations": [],
            "last_update_time": utc_now(),
        },
    )


def record_error_memory(run_dir: Path, candidates: list[Candidate]) -> tuple[dict[str, object], ...]:
    """Merge bounded failure signatures from evaluated candidates into errors.jsonl."""
    path = run_dir / "errors.jsonl"
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
    path = run_dir / "errors.jsonl"
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
) -> None:
    """Record the surviving population after selection exactly once."""
    snapshot = {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "generation": generation,
        "population": [candidate.to_json_dict() for candidate in population],
    }
    generations_dir = run_dir / "generations"
    generations_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = generations_dir / f"generation_{generation:04d}.json"
    atomic_json(snapshot_path, snapshot)
    metrics = generation_metrics(generation, population, diversity=diversity)
    metrics_path = run_dir / "generation_metrics.jsonl"
    existing = _jsonl_by_key(metrics_path, "generation")
    existing[generation] = metrics
    atomic_jsonl(metrics_path, [existing[key] for key in sorted(existing)])
    manifest = load_manifest(run_dir)
    completed = sorted({int(value) for value in manifest.get("completed_generations", [])} | {generation})
    manifest.update(
        status="running",
        completed_generations=completed,
        last_completed_generation=max(completed),
        last_update_time=utc_now(),
    )
    atomic_json(run_dir / "manifest.json", manifest)


def finalize_run(run_dir: Path, population: list[Candidate], *, stop_reason: str | None) -> None:
    atomic_json(
        run_dir / "final_population.json",
        {
            "schema_version": "eagle-final-population-v2",
            "population": [candidate.to_json_dict() for candidate in population],
        },
    )
    manifest = load_manifest(run_dir)
    manifest.update(status="complete", stop_reason=stop_reason, last_update_time=utc_now())
    atomic_json(run_dir / "manifest.json", manifest)


def generation_metrics(
    generation: int,
    population: list[Candidate],
    *,
    diversity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    objectives: dict[str, Any] = {}
    opponent_by_candidate: dict[str, Any] = {}
    opponent_values: dict[str, list[float]] = {}
    opponent_failures: dict[str, int] = {}
    fronts = assign_rank_and_crowding(population)
    for objective_id, direction in OBJECTIVE_DIRECTIONS.items():
        values = [
            float(candidate.fitness_objectives[objective_id])
            for candidate in population
            if objective_id in candidate.fitness_objectives
            and math.isfinite(float(candidate.fitness_objectives[objective_id]))
            and candidate.status != "failed"
            and candidate.failure_reason is None
            and float(candidate.fitness_objectives[objective_id]) != FAILED_GAME_PERFORMANCE
        ]
        missing = sum(objective_id not in candidate.fitness_objectives for candidate in population)
        failures = sum(
            candidate.status == "failed"
            or candidate.failure_reason is not None
            or candidate.fitness_objectives.get(objective_id) == FAILED_GAME_PERFORMANCE
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
                "aggregate_game_performance": candidate.fitness_objectives.get("game_performance"),
                "expected_match_count": game.get("expected_match_count"),
                "completed_match_count": game.get("completed_match_count"),
                "evaluation_maps": game.get("evaluation_maps"),
                "rounds_per_map": game.get("rounds_per_map"),
                "swap_player_sides": game.get("swap_player_sides"),
                "opponent_scores": scores,
                "fixed_weight_sum": game.get("fixed_weight_sum"),
                "eagle_weight": game.get("eagle_weight", 0.0),
                "total_weight": game.get("total_weight"),
                "weighted_numerator": game.get("weighted_numerator"),
                "eagle_reference": game.get("eagle_reference"),
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
                if item.get("status") != "completed" or float(item.get("score") or 0.0) == FAILED_GAME_PERFORMANCE:
                    opponent_failures[opponent_id] = opponent_failures.get(opponent_id, 0) + 1
        else:
            # Older generation snapshots remain valid; they simply have no detail.
            opponent_by_candidate.setdefault(candidate.id, {
                "aggregate_game_performance": candidate.fitness_objectives.get("game_performance"),
                "opponent_scores": list(game.get("opponent_scores") or []),
                "best_matchup": None,
                "worst_matchup": None,
            })
    opponent_summary = {
        opponent_id: {
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
    eagle_reference = first_game.get("eagle_reference")
    previous_champion_id = None if not isinstance(eagle_reference, dict) else eagle_reference.get("candidate_id")
    previous_champion_generation = None if not isinstance(eagle_reference, dict) else eagle_reference.get("generation")
    payload = {
        "schema_version": "eagle-generation-metrics-v1",
        "generation": generation,
        "population_size": len(population),
        "previous_champion_candidate_id": previous_champion_id,
        "previous_champion_generation": previous_champion_generation,
        "previous_champion_game_performance": next(
            iter((eagle_reference.get("game_performance"),)) if isinstance(eagle_reference, dict) else iter(()),
            None,
        ),
        "eagle_weight": first_game.get("eagle_weight", 0.0),
        "fixed_weight_sum": first_game.get("fixed_weight_sum"),
        "total_weight": first_game.get("total_weight"),
        "weighted_numerator": first_game.get("weighted_numerator"),
        "expected_match_count": first_game.get("expected_match_count"),
        "completed_match_count": first_game.get("completed_match_count"),
        "evaluation_maps": first_game.get("evaluation_maps"),
        "rounds_per_map": first_game.get("rounds_per_map"),
        "swap_player_sides": first_game.get("swap_player_sides"),
        "failure_count": sum(candidate.status == "failed" or candidate.failure_reason is not None for candidate in population),
        "pareto_front_size": len(fronts[0]) if fronts else 0,
        "objectives": objectives,
        "opponent_scores": {
            "by_candidate": opponent_by_candidate,
            "by_opponent": opponent_summary,
        },
    }
    if diversity is not None:
        payload["strategy_diversity"] = dict(diversity)
    return payload


def load_resume_population(run_dir: Path) -> tuple[int, list[Candidate]]:
    manifest = load_manifest(run_dir)
    completed = [int(value) for value in manifest.get("completed_generations", [])]
    if not completed:
        raise ValueError(f"Run has no completed generation to resume: {run_dir}")
    generation = max(completed)
    path = run_dir / "generations" / f"generation_{generation:04d}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    population = payload.get("population")
    if not isinstance(population, list):
        raise ValueError(f"Invalid generation snapshot: {path}")
    return generation, [candidate_from_dict(item) for item in population]


def candidate_from_dict(payload: dict[str, Any]) -> Candidate:
    field_names = set(Candidate.__dataclass_fields__)
    values = {key: value for key, value in payload.items() if key in field_names}
    values["id"] = str(payload.get("candidate_id") or payload.get("id"))
    for key in ("parent_ids", "source_candidate_ids"):
        values[key] = tuple(values.get(key, ()))
    return Candidate(**values)


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Unsupported run manifest schema in {path}.")
    return payload


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


def _jsonl_by_key(path: Path, key: str) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    return {
        int(payload[key]): payload
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for payload in [json.loads(line)]
    }
