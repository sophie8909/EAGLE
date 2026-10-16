"""Managed self-play opponent-library and immutable-context helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eagle.candidate import Candidate
from eagle.config import ExperimentConfig
from eagle.opponent_cases import SELF_PLAY_CASES
from eagle.run_artifacts import atomic_json
from eagle.evaluation.semantic_signature import SemanticLibrary


SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v3"
LEGACY_SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v1"
PREVIOUS_SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v2"
LEGACY_OPPONENT_LIBRARY_SCHEMA_VERSION = "eagle-self-play-opponent-library-v1"
OPPONENT_LIBRARY_SCHEMA_VERSION = "eagle-self-play-opponent-library-v2"
OPPONENT_LIBRARY_PATH = Path("archives/self_play_opponents.json")
GENERATION_COHORT_SCHEMA_VERSION = "eagle-self-play-generation-cohorts-v1"
GENERATION_COHORT_PATH = Path("archives/self_play_generation_cohorts.json")


def is_self_play_refresh(config: ExperimentConfig, generation: int) -> bool:
    return (
        config.evaluation_mode == "self_play"
        and generation > config.self_play_refresh_interval
        and (generation - 1) % config.self_play_refresh_interval == 0
    )


def self_play_opponent_generation(generation: int, refresh_interval: int) -> int:
    """Return the delayed opponent cohort used for one evaluation generation."""

    if generation < 0:
        raise ValueError("Self-play generation must be non-negative.")
    if refresh_interval < 1:
        raise ValueError("Self-play refresh interval must be at least one.")
    return max(0, (generation - 1) // refresh_interval)


def expand_self_play_slots(candidates: list[Candidate]) -> list[Candidate]:
    """Cycle a non-empty snapshot into the canonical ten lexicase slots."""

    if not candidates:
        raise ValueError("A self-play opponent snapshot must not be empty.")
    return [candidates[index % len(candidates)] for index in range(len(SELF_PLAY_CASES))]


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


def self_play_context_id(candidates: list[Candidate]) -> str:
    slots = expand_self_play_slots(candidates)
    payload = [
        {
            "slot_id": slot_id,
            "source_candidate_id": candidate.id,
            "source_generation": candidate.generation,
        }
        for slot_id, candidate in zip(SELF_PLAY_CASES, slots, strict=True)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def update_self_play_opponent_library(
    run_dir: Path,
    candidates: list[Candidate],
    *,
    capacity: int,
) -> None:
    """Append newly runnable phenotypes to the run-local opponent library.

    Candidate artifacts remain the sole Java-source owner.  The library stores
    immutable references only, which lets an old phenotype remain available as
    an opponent without copying executable source into a second artifact tree.
    """

    path = run_dir / OPPONENT_LIBRARY_PATH
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Self-play opponent library is missing or invalid: {path}") from exc
        if payload.get("schema_version") not in {
            LEGACY_OPPONENT_LIBRARY_SCHEMA_VERSION,
            OPPONENT_LIBRARY_SCHEMA_VERSION,
        }:
            raise ValueError(f"Unsupported self-play opponent library schema: {path}")
        payload["schema_version"] = OPPONENT_LIBRARY_SCHEMA_VERSION
    else:
        payload = {
            "schema_version": OPPONENT_LIBRARY_SCHEMA_VERSION,
            "opponents": [],
        }

    entries = payload.get("opponents")
    if not isinstance(entries, list):
        raise ValueError(f"Self-play opponent library has invalid entries: {path}")
    if capacity < 1:
        raise ValueError("Self-play opponent library capacity must be at least 1.")
    if len(entries) > capacity:
        del entries[:len(entries) - capacity]

    def current_indexes() -> tuple[set[str], set[str], SemanticLibrary]:
        known_ids = {
            str(entry.get("candidate_id") or "")
            for entry in entries
            if isinstance(entry, dict)
        }
        known_java_hashes = {
            str(entry.get("generated_java_sha256") or "")
            for entry in entries
            if isinstance(entry, dict) and entry.get("generated_java_sha256")
        }
        semantic_library = SemanticLibrary()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            summary = entry.get("semantic_signature")
            if isinstance(summary, dict):
                semantic_library.add(str(entry.get("candidate_id") or ""), summary)
        return known_ids, known_java_hashes, semantic_library

    for candidate in runnable_self_play_candidates(candidates):
        known_ids, known_java_hashes, semantic_library = current_indexes()
        if candidate.id in known_ids:
            continue
        generated_java_sha256 = hashlib.sha256(
            candidate.generated_java.encode("utf-8")
        ).hexdigest()
        if generated_java_sha256 in known_java_hashes:
            continue
        semantic_summary = _library_semantic_summary(candidate)
        if semantic_summary is not None and semantic_library.find_equivalent(semantic_summary):
            continue
        entries.append({
            "candidate_id": candidate.id,
            "generation": candidate.generation,
            "generated_java_sha256": generated_java_sha256,
            "semantic_signature": semantic_summary or {
                "status": "unavailable",
                "reason": "complete executable semantic signature unavailable",
            },
        })
        if len(entries) > capacity:
            # The index must follow the bounded FIFO pool.  An evicted
            # phenotype is eligible to re-enter later, like LocalLearner's
            # rolling solution pool.
            del entries[:len(entries) - capacity]
    atomic_json(path, payload)


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


def select_self_play_library_candidates(
    run_dir: Path,
    *,
    generation: int,
    refresh_interval: int,
) -> list[Candidate]:
    """Choose one deterministic context from the semantic archive.

    This compatibility helper remains available for library-contract tests and
    older tooling. The active evolutionary scheduler uses exact delayed
    birth-generation cohorts instead.
    """

    path = run_dir / OPPONENT_LIBRARY_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play opponent library is missing or invalid: {path}") from exc
    if payload.get("schema_version") not in {
        LEGACY_OPPONENT_LIBRARY_SCHEMA_VERSION,
        OPPONENT_LIBRARY_SCHEMA_VERSION,
    }:
        raise ValueError(f"Unsupported self-play opponent library schema: {path}")
    entries = payload.get("opponents")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Self-play opponent library has no opponents: {path}")

    from eagle.run_artifacts import load_candidate

    candidates: list[Candidate] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Self-play opponent library has an invalid entry: {path}")
        candidate_id = str(entry.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError(f"Self-play opponent library has an entry without candidate_id: {path}")
        candidate = load_candidate(run_dir, candidate_id)
        expected_hash = str(entry.get("generated_java_sha256") or "")
        actual_hash = hashlib.sha256(candidate.generated_java.encode("utf-8")).hexdigest()
        if not expected_hash or actual_hash != expected_hash:
            raise ValueError(
                f"Self-play opponent library Java hash does not match candidate artifacts: {path}"
            )
        candidates.append(candidate)
    candidates = runnable_self_play_candidates(candidates)
    source_count = min(len(candidates), len(SELF_PLAY_CASES))
    epoch = generation // refresh_interval
    start = (epoch * source_count) % len(candidates)
    return [candidates[(start + index) % len(candidates)] for index in range(source_count)]


def write_self_play_snapshot(
    run_dir: Path,
    *,
    generation: int,
    candidates: list[Candidate],
    refresh_interval: int,
    opponent_generation: int | None = None,
) -> None:
    candidates = runnable_self_play_candidates(candidates)
    slots = expand_self_play_slots(candidates)
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_snapshot.json",
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generation": generation,
            "refresh_interval": refresh_interval,
            "opponent_generation": (
                generation if opponent_generation is None else opponent_generation
            ),
            "opponent_schedule": "passive_gen0_then_delayed_generation_cohorts",
            "context_id": self_play_context_id(candidates),
            "opponent_library": {
                "schema_version": OPPONENT_LIBRARY_SCHEMA_VERSION,
                "path": str(OPPONENT_LIBRARY_PATH),
            },
            "generation_cohorts": {
                "schema_version": GENERATION_COHORT_SCHEMA_VERSION,
                "path": str(GENERATION_COHORT_PATH),
            },
            "source_candidate_ids": [candidate.id for candidate in candidates],
            "slots": [
                {
                    "slot_id": slot_id,
                    "source_candidate_id": candidate.id,
                    "source_generation": candidate.generation,
                }
                for slot_id, candidate in zip(SELF_PLAY_CASES, slots, strict=True)
            ],
        },
    )


def load_self_play_snapshot(
    run_dir: Path,
    *,
    completed_generation: int,
    refresh_interval: int,
) -> list[Candidate]:
    snapshot_generation = (
        0
        if completed_generation <= refresh_interval
        else completed_generation - (completed_generation - 1) % refresh_interval
    )
    path = run_dir / "generations" / f"generation_{snapshot_generation:04d}_self_play_snapshot.json"
    if not path.is_file():
        # Preserve resumability for pre-delay v2 runs that wrote snapshots at
        # generations 5, 10, ... rather than at the delayed switch boundary.
        legacy_generation = completed_generation - completed_generation % refresh_interval
        path = run_dir / "generations" / f"generation_{legacy_generation:04d}_self_play_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play resume snapshot is missing or invalid: {path}") from exc
    if payload.get("schema_version") not in {
        LEGACY_SNAPSHOT_SCHEMA_VERSION,
        PREVIOUS_SNAPSHOT_SCHEMA_VERSION,
        SNAPSHOT_SCHEMA_VERSION,
    }:
        raise ValueError(f"Unsupported self-play snapshot schema: {path}")
    if int(payload.get("refresh_interval", 0)) != refresh_interval:
        raise ValueError("Self-play snapshot refresh interval does not match the run config.")
    candidate_ids = payload.get("source_candidate_ids")
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ValueError(f"Self-play snapshot has no source candidates: {path}")
    from eagle.run_artifacts import load_candidate

    candidates = [load_candidate(run_dir, str(candidate_id)) for candidate_id in candidate_ids]
    if self_play_context_id(candidates) != payload.get("context_id"):
        raise ValueError(f"Self-play snapshot context hash does not match candidate artifacts: {path}")
    return candidates


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
    snapshot_candidates: list[Candidate],
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
