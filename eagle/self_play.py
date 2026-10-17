"""Immutable evaluation contexts for the tournament-maintained opponent pool."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.opponent_cases import SELF_PLAY_CASES
from eagle.opponents import OpponentSpec, SEARCH_OPPONENT_REGISTRY, rooted_jar_path
from eagle.opponent_pool import (
    POOL_PATH, POOL_SCHEMA_VERSION, PROTECTED_OPPONENT_IDS, PoolMember,
    member_identity, member_reference, resolve_member_reference,
)
from eagle.run_artifacts import atomic_json


SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v4"
GENERATION_COHORT_SCHEMA_VERSION = "eagle-self-play-generation-cohorts-v1"
GENERATION_COHORT_PATH = Path("archives/self_play_generation_cohorts.json")


def is_self_play_refresh(config: ExperimentConfig, generation: int) -> bool:
    return config.evaluation_mode == "self_play" and generation >= 1 and (
        generation - 1
    ) % config.self_play_refresh_interval == 0


def expand_self_play_slots(members: list[PoolMember]) -> list[PoolMember]:
    """Put permanent opponents first and retain exactly six eligible slots."""
    protected = {
        member.opponent_id: member for member in members
        if isinstance(member, OpponentSpec) and member.opponent_id in PROTECTED_OPPONENT_IDS
    }
    if len(members) != 10 or len({member_identity(item) for item in members}) != 10:
        raise ValueError("A self-play snapshot requires ten distinct pool members.")
    if set(protected) != set(PROTECTED_OPPONENT_IDS):
        raise ValueError("A self-play snapshot requires all four permanent opponents.")
    eligible = [
        member for member in members
        if not isinstance(member, OpponentSpec) or member.opponent_id not in protected
    ]
    return [*(protected[key] for key in PROTECTED_OPPONENT_IDS), *eligible]


def self_play_context_rows(members: list[PoolMember]) -> list[dict[str, object]]:
    slots = expand_self_play_slots(members)
    case_ids = (*PROTECTED_OPPONENT_IDS, *SELF_PLAY_CASES[:6])
    return [
        {
            "slot_id": case_id,
            "source_candidate_id": member.id if isinstance(member, Candidate) else None,
            "source_generation": member.generation if isinstance(member, Candidate) else None,
            "source_opponent_id": member.opponent_id if isinstance(member, OpponentSpec) else None,
        }
        for case_id, member in zip(case_ids, slots, strict=True)
    ]


def self_play_context_id(members: list[PoolMember]) -> str:
    encoded = json.dumps(
        self_play_context_rows(members), sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def self_play_runtime_identity(config: ExperimentConfig) -> dict[str, object]:
    """Fence cached fitness against changed builtins, runtime classes, or maps."""
    from eagle.evaluation.runtime_evaluation import hash_class_directory, hash_file

    root = Path(__file__).resolve().parents[1]
    files = [
        config.microrts_dir / name for name in config.evaluation_maps
    ] + [
        path for opponent in SEARCH_OPPONENT_REGISTRY
        if (path := rooted_jar_path(root, opponent)) is not None
    ] + [root / "third_party/microrts/src/ai/abstraction/WorkerRush.java"]
    directories = [config.microrts_dir / name for name in ("src", "bin", "lib")] + [
        root / name for name in (
            "eagle/opponent_sources", "eagle/opponent_adapters",
            "third_party/gui_opponents/src/allibot/lib",
        )
    ]
    return {
        "files": {str(path.resolve()): hash_file(path) if path.is_file() else None for path in files},
        "directories": {
            str(path.resolve()): hash_class_directory(path) if path.is_dir() else None
            for path in directories
        },
    }


def runnable_self_play_candidates(candidates: list[Candidate]) -> list[Candidate]:
    runnable = [
        candidate
        for candidate in candidates
        if _is_self_play_opponent_ready(candidate)
    ]
    if not runnable:
        raise ValueError(
            "A self-play snapshot requires at least one evaluated, complete phenotype."
        )
    return runnable


def _is_self_play_opponent_ready(candidate: Candidate) -> bool:
    """Reject failed or incomplete phenotypes before they enter the pool."""

    if (
        not candidate.generated_java
        or candidate.compile_status != "success"
        or candidate.status not in {"evaluated", "complete"}
        or candidate.failure_stage is not None
        or candidate.failure_reason is not None
    ):
        return False
    game = candidate.game_eval_result or {}
    expected = game.get("expected_match_count")
    completed = game.get("completed_match_count")
    if expected is not None or completed is not None:
        if expected is None or completed is None or int(completed) != int(expected):
            return False
    opponent_results = game.get("opponent_results") or []
    if any(
        str(row.get("status") or "").lower() != "completed"
        for row in opponent_results
        if isinstance(row, dict)
    ):
        return False
    return True


def record_self_play_generation_cohort(
    run_dir: Path,
    generation: int,
    candidates: list[Candidate],
) -> None:
    """Persist runnable candidates by birth generation for delayed opponents."""

    if generation < 0:
        raise ValueError("Self-play cohort generation must be non-negative.")
    path = run_dir / GENERATION_COHORT_PATH
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Self-play generation cohorts are missing or invalid: {path}") from exc
        if payload.get("schema_version") != GENERATION_COHORT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported self-play generation cohort schema: {path}")
        cohorts = payload.get("cohorts")
        if not isinstance(cohorts, dict):
            raise ValueError(f"Self-play generation cohorts have invalid cohorts: {path}")
    else:
        payload = {
            "schema_version": GENERATION_COHORT_SCHEMA_VERSION,
            "cohorts": {},
        }
        cohorts = payload["cohorts"]

    runnable = runnable_self_play_candidates(candidates)
    cohorts[str(generation)] = {
        "generation": generation,
        "candidate_ids": [candidate.id for candidate in runnable],
    }
    atomic_json(path, payload)


def load_self_play_generation_cohort(
    run_dir: Path,
    generation: int,
) -> list[Candidate]:
    """Load one exact runnable birth-generation cohort from the run archive."""

    path = run_dir / GENERATION_COHORT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play generation cohorts are missing or invalid: {path}") from exc
    if payload.get("schema_version") != GENERATION_COHORT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported self-play generation cohort schema: {path}")
    cohorts = payload.get("cohorts")
    record = cohorts.get(str(generation)) if isinstance(cohorts, dict) else None
    if not isinstance(record, dict) or int(record.get("generation", -1)) != generation:
        raise ValueError(
            f"Self-play opponent cohort for generation {generation} is unavailable: {path}"
        )
    candidate_ids = record.get("candidate_ids")
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ValueError(
            f"Self-play opponent cohort for generation {generation} has no runnable candidates: {path}"
        )
    from eagle.run_artifacts import load_candidate

    candidates = [load_candidate(run_dir, str(candidate_id)) for candidate_id in candidate_ids]
    if any(candidate.generation != generation for candidate in candidates):
        raise ValueError(
            f"Self-play opponent cohort generation mismatch for generation {generation}: {path}"
        )
    return runnable_self_play_candidates(candidates)



def write_self_play_snapshot(
    run_dir: Path,
    *,
    generation: int,
    candidates: list[PoolMember],
    config: ExperimentConfig,
) -> None:
    members = expand_self_play_slots(candidates)
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_snapshot.json",
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION, "generation": generation,
            "refresh_interval": config.self_play_refresh_interval, "pool_policy": "tournament-v1",
            "opponent_schedule": "fixed_champions_and_tournament_pool",
            "context_id": self_play_context_id(members),
            "runtime_identity": self_play_runtime_identity(config),
            "opponent_library": {"schema_version": POOL_SCHEMA_VERSION, "path": str(POOL_PATH)},
            "source_opponents": [member_reference(member) for member in members],
            "slots": self_play_context_rows(members),
        },
    )


def load_self_play_snapshot(
    run_dir: Path,
    *,
    completed_generation: int,
    config: ExperimentConfig,
) -> list[PoolMember]:
    refresh_interval = config.self_play_refresh_interval
    snapshot_generation = (
        0 if completed_generation == 0
        else 1 + (completed_generation - 1) // refresh_interval * refresh_interval
    )
    path = run_dir / "generations" / f"generation_{snapshot_generation:04d}_self_play_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play resume snapshot is missing or invalid: {path}") from exc
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION or payload.get("pool_policy") != "tournament-v1":
        raise ValueError(f"Unsupported self-play pool snapshot; start a new run: {path}")
    if payload.get("generation") != snapshot_generation or payload.get("refresh_interval") != refresh_interval:
        raise ValueError("Self-play snapshot generation/refresh interval does not match the run config.")
    if payload.get("runtime_identity") != self_play_runtime_identity(config):
        raise ValueError("Self-play runtime/opponent/map assets changed; start a new run.")
    references = payload.get("source_opponents")
    if not isinstance(references, list) or len(references) != 10:
        raise ValueError(f"Self-play snapshot requires ten source opponents: {path}")
    members = expand_self_play_slots([resolve_member_reference(run_dir, ref) for ref in references])
    if self_play_context_id(members) != payload.get("context_id") or self_play_context_rows(members) != payload.get("slots"):
        raise ValueError(f"Self-play snapshot context hash does not match opponent artifacts: {path}")
    return members


def assert_shared_self_play_context(candidates: list[Candidate]) -> None:
    context_ids = {
        str(candidate.game_eval_result.get("evaluation_context_id") or "")
        for candidate in candidates
    }
    if len(context_ids) != 1 or "" in context_ids:
        raise ValueError(
            "Self-play survivor selection requires every parent and offspring to be "
            "evaluated against the same immutable opponent snapshot."
        )


def population_matches_self_play_context(
    candidates: list[Candidate],
    snapshot_candidates: list[PoolMember],
) -> bool:
    expected_context_id = self_play_context_id(snapshot_candidates)
    expected_cases = {"game_performance"}
    return bool(candidates) and all(
        candidate.game_eval_result.get("evaluation_context_id") == expected_context_id
        and set(candidate.game_eval_result.get("fitness_case_ids") or ()) == expected_cases
        and set(candidate.fitness_objectives) == expected_cases
        for candidate in candidates
    )


def _library_semantic_summary(candidate: Candidate) -> dict[str, object] | None:
    """Return the LISS-compatible output vector used for library deduplication."""

    value = candidate.semantic_signature
    if not isinstance(value, dict) or value.get("status") != "complete":
        return None
    dataset_id = value.get("dataset_id")
    global_hash = value.get("global_hash")
    probe_ids = value.get("probe_ids")
    action_hashes = value.get("action_hashes")
    if not isinstance(dataset_id, str) or not dataset_id:
        return None
    if not isinstance(global_hash, str) or not global_hash:
        return None
    if not isinstance(probe_ids, list) or not isinstance(action_hashes, list):
        return None
    if not probe_ids or len(probe_ids) != len(action_hashes):
        return None
    if any(not isinstance(item, str) or not item for item in probe_ids + action_hashes):
        return None
    if len(set(probe_ids)) != len(probe_ids):
        return None
    return {
        "status": "complete",
        "dataset_id": dataset_id,
        "dataset_sha256": str(value.get("dataset_sha256") or ""),
        "normalization_version": str(value.get("normalization_version") or ""),
        "probe_ids": list(probe_ids),
        "action_hashes": list(action_hashes),
        "global_hash": global_hash,
    }
