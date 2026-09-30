"""Managed self-play opponent-library and immutable-context helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .candidate import Candidate
from .config import ExperimentConfig
from .opponent_cases import SELF_PLAY_CASES
from .run_artifacts import atomic_json


SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v2"
LEGACY_SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v1"
OPPONENT_LIBRARY_SCHEMA_VERSION = "eagle-self-play-opponent-library-v1"
OPPONENT_LIBRARY_PATH = Path("archives/self_play_opponents.json")


def is_self_play_refresh(config: ExperimentConfig, generation: int) -> bool:
    return (
        config.evaluation_mode == "self_play"
        and generation % config.self_play_refresh_interval == 0
    )


def expand_self_play_slots(candidates: list[Candidate]) -> list[Candidate]:
    """Cycle a non-empty snapshot into the canonical ten lexicase slots."""

    if not candidates:
        raise ValueError("A self-play opponent snapshot must not be empty.")
    return [candidates[index % len(candidates)] for index in range(len(SELF_PLAY_CASES))]


def runnable_self_play_candidates(candidates: list[Candidate]) -> list[Candidate]:
    runnable = [
        candidate
        for candidate in candidates
        if candidate.generated_java and candidate.compile_status == "success"
    ]
    if not runnable:
        raise ValueError("A self-play snapshot requires at least one compiled phenotype.")
    return runnable


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


def update_self_play_opponent_library(run_dir: Path, candidates: list[Candidate]) -> None:
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
        if payload.get("schema_version") != OPPONENT_LIBRARY_SCHEMA_VERSION:
            raise ValueError(f"Unsupported self-play opponent library schema: {path}")
    else:
        payload = {
            "schema_version": OPPONENT_LIBRARY_SCHEMA_VERSION,
            "opponents": [],
        }

    entries = payload.get("opponents")
    if not isinstance(entries, list):
        raise ValueError(f"Self-play opponent library has invalid entries: {path}")
    known_ids = {str(entry.get("candidate_id") or "") for entry in entries if isinstance(entry, dict)}
    for candidate in runnable_self_play_candidates(candidates):
        if candidate.id in known_ids:
            continue
        entries.append({
            "candidate_id": candidate.id,
            "generation": candidate.generation,
            "generated_java_sha256": hashlib.sha256(
                candidate.generated_java.encode("utf-8")
            ).hexdigest(),
        })
        known_ids.add(candidate.id)
    atomic_json(path, payload)


def select_self_play_library_candidates(
    run_dir: Path,
    *,
    generation: int,
    refresh_interval: int,
) -> list[Candidate]:
    """Choose one deterministic active context from the managed library.

    The first implementation intentionally preserves the existing refresh
    cadence: it rotates up to ten stored phenotypes once per refresh epoch.
    This is a library replacement, not a per-generation helpful-opponent
    scheduler.
    """

    path = run_dir / OPPONENT_LIBRARY_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play opponent library is missing or invalid: {path}") from exc
    if payload.get("schema_version") != OPPONENT_LIBRARY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported self-play opponent library schema: {path}")
    entries = payload.get("opponents")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Self-play opponent library has no opponents: {path}")

    from .run_artifacts import load_candidate

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
) -> None:
    candidates = runnable_self_play_candidates(candidates)
    slots = expand_self_play_slots(candidates)
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_snapshot.json",
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generation": generation,
            "refresh_interval": refresh_interval,
            "context_id": self_play_context_id(candidates),
            "opponent_library": {
                "schema_version": OPPONENT_LIBRARY_SCHEMA_VERSION,
                "path": str(OPPONENT_LIBRARY_PATH),
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
    snapshot_generation = completed_generation - completed_generation % refresh_interval
    path = run_dir / "generations" / f"generation_{snapshot_generation:04d}_self_play_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play resume snapshot is missing or invalid: {path}") from exc
    if payload.get("schema_version") not in {
        LEGACY_SNAPSHOT_SCHEMA_VERSION,
        SNAPSHOT_SCHEMA_VERSION,
    }:
        raise ValueError(f"Unsupported self-play snapshot schema: {path}")
    if int(payload.get("refresh_interval", 0)) != refresh_interval:
        raise ValueError("Self-play snapshot refresh interval does not match the run config.")
    candidate_ids = payload.get("source_candidate_ids")
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise ValueError(f"Self-play snapshot has no source candidates: {path}")
    from .run_artifacts import load_candidate

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
