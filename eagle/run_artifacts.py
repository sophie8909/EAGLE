"""Compact canonical run and per-generation artifacts."""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.nsga2_objectives import FAILED_GAME_PERFORMANCE, OBJECTIVE_DIRECTIONS

from .candidate import Candidate

from .selection import assign_rank_and_crowding
RUN_SCHEMA_VERSION = "eagle-run-v1"
GENERATION_SCHEMA_VERSION = "eagle-generation-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_run_manifest(run_dir: Path, *, config_path: Path) -> None:
    for directory in (run_dir / "generations", run_dir / "final_test"):
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


def record_generation(run_dir: Path, generation: int, population: list[Candidate]) -> None:
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
    metrics = generation_metrics(generation, population)
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
            "schema_version": "eagle-final-population-v1",
            "population": [candidate.to_json_dict() for candidate in population],
        },
    )
    manifest = load_manifest(run_dir)
    manifest.update(status="complete", stop_reason=stop_reason, last_update_time=utc_now())
    atomic_json(run_dir / "manifest.json", manifest)


def generation_metrics(generation: int, population: list[Candidate]) -> dict[str, Any]:
    objectives: dict[str, Any] = {}
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
    return {
        "schema_version": "eagle-generation-metrics-v1",
        "generation": generation,
        "population_size": len(population),
        "failure_count": sum(candidate.status == "failed" or candidate.failure_reason is not None for candidate in population),
        "pareto_front_size": len(fronts[0]) if fronts else 0,
        "objectives": objectives,
    }


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
