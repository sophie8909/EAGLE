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

# AlliBot ships against a newer, LLM-enabled MicroRTS fork. Its local setup owns
# a self-contained upstream runtime JAR; the same spec is available to search
# evaluation and the GUI inspection utility.
GUI_ONLY_OPPONENTS = (
    OpponentSpec(
        "allibot",
        "AlliBot (upstream runtime)",
        "ai.abstraction.submissions.allibot.alli",
        "gui_only_external",
        "third_party/gui_opponents/jars/allibot.jar",
    ),
)

BASIC_OPPONENTS = (
    OpponentSpec("passive", "PassiveAI", "ai.PassiveAI", "basic"),
    OpponentSpec("random", "RandomAI", "ai.RandomAI", "basic"),
    OpponentSpec("randombias", "RandomBiasedAI", "ai.RandomBiasedAI", "basic"),
    OpponentSpec("lightrush", "LightRush", "ai.abstraction.LightRush", "basic"),
    OpponentSpec("heavyrush", "HeavyRush", "ai.abstraction.HeavyRush", "basic"),
    # The vendored runtime has no WorkerRush class; evaluation compiles a
    # run-local compatibility adapter with this canonical identity.
    OpponentSpec("workerrush", "WorkerRush", "ai.abstraction.WorkerRush", "basic"),
)

MICRORTS_VARIANT_OPPONENTS = (
    OpponentSpec("bfs_light_rush", "BFS LightRush", "ai.abstraction.BFSLightRush", "builtin_variant"),
    OpponentSpec("greedy_light_rush", "Greedy LightRush", "ai.abstraction.GreedyLightRush", "builtin_variant"),
    OpponentSpec("floodfill_light_rush", "FloodFill LightRush", "ai.abstraction.FloodFillLightRush", "builtin_variant"),
    OpponentSpec("astar_light_rush", "AStar LightRush", "ai.abstraction.AStarLightRush", "builtin_variant"),
    OpponentSpec("bfs_heavy_rush", "BFS HeavyRush", "ai.abstraction.BFSHeavyRush", "builtin_variant"),
)

# The search-time roster is resolved from this registry in the canonical order
# supplied by the experiment configuration.  External entries are intentionally
# available here; setup/preflight must fail if one is unavailable.
SEARCH_OPPONENT_REGISTRY = (
    *BASIC_OPPONENTS,
    GUI_ONLY_OPPONENTS[0],
    EXTERNAL_OPPONENTS[1],
    EXTERNAL_OPPONENTS[2],
    EXTERNAL_OPPONENTS[0],
)
EVALUATION_ROSTER = SEARCH_OPPONENT_REGISTRY
FINAL_TEST_BASIC_OPPONENTS = (
    OpponentSpec("random", "RandomAI", "ai.RandomAI", "basic"),
    OpponentSpec("random_biased", "RandomBiasedAI", "ai.RandomBiasedAI", "basic"),
    OpponentSpec("passive", "PassiveAI", "ai.PassiveAI", "basic"),
    OpponentSpec("light_rush", "LightRush", "ai.abstraction.LightRush", "basic"),
    OpponentSpec("heavy_rush", "HeavyRush", "ai.abstraction.HeavyRush", "basic"),
)
FINAL_TEST_ROSTER = EXTERNAL_OPPONENTS + FINAL_TEST_BASIC_OPPONENTS


def opponent_by_id(opponent_id: str) -> OpponentSpec:
    for item in EVALUATION_ROSTER + FINAL_TEST_ROSTER:
        if item.opponent_id == opponent_id:
            return item
    raise KeyError(opponent_id)


def gui_opponent_by_id(opponent_id: str) -> OpponentSpec:
    """Resolve opponents supported by the visual inspection utility only."""

    for item in EVALUATION_ROSTER + EXTERNAL_OPPONENTS + GUI_ONLY_OPPONENTS:
        if item.opponent_id == opponent_id:
            return item
    raise KeyError(opponent_id)


def rooted_jar_path(repository_root: Path, opponent: OpponentSpec) -> Path | None:
    if not opponent.jar_path:
        return None
    return (repository_root / opponent.jar_path).resolve()
