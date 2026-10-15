"""Compact canonical run and per-generation artifacts."""
from __future__ import annotations

import json
import hashlib
import yaml
import math
import os
import re
import statistics
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eagle.evaluation.objectives import OBJECTIVE_DIRECTIONS
from eagle.opponent_cases import FAILED_OPPONENT_SCORE

from eagle.candidate import (
    FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION,
    FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION,
    FRAMEWORK_SLOTS_MATERIALIZATION_VERSION,
    Candidate,
    has_completed_evaluation,
)
from eagle.config import (
    FRAMEWORK_SLOTS_EVOLUTION_PROTOCOL,
    ExperimentConfig,
    EVOLUTION_PROTOCOL,
    STRATEGY_POLICY_FORMAT,
)
from eagle.generation.framework_slots import (
    FRAMEWORK_BUNDLE_SCHEMA_VERSION,
    canonical_genome_json,
    render_framework,
    validate_framework_bundle,
    validate_genome,
)

RUN_SCHEMA_VERSION = "eagle-run-v2"
GENERATION_SCHEMA_VERSION = "eagle-generation-v3"
ERROR_MEMORY_SCHEMA_VERSION = "eagle-error-memory-v1"
GENERATION_POLICY_SCHEMA_VERSION = "eagle-generation-policy-v2"
RESUME_ARCHIVE_PATHS = (
    "archives/strategy.json", "archives/error_memory.jsonl",
    "archives/self_play_opponents.json",
)

FRAMEWORK_BUNDLE_ARTIFACT = "framework/bundle.json"


def freeze_framework_bundle(
    run_dir: Path,
    config: ExperimentConfig,
) -> ExperimentConfig:
    """Copy the exact configured bundle bytes into a fresh run.

    The exact-byte digest is the run identity fence.  The normalized bundle
    digest is deliberately not substituted here because JSON whitespace and
    key ordering are part of the configured input provenance.
    """

    if config.java_materialization_mode != "framework_slots":
        return config
    source = config.framework_bundle_path
    expected_digest = config.framework_bundle_sha256
    if source is None or expected_digest is None:
        raise ValueError("framework_slots requires a configured framework bundle.")
    data = source.read_bytes()
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("Configured framework bundle_sha256 changed before run creation.")
    target = run_dir / FRAMEWORK_BUNDLE_ARTIFACT
    if target.exists():
        raise ValueError(f"Frozen framework bundle is immutable and already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    frozen = replace(config, framework_bundle_path=target.resolve())
    frozen.validate()
    return frozen


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
            "evolution_protocol": config.evolution_protocol,
            "java_materialization_mode": config.java_materialization_mode,
            "java_compiler_version": (
                config.java_compiler_version
                if config.java_materialization_mode in {"deterministic_dsl", "framework_slots"}
                else None
            ),
            "framework_bundle_version": config.framework_bundle_version if config.java_materialization_mode == "framework_slots" else None,
            "framework_bundle_sha256": config.framework_bundle_sha256 if config.java_materialization_mode == "framework_slots" else None,
            "framework_bundle_artifact": FRAMEWORK_BUNDLE_ARTIFACT if config.java_materialization_mode == "framework_slots" else None,
            "strategy_policy_format": STRATEGY_POLICY_FORMAT,
            "run_id": run_dir.name,
            "created_at": utc_now(),
            "status": "initialized",
            "experiment_name": config.experiment_name,
            "model_name": config.model.name,
            "generation_model_name": config.resolved_generation_model.name,
            "reflection_operator_mode": config.reflection_operator_mode.value,
            "experiment_pid": os.getpid(),
            "latest_generation": None,
            "updated_at": utc_now(),
        },
    )


