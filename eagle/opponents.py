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
    enabled: bool = True


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

MICRORTS_BOT_OPPONENTS = (
    OpponentSpec("tiamat", "Tiamat", "ai.competition.tiamat.Tiamat", "bundled_bot", "third_party/microrts/lib/bots/TiamatBot.jar"),
    OpponentSpec("droplet", "Droplet", "GNS.Droplet", "bundled_bot", "third_party/microrts/lib/bots/Droplet.jar"),
    OpponentSpec("izanagi", "Izanagi", "ai.competition.IzanagiBot.Izanagi", "bundled_bot", "third_party/microrts/lib/bots/Izanagi.jar"),
    OpponentSpec("mixed_bot", "MixedBot", "ai.JZ.MixedBot", "bundled_bot", "third_party/microrts/lib/bots/MixedBot.jar"),
    OpponentSpec("guided_a3nw", "GuidedA3NW", "ai.CMAB.GuidedA3NW", "bundled_bot", "third_party/microrts/lib/bots/GRojoA3N.jar"),
)

# This is the only roster used by EA evaluation and Strategy Reflection.  The
# external competition agents below remain exclusively in FINAL_TEST_ROSTER.
EVALUATION_ROSTER = BASIC_OPPONENTS + MICRORTS_BOT_OPPONENTS
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
