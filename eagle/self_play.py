"""Managed self-play opponent library and immutable fitness contexts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .candidate import Candidate
from .config import ExperimentConfig
from .opponent_cases import SELF_PLAY_CASES
from .run_artifacts import atomic_json


SNAPSHOT_SCHEMA_VERSION = "eagle-self-play-snapshot-v1"
LIBRARY_SCHEMA_VERSION = "eagle-self-play-library-v1"
CONTEXT_SCHEMA_VERSION = "eagle-self-play-context-v1"
HELPFUL_SELECTOR_VERSION = "helpful_v1"
ACTIVE_SLOT_COUNT = len(SELF_PLAY_CASES)


def candidate_java_sha256(candidate: Candidate) -> str:
    return hashlib.sha256(candidate.generated_java.encode("utf-8")).hexdigest()


def _runnable(candidates: Iterable[Candidate]) -> list[Candidate]:
    return [
        candidate
        for candidate in candidates
        if candidate.generated_java and candidate.compile_status == "success"
    ]


def _library_entry(candidate: Candidate, *, generation: int) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "generation": candidate.generation,
        "generated_java_sha256": candidate_java_sha256(candidate),
        "strategy_niche": candidate.strategy_niche,
        "sample_count": 0,
        "mean_score": None,
        "last_seen_generation": generation,
    }


def admit_opponent_library(
    existing: Iterable[dict[str, Any]],
    candidates: Iterable[Candidate],
    *,
    generation: int,
    capacity: int,
) -> list[dict[str, Any]]:
    """Admit unique runnable phenotypes and deterministically bound the library."""

    if capacity < 1:
        raise ValueError("Opponent library capacity must be at least one.")
    entries = {
        str(item.get("candidate_id")): dict(item)
        for item in existing
        if str(item.get("candidate_id") or "")
    }
    java_hashes = {
        str(item.get("generated_java_sha256")): candidate_id
        for candidate_id, item in entries.items()
        if item.get("generated_java_sha256")
    }
    for candidate in _runnable(candidates):
        digest = candidate_java_sha256(candidate)
        current_id = java_hashes.get(digest)
        if current_id is not None and current_id != candidate.id:
            # Keep one immutable artifact for identical phenotypes.
            entries[current_id]["last_seen_generation"] = generation
            continue
        item = entries.setdefault(candidate.id, _library_entry(candidate, generation=generation))
        item["last_seen_generation"] = generation
        item.setdefault("sample_count", 0)
        item.setdefault("mean_score", None)
        item.setdefault("generated_java_sha256", digest)
        item.setdefault("generation", candidate.generation)
        item.setdefault("strategy_niche", candidate.strategy_niche)
        java_hashes[digest] = candidate.id

    def keep_key(item: dict[str, Any]) -> tuple[float, float, int, str]:
        sample_count = int(item.get("sample_count") or 0)
        mean_score = item.get("mean_score")
        distance = abs(float(mean_score)) if mean_score is not None else float("inf")
        return (
            0.0 if sample_count == 0 else 1.0,
            distance,
            -int(item.get("last_seen_generation") or item.get("generation") or 0),
            str(item.get("candidate_id") or ""),
        )

    return sorted(entries.values(), key=keep_key)[:capacity]


def update_opponent_library_scores(
    entries: Iterable[dict[str, Any]],
    evaluated_candidates: Iterable[Candidate],
) -> list[dict[str, Any]]:
    """Fold the last generation's candidate×opponent scores into library entries."""

    by_id = {str(item.get("candidate_id")): dict(item) for item in entries}
    observations: dict[str, list[float]] = {}
    for candidate in evaluated_candidates:
        game = candidate.game_eval_result or {}
        scores = game.get("opponent_scores") or {}
        configuration = game.get("evaluation_configuration") or {}
        for opponent in configuration.get("opponents") or ():
            if not isinstance(opponent, dict):
                continue
            source_id = str(opponent.get("source_candidate_id") or "")
            slot_id = str(opponent.get("slot_id") or "")
            if source_id and slot_id in scores:
                try:
                    observations.setdefault(source_id, []).append(float(scores[slot_id]))
                except (TypeError, ValueError):
                    continue
    for source_id, values in observations.items():
        item = by_id.get(source_id)
        if item is None or not values:
            continue
        old_count = int(item.get("sample_count") or 0)
        old_mean = item.get("mean_score")
        total = old_count * (float(old_mean) if old_mean is not None else 0.0)
        item["sample_count"] = old_count + len(values)
        item["mean_score"] = round((total + sum(values)) / item["sample_count"], 6)
    return list(by_id.values())


def select_helpful_opponents(
    entries: Iterable[dict[str, Any]],
    *,
    active_count: int = ACTIVE_SLOT_COUNT,
) -> list[dict[str, Any]]:
    """Select a deterministic helpful subset, then cycle it into ten slots.

    ``helpful_v1`` is deliberately conservative: unseen opponents are explored
    first, then sampled opponents closest to a draw are preferred because they
    provide the strongest discrimination without selecting only trivial wins or
    impossible losses.  The selector is a measurable first approximation to the
    2L helpful-opponent set-cover idea; richer coverage models can evolve behind
    this persisted selector version later.
    """

    if active_count < 1:
        raise ValueError("active_count must be at least one.")
    candidates = [dict(item) for item in entries if str(item.get("candidate_id") or "")]
    candidates.sort(key=lambda item: (
        0 if int(item.get("sample_count") or 0) == 0 else 1,
        abs(float(item.get("mean_score"))) if item.get("mean_score") is not None else float("inf"),
        -int(item.get("last_seen_generation") or item.get("generation") or 0),
        str(item.get("candidate_id")),
    ))
    return candidates[:min(active_count, len(candidates))]