def mark_run_started(run_dir: Path, *, pid: int | None = None) -> None:
    """Associate a resumed run with the current experiment process."""

    manifest = load_manifest(run_dir)
    if manifest.get("status") == "complete":
        return
    manifest.update(
        status="running",
        experiment_pid=os.getpid() if pid is None else int(pid),
        process_started_at=utc_now(),
        updated_at=utc_now(),
    )
    atomic_json(run_dir / "manifest.json", manifest)


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
    stagnation_count: int = 0,
) -> None:
    """Record the surviving population after selection exactly once."""
    metrics = generation_metrics(generation, population, diversity=diversity)
    snapshot = {
        "schema_version": GENERATION_SCHEMA_VERSION,
        "generation": generation,
        "stagnation_count": stagnation_count,
        "resume_archives": {
            name: (run_dir / name).read_text(encoding="utf-8")
            if (run_dir / name).is_file() else None
            for name in RESUME_ARCHIVE_PATHS
        },
        "population": [
            {
                "candidate_id": candidate.id,
                "fitness_objectives": dict(candidate.fitness_objectives),
                "semantic_signature": dict(candidate.semantic_signature),
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
        records.append(record)
    return records


def finalize_run(run_dir: Path, population: list[Candidate], *, stop_reason: str | None) -> None:
    manifest = load_manifest(run_dir)
    valid = [
        candidate
        for candidate in population
        if has_completed_evaluation(candidate)
    ]
    if valid:
        manifest.update(status="complete", stop_reason=stop_reason)
    else:
        manifest.update(
            status="failed",
            stop_reason=stop_reason or "all_candidates_failed",
            failure_type="population_failure",
            failure_reason="The final population contains no candidate that completed evaluation.",
        )
    manifest["updated_at"] = utc_now()
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
    objective_ids = (
        tuple(population[0].game_eval_result.get("fitness_case_ids") or ())
        if population
        else ()
    ) or tuple(OBJECTIVE_DIRECTIONS)
    for objective_id in objective_ids:
        direction = "maximize"
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
        "semantic_library": _semantic_library_metrics(population),
    }
    if diversity is not None:
        payload["strategy_diversity"] = dict(diversity)
    if aos is not None:
        payload["aos"] = dict(aos)
    return payload


def _semantic_library_metrics(population: list[Candidate]) -> dict[str, Any]:
    complete = [
        candidate
        for candidate in population
        if isinstance(candidate.semantic_signature, dict)
        and candidate.semantic_signature.get("status") == "complete"
    ]

    def equivalence(field: str, scope: str | None = None) -> dict[str, Any]:
        groups: dict[tuple[str, str], list[str]] = {}
        for candidate in complete:
            signature = candidate.semantic_signature
            value = signature.get(field)
            hash_value = value.get(scope) if scope is not None and isinstance(value, dict) else value
            if not isinstance(hash_value, str) or not hash_value:
                continue
            key = (str(signature.get("dataset_id") or ""), hash_value)
            groups.setdefault(key, []).append(candidate.id)
        usable = sum(len(items) for items in groups.values())
        unique = len(groups)
        return {
            "usable_signature_count": usable,
            "unique_signature_count": unique,
            "duplicate_candidate_count": max(0, usable - unique),
            "uniqueness_ratio": unique / usable if usable else 0.0,
            "largest_equivalence_class": max((len(items) for items in groups.values()), default=0),
        }

    map_ids = sorted({
        str(map_id)
        for candidate in complete
        for map_id in (candidate.semantic_signature.get("map_hashes") or {})
    })
    phases = sorted({
        str(phase)
        for candidate in complete
        for phase in (candidate.semantic_signature.get("phase_hashes") or {})
    })
    return {
        "candidate_count": len(population),
        "available_signature_count": len(complete),
        "unavailable_signature_count": len(population) - len(complete),
        "global": equivalence("global_hash"),
        "by_map": {map_id: equivalence("map_hashes", map_id) for map_id in map_ids},
        "by_phase": {phase: equivalence("phase_hashes", phase) for phase in phases},
    }


def load_aos_state(run_dir: Path) -> dict[str, Any] | None:
    """Load the latest persisted AOS state for deterministic resume."""

    latest = load_manifest(run_dir).get("latest_generation")
    if latest is None:
        return None
    checkpoint = run_dir / "generations" / f"generation_{int(latest):04d}.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
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
    if not candidate_id or Path(candidate_id).name != candidate_id or candidate_id in {".", ".."}:
        raise ValueError(f"Invalid candidate identifier: {candidate_id!r}")
    candidate_dir = run_dir / "candidates" / candidate_id
    path = candidate_dir / "candidate.json"
    if not path.is_file():
        raise ValueError(f"Candidate snapshot is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))

    def text(relative: str) -> str:
        target = candidate_dir / relative
        if not target.is_file():
            return ""
        if payload.get("java_materialization_mode") == "deterministic_dsl":
            return target.read_bytes().decode("utf-8")
        return target.read_text(encoding="utf-8")

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

    mode = payload.get("java_materialization_mode", "llm")
    version = payload.get("java_compiler_version")
    if payload.get("candidate_schema_version") == "eagle-candidate-v7" and mode != "deterministic_dsl":
        raise ValueError("Deterministic candidate schema cannot be reinterpreted in another mode.")
    if mode == "deterministic_dsl":
        if payload.get("candidate_schema_version") != "eagle-candidate-v7":
            raise ValueError("Unsupported deterministic candidate schema version.")
        from eagle.config import JAVA_COMPILER_VERSION
        if version != JAVA_COMPILER_VERSION:
            raise ValueError(f"Unsupported Java compiler version: {version!r}")
        if payload.get("active_genotype_components") != ["strategy_prompt"]:
            raise ValueError("Invalid deterministic active genotype components.")
        evidence = object_json("generation/compiler_evidence.json")
        if evidence.get("operation") != "deterministic_dsl_compile" or evidence.get("materialization_mode") != mode:
            raise ValueError("Invalid deterministic compiler evidence operation/mode.")
        if evidence.get("compiler_version") != version:
            raise ValueError("Deterministic compiler evidence/version mismatch.")
        generation_result = object_json("generation/result.json")
        if generation_result:
            if generation_result.get("artifact_schema_version") != "phase4-v7":
                raise ValueError("Unsupported deterministic generation artifact schema.")
            for key in ("materialization_mode", "compiler_version", "policy_sha256", "scaffold_sha256", "source_sha256"):
                if generation_result.get(key) != evidence.get(key):
                    raise ValueError(f"Deterministic generation/compiler evidence mismatch: {key}")
        elif payload.get("compile_status") == "success":
            raise ValueError("Successful deterministic candidate lacks generation result evidence.")
        from eagle.strategy_dsl import normalize_strategy_dsl, validate_strategy_dsl
        if evidence.get("schema_version") != "eagle-dsl-materialization-v1":
            raise ValueError("Unsupported deterministic compiler evidence schema.")
        policy = normalize_strategy_dsl(text("genotype/policy_prompt.txt"))
        source = text("phenotype/CandidateAgent.java") or text("generation/compiled_candidate.java")
        if source and any(not isinstance(evidence.get(key), str) or len(evidence[key]) != 64
                          for key in ("policy_sha256", "source_sha256", "scaffold_sha256")):
            raise ValueError("Deterministic compiler evidence requires complete hashes.")
        for content, key in ((policy, "policy_sha256"), (source, "source_sha256")):
            if evidence.get(key) is not None and hashlib.sha256(content.encode("utf-8")).hexdigest() != evidence[key]:
                raise ValueError(f"Deterministic compiler evidence hash mismatch: {key}")
        if source and (text("generation/normalized_policy.json") != policy or evidence.get("normalized_policy") != policy):
            raise ValueError("Deterministic normalized policy evidence mismatch.")
        scaffold = text("generation/scaffold.java")
        if source and hashlib.sha256(scaffold.encode("utf-8")).hexdigest() != evidence["scaffold_sha256"]:
            raise ValueError("Deterministic scaffold evidence hash mismatch.")
        reference_agent = evidence.get("reference_agent")
        policy_reference_agent = validate_strategy_dsl(policy).get("reference_agent")
        if reference_agent != policy_reference_agent:
            raise ValueError("Deterministic reference policy/evidence mismatch.")
        if reference_agent is not None:
            if reference_agent != "WorkerRush":
                raise ValueError(f"Unsupported deterministic reference agent: {reference_agent!r}")
            reference_source = (
                Path(__file__).resolve().parents[1]
                / "third_party/microrts/src/ai/abstraction/WorkerRush.java"
            )
            reference_hash = hashlib.sha256(reference_source.read_bytes()).hexdigest()
            if evidence.get("reference_source_sha256") != reference_hash:
                raise ValueError("Deterministic reference source hash mismatch.")
        elif evidence.get("reference_source_sha256") is not None:
            raise ValueError("Ordinary deterministic policy has a reference source hash.")
    elif mode == "framework_slots":
        if payload.get("candidate_id") != candidate_id:
            raise ValueError("Framework candidate snapshot identifier mismatch.")
        if payload.get("candidate_schema_version") != FRAMEWORK_SLOTS_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("Unsupported framework_slots candidate schema version.")
        if version != FRAMEWORK_SLOTS_MATERIALIZATION_VERSION:
            raise ValueError(f"Unsupported framework_slots materialization version: {version!r}")
        if payload.get("candidate_java_mode") != "generated_phenotype":
            raise ValueError("framework_slots candidate must use generated_phenotype.")
        if payload.get("active_genotype_components") != ["control_genome"]:
            raise ValueError("Invalid framework_slots active genotype components.")

        expected_refs = {
            "control_genome": "genotype/control_genome.json",
            "framework_evidence": "generation/framework_evidence.json",
            "framework_bundle": "../../framework/bundle.json",
        }
        for name, expected in expected_refs.items():
            if artifact_refs.get(name) != expected:
                raise ValueError(f"Invalid framework_slots artifact reference: {name}")

        bundle_path = run_dir / FRAMEWORK_BUNDLE_ARTIFACT
        if not bundle_path.is_file():
            raise ValueError("Frozen framework bundle is missing.")
        bundle_bytes = bundle_path.read_bytes()
        exact_bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
        if payload.get("framework_bundle_sha256") != exact_bundle_sha256:
            raise ValueError("Framework candidate/frozen bundle hash mismatch.")
        try:
            bundle_payload = json.loads(bundle_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Frozen framework bundle is not valid UTF-8 JSON.") from exc
        if not isinstance(bundle_payload, dict):
            raise ValueError("Frozen framework bundle must contain a JSON object.")
        bundle = validate_framework_bundle(bundle_payload)
        if bundle.schema_version != FRAMEWORK_BUNDLE_SCHEMA_VERSION:
            raise ValueError("Unsupported frozen framework bundle schema.")

        manifest = load_manifest(run_dir)
        manifest_fences = (
            ("java_materialization_mode", mode),
            ("evolution_protocol", FRAMEWORK_SLOTS_EVOLUTION_PROTOCOL),
            ("java_compiler_version", FRAMEWORK_SLOTS_MATERIALIZATION_VERSION),
            ("framework_bundle_version", FRAMEWORK_BUNDLE_SCHEMA_VERSION),
            ("framework_bundle_sha256", exact_bundle_sha256),
            ("framework_bundle_artifact", FRAMEWORK_BUNDLE_ARTIFACT),
        )
        for key, expected in manifest_fences:
            if manifest.get(key) != expected:
                raise ValueError(f"Framework candidate/run manifest mismatch: {key}")

        genome_path = candidate_dir / "genotype" / "control_genome.json"
        if not genome_path.is_file():
            raise ValueError("Framework candidate control genome is missing.")
        try:
            raw_genome = json.loads(genome_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Framework candidate control genome is not valid JSON.") from exc
        genome = validate_genome(bundle, raw_genome)
        if genome_path.read_text(encoding="utf-8") != canonical_genome_json(bundle, genome) + "\n":
            raise ValueError("Framework candidate control genome is not canonical.")

        slot_parent_ids = payload.get("slot_parent_ids")
        if not isinstance(slot_parent_ids, dict) or any(
            not isinstance(slot_id, str) or not isinstance(parent_id, str) or not parent_id
            for slot_id, parent_id in slot_parent_ids.items()
        ):
            raise ValueError("Invalid framework_slots slot provenance.")
        slot_ids = set(bundle.slot_ids)
        generation = int(payload.get("generation") or 0)
        if generation == 0:
            if slot_parent_ids:
                raise ValueError("Generation-zero framework candidate has parent provenance.")
        elif set(slot_parent_ids) != slot_ids:
            raise ValueError("Framework candidate provenance must cover every slot.")
        parent_ids = tuple(payload.get("parent_ids") or ())
        if any(parent_id not in parent_ids for parent_id in slot_parent_ids.values()):
            raise ValueError("Framework slot provenance references a non-parent candidate.")
        expected_sources = tuple(dict.fromkeys(
            slot_parent_ids[slot_id] for slot_id in sorted(slot_parent_ids)
        ))
        if tuple(payload.get("source_candidate_ids") or ()) != expected_sources:
            raise ValueError("Framework source candidate IDs/provenance mismatch.")

        lineage = object_json("lineage.json")
        lineage_fences = (
            ("lineage_schema_version", FRAMEWORK_SLOTS_LINEAGE_SCHEMA_VERSION),
            ("candidate_id", candidate_id),
            ("java_materialization_mode", mode),
            ("java_compiler_version", version),
            ("framework_bundle_sha256", exact_bundle_sha256),
            ("active_genotype_components", ["control_genome"]),
            ("slot_parent_ids", slot_parent_ids),
            ("source_candidate_ids", list(expected_sources)),
        )
        for key, expected in lineage_fences:
            if lineage.get(key) != expected:
                raise ValueError(f"Framework candidate lineage mismatch: {key}")

        evidence = object_json("generation/framework_evidence.json")
        rendered = render_framework(bundle, genome)
        identity_fences = (
            ("schema_version", "eagle-framework-materialization-v1"),
            ("operation", "framework_slot_assembly"),
            ("materialization_mode", mode),
            ("materialization_version", version),
            ("framework_bundle_sha256", exact_bundle_sha256),
            ("control_genome", genome),
            ("slot_parent_ids", slot_parent_ids),
        )
        for key, expected in identity_fences:
            if evidence.get(key) != expected:
                raise ValueError(f"Framework materialization evidence mismatch: {key}")
        derived_fences = (
            ("framework_id", bundle.framework_id),
            ("canonical_bundle_sha256", rendered.bundle_sha256),
            ("template_sha256", rendered.template_sha256),
            ("genome_sha256", rendered.genome_sha256),
            ("source_sha256", rendered.source_sha256),
        )
        has_derived_evidence = all(
            evidence.get(key) == expected for key, expected in derived_fences
        )
        has_explicit_failed_evidence = all(
            evidence.get(key) is None for key, _ in derived_fences
        )
        if not has_derived_evidence and not has_explicit_failed_evidence:
            raise ValueError("Framework materialization evidence has partial derived hashes.")
        if payload.get("compile_status") == "success" and not has_derived_evidence:
            raise ValueError("Successful framework candidate lacks derived materialization evidence.")
        generation_result = object_json("generation/result.json")
        if generation_result.get("artifact_schema_version") != "phase4-v8":
            raise ValueError("Unsupported framework generation artifact schema.")
        for key in tuple(key for key, _ in identity_fences) + tuple(
            key for key, _ in derived_fences
        ):
            if generation_result.get(key) != evidence.get(key):
                raise ValueError(f"Framework generation/result evidence mismatch: {key}")
        rendered_source = (
            text("phenotype/CandidateAgent.java")
            or text("generation/failed_candidate.java")
        )
        if has_derived_evidence and rendered_source != rendered.source:
            raise ValueError("Framework candidate phenotype does not match its genome.")
        if has_explicit_failed_evidence and rendered_source:
            raise ValueError("Failed framework materialization unexpectedly persisted source.")
    elif mode != "llm":
        raise ValueError(f"Unsupported Java materialization mode: {mode!r}")
    candidate_java_mode = payload.get("candidate_java_mode")
    if candidate_java_mode is None:
        config_path = run_dir / "config.yaml"
        legacy_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        candidate_java_mode = (legacy_config or {}).get("candidate_java_mode", "generated_phenotype")
    return Candidate(
        candidate_java_mode=str(candidate_java_mode),
        java_materialization_mode=mode,
        java_compiler_version=version,
        control_genome=genome if mode == "framework_slots" else {},
        slot_parent_ids=slot_parent_ids if mode == "framework_slots" else {},
        framework_bundle_sha256=(
            exact_bundle_sha256 if mode == "framework_slots" else None
        ),
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
        semantic_signature=dict(payload.get("semantic_signature") or {}),
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
    return max(valid, key=lambda item: (tuple(item.objective_vector()), item.id)).id


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
