"""Canonical opponent identities for evolution evaluation and final tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OpponentSpec:
    opponent_id: str
    display_name: str
    class_name: str
    kind: str
    jar_path: str | None = None


EXTERNAL_OPPONENTS = (
    OpponentSpec("tma", "TMA", "ai.tma.TMA", "external", "third_party/final_test_opponents/jars/tma.jar"),
    OpponentSpec("mayari", "Mayari", "mayariBot.mayari", "external", "third_party/final_test_opponents/jars/mayari.jar"),
    OpponentSpec("coac", "COAC", "ai.coac.CoacAI", "external", "third_party/final_test_opponents/jars/coac.jar"),
)

BASIC_OPPONENTS = (
    OpponentSpec("random", "RandomAI", "ai.RandomAI", "basic"),
    OpponentSpec("random_biased", "RandomBiasedAI", "ai.RandomBiasedAI", "basic"),
    OpponentSpec("passive", "PassiveAI", "ai.PassiveAI", "basic"),
    OpponentSpec("light_rush", "LightRush", "ai.abstraction.LightRush", "basic"),
    OpponentSpec("heavy_rush", "HeavyRush", "ai.abstraction.HeavyRush", "basic"),
)

HISTORICAL_SELF_OPPONENTS = (
    OpponentSpec("historical_self_1", "Historical Self 1", "ai.historical.HistoricalSelf1", "historical_self"),
    OpponentSpec("historical_self_2", "Historical Self 2", "ai.historical.HistoricalSelf2", "historical_self"),
)

EVALUATION_ROSTER = EXTERNAL_OPPONENTS + BASIC_OPPONENTS + HISTORICAL_SELF_OPPONENTS
FINAL_TEST_ROSTER = EXTERNAL_OPPONENTS + BASIC_OPPONENTS


def opponent_by_id(opponent_id: str) -> OpponentSpec:
    for item in EVALUATION_ROSTER + FINAL_TEST_ROSTER:
        if item.opponent_id == opponent_id:
            return item
    raise KeyError(opponent_id)


def rooted_jar_path(repository_root: Path, opponent: OpponentSpec) -> Path | None:
    if not opponent.jar_path:
        return None
    return (repository_root / opponent.jar_path).resolve()
