"""Lightweight run-level archive of successfully evaluated strategy niches."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from .candidate import Candidate
from .run_artifacts import atomic_json


ARCHIVE_SCHEMA_VERSION = "eagle-strategy-archive-v1"
ARCHIVE_FILENAME = "strategy_archive.json"


def ensure_strategy_archive(run_dir: Path) -> None:
    path = run_dir / ARCHIVE_FILENAME
    if not path.exists():
        atomic_json(path, {"schema_version": ARCHIVE_SCHEMA_VERSION, "niches": {}})


def load_strategy_archive(run_dir: Path) -> dict[str, Any]:
    ensure_strategy_archive(run_dir)
    import json

    payload = json.loads((run_dir / ARCHIVE_FILENAME).read_text(encoding="utf-8"))
    if payload.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported strategy archive schema: {run_dir / ARCHIVE_FILENAME}")
    if not isinstance(payload.get("niches"), dict):
        raise ValueError(f"Invalid strategy archive: {run_dir / ARCHIVE_FILENAME}")
    return payload


def archive_niches(run_dir: Path) -> set[str]:
    return set(load_strategy_archive(run_dir).get("niches", {}))


def update_strategy_archive(run_dir: Path, candidates: Iterable[Candidate]) -> dict[str, Any]:
    payload = load_strategy_archive(run_dir)
    entries = dict(payload.get("niches", {}))
    for candidate in candidates:
        if not _archiveable(candidate):
            continue
        niche = candidate.strategy_niche
        candidate_entry = _entry(run_dir, candidate)
        current = entries.get(niche)
        if current is None or _better(candidate_entry, current):
            entries[niche] = candidate_entry
    payload = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "niches": dict(sorted(entries.items())),
    }
    atomic_json(run_dir / ARCHIVE_FILENAME, payload)
    return payload


def _archiveable(candidate: Candidate) -> bool:
    game = candidate.fitness_objectives.get("game_performance")
    return (
        candidate.status == "evaluated"
        and not candidate.failure_reason
        and candidate.strategy_niche not in {"", "unknown"}
        and isinstance(game, (int, float))
        and math.isfinite(float(game))
        and float(game) != -1000.0
    )


def _entry(_run_dir: Path, candidate: Candidate) -> dict[str, Any]:
    return {
        "strategy_niche": candidate.strategy_niche,
        "strategy_signature": dict(candidate.strategy_signature),
        "representative_candidate_id": candidate.id,
        "generation": candidate.generation,
        "best_game_performance": candidate.fitness_objectives.get("game_performance"),
        "code_quality": candidate.fitness_objectives.get("code_quality"),
        "strategy_prompt_path": f"candidates/{candidate.id}/genotype/strategy_prompt.txt",
    }


def _better(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_score = _finite_score(candidate.get("best_game_performance"))
    current_score = _finite_score(current.get("best_game_performance"))
    if candidate_score != current_score:
        return candidate_score > current_score
    candidate_quality = _finite_score(candidate.get("code_quality"))
    current_quality = _finite_score(current.get("code_quality"))
    if candidate_quality != current_quality:
        return candidate_quality > current_quality
    return str(candidate.get("representative_candidate_id", "")) < str(current.get("representative_candidate_id", ""))


def _finite_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return -math.inf
    return score if math.isfinite(score) else -math.inf
