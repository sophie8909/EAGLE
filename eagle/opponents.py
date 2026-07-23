"""Canonical opponent rosters shared by evolution evaluation and final tests."""

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

EVALUATION_ROSTER = EXTERNAL_OPPONENTS + BASIC_OPPONENTS
FINAL_TEST_ROSTER = EXTERNAL_OPPONENTS + BASIC_OPPONENTS


def opponent_by_id(opponent_id: str) -> OpponentSpec:
    for item in EVALUATION_ROSTER:
        if item.opponent_id == opponent_id:
            return item
    raise KeyError(opponent_id)


def rooted_jar_path(repository_root: Path, opponent: OpponentSpec) -> Path | None:
    if not opponent.jar_path:
        return None
    return (repository_root / opponent.jar_path).resolve()