"""Derive per-opponent best representatives from canonical candidate snapshots."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eagle.opponent_cases import LEXICASE_CASES

ARCHIVE_SCHEMA_VERSION = "eagle-opponent-archive-v2"


def build_opponent_archive(run_dir: Path) -> dict[str, Any]:
    """Read all evaluated candidates; never maintain a second search-time archive."""
    entries: dict[str, Any] = {case: None for case in LEXICASE_CASES}
    for path in sorted((run_dir / "candidates").glob("*/candidate.json")):
        candidate = json.loads(path.read_text(encoding="utf-8"))
        if candidate.get("status") != "evaluated" or candidate.get("failure_reason"):
            continue
        scores = candidate.get("fitness_objectives") or {}
        aggregate = float(candidate.get("aggregate_game_performance") or 0.0)
        identity = candidate["candidate_id"]
        for case in LEXICASE_CASES:
            if case not in scores:
                continue
            score = float(scores[case])
            current = entries[case]
            if current is not None:
                rank = (score, aggregate)
                previous = (current["opponent_score"], current["game_performance"])
                if rank < previous or (rank == previous and identity >= current["candidate_id"]):
                    continue
            entries[case] = {
                "candidate_id": identity,
                "generation": candidate.get("generation", 0),
                "opponent_score": score,
                "game_performance": aggregate,
                "strategy_niche": candidate.get("strategy_niche", "unknown"),
                "strategy_signature": candidate.get("strategy_signature") or {},
                "policy_prompt": f"candidates/{identity}/genotype/policy_prompt.txt",
            }
    return {"schema_version": ARCHIVE_SCHEMA_VERSION, "opponents": entries}