def resolve_opponent_library_candidates(
    run_dir: Path,
    entries: Iterable[dict[str, Any]],
    *,
    candidates: Iterable[Candidate] = (),
) -> list[Candidate]:
    """Resolve persisted library references without mutating candidate artifacts."""

    from .run_artifacts import load_candidate

    supplied = {candidate.id: candidate for candidate in candidates}
    resolved: list[Candidate] = []
    for item in entries:
        candidate_id = str(item.get("candidate_id") or "")
        if not candidate_id:
            continue
        candidate = supplied.get(candidate_id)
        if candidate is None:
            try:
                candidate = load_candidate(run_dir, candidate_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        if candidate.generated_java and candidate.compile_status == "success":
            expected = str(item.get("generated_java_sha256") or "")
            if not expected or expected == candidate_java_sha256(candidate):
                resolved.append(candidate)
    return resolved


def write_opponent_library(
    run_dir: Path,
    *,
    generation: int,
    entries: Iterable[dict[str, Any]],
    capacity: int,
) -> None:
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_library.json",
        {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "generation": generation,
            "capacity": capacity,
            "selector": HELPFUL_SELECTOR_VERSION,
            "entries": [dict(item) for item in entries],
        },
    )


def write_self_play_context(
    run_dir: Path,
    *,
    generation: int,
    active_candidates: list[Candidate],
    library_entries: Iterable[dict[str, Any]],
) -> None:
    slots = expand_self_play_slots(active_candidates)
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_context.json",
        {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "generation": generation,
            "selector": HELPFUL_SELECTOR_VERSION,
            "context_id": self_play_context_id(active_candidates),
            "library_candidate_ids": [
                str(item.get("candidate_id")) for item in library_entries
            ],
            "active_candidate_ids": [candidate.id for candidate in active_candidates],
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


def load_opponent_library(
    run_dir: Path,
    *,
    generation: int,
) -> list[dict[str, Any]] | None:
    path = run_dir / "generations" / f"generation_{generation:04d}_self_play_library.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIBRARY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported self-play library schema: {path}")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"Self-play library has no entries: {path}")
    return [dict(item) for item in entries if isinstance(item, dict)]


def load_self_play_context(
    run_dir: Path,
    *,
    generation: int,
) -> list[Candidate] | None:
    path = run_dir / "generations" / f"generation_{generation:04d}_self_play_context.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != CONTEXT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported self-play context schema: {path}")
        ids = payload.get("active_candidate_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError(f"Self-play context has no active candidates: {path}")
        from .run_artifacts import load_candidate

        candidates = [load_candidate(run_dir, str(candidate_id)) for candidate_id in ids]
        if self_play_context_id(candidates) != payload.get("context_id"):
            raise ValueError(f"Self-play context hash does not match artifacts: {path}")
        return candidates
    return None


def initialize_opponent_library(
    run_dir: Path,
    *,
    generation: int,
    candidates: list[Candidate],
    capacity: int,
) -> tuple[list[dict[str, Any]], list[Candidate]]:
    entries = admit_opponent_library((), candidates, generation=generation, capacity=capacity)
    entries = update_opponent_library_scores(entries, candidates)
    active_entries = select_helpful_opponents(entries)
    active = resolve_opponent_library_candidates(run_dir, active_entries, candidates=candidates)
    if not active:
        raise ValueError("A self-play opponent library requires at least one runnable candidate.")
    write_opponent_library(run_dir, generation=generation, entries=entries, capacity=capacity)
    write_self_play_context(
        run_dir,
        generation=generation,
        active_candidates=active,
        library_entries=entries,
    )
    return entries, active


def update_and_select_opponent_library(
    run_dir: Path,
    *,
    generation: int,
    existing: list[dict[str, Any]],
    evaluated_candidates: list[Candidate],
    capacity: int,
) -> tuple[list[dict[str, Any]], list[Candidate]]:
    entries = update_opponent_library_scores(existing, evaluated_candidates)
    entries = admit_opponent_library(
        entries,
        evaluated_candidates,
        generation=generation,
        capacity=capacity,
    )
    active_entries = select_helpful_opponents(entries)
    active = resolve_opponent_library_candidates(run_dir, active_entries, candidates=evaluated_candidates)
    if not active:
        raise ValueError("The updated self-play opponent library has no runnable candidate.")
    write_opponent_library(run_dir, generation=generation, entries=entries, capacity=capacity)
    write_self_play_context(
        run_dir,
        generation=generation,
        active_candidates=active,
        library_entries=entries,
    )
    return entries, active


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


def write_self_play_snapshot(
    run_dir: Path,
    *,
    generation: int,
    candidates: list[Candidate],
    refresh_interval: int,
) -> None:
    """Write the pre-library snapshot shape for one-time resume migration."""
    candidates = runnable_self_play_candidates(candidates)
    slots = expand_self_play_slots(candidates)
    atomic_json(
        run_dir / "generations" / f"generation_{generation:04d}_self_play_snapshot.json",
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generation": generation,
            "refresh_interval": refresh_interval,
            "context_id": self_play_context_id(candidates),
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
    """Read a legacy snapshot so old runs can seed the managed library."""
    snapshot_generation = completed_generation - completed_generation % refresh_interval
    path = run_dir / "generations" / f"generation_{snapshot_generation:04d}_self_play_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Self-play resume snapshot is missing or invalid: {path}") from exc
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
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
