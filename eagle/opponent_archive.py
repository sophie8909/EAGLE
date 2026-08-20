"""Run-level archive of the best valid candidate for each opponent case."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .candidate import Candidate
from .opponent_cases import LEXICASE_CASES, FAILED_OPPONENT_SCORE


ARCHIVE_SCHEMA_VERSION = "eagle-opponent-archive-v1"
ARCHIVE_PATH = Path("archives/opponents.json")


def ensure_opponent_archive(run_dir: Path) -> None:
    path = run_dir / ARCHIVE_PATH
    if path.is_file():
        return
    _write(path, {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "opponents": {case: None for case in LEXICASE_CASES},
    })


def update_opponent_archive(run_dir: Path, candidates: list[Candidate]) -> None:
    ensure_opponent_archive(run_dir)
    payload = json.loads((run_dir / ARCHIVE_PATH).read_text(encoding="utf-8"))
    entries = payload.setdefault("opponents", {})
    for candidate in candidates:
        if candidate.status != "evaluated" or candidate.failure_reason:
            continue
        aggregate = float((candidate.game_eval_result or {}).get("game_performance", -1000.0))
        for case in LEXICASE_CASES:
            score = float(candidate.fitness_objectives.get(case, FAILED_OPPONENT_SCORE))
            current = entries.get(case)
            if current is not None and not _is_better(score, aggregate, candidate.id, current):
                continue
            entries[case] = {
                "candidate_id": candidate.id,
                "generation": candidate.generation,
                "opponent_score": score,
                "game_performance": aggregate,
                "strategy_niche": candidate.strategy_niche,
                "strategy_signature": dict(candidate.strategy_signature),
                "strategy_prompt": f"candidates/{candidate.id}/genotype/strategy_prompt.txt",
            }
    _write(run_dir / ARCHIVE_PATH, payload)


def _is_better(score: float, aggregate: float, candidate_id: str, current: dict[str, Any]) -> bool:
    if score != float(current.get("opponent_score", FAILED_OPPONENT_SCORE)):
        return score > float(current.get("opponent_score", FAILED_OPPONENT_SCORE))
    if aggregate != float(current.get("game_performance", FAILED_OPPONENT_SCORE)):
        return aggregate > float(current.get("game_performance", FAILED_OPPONENT_SCORE))
    return _stable_id(candidate_id) < _stable_id(str(current.get("candidate_id", "")))


def _stable_id(value: str) -> tuple[int, str]:
    return (0, value)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
