"""Convert pipeline results into NSGA-II objective values."""

from __future__ import annotations

from .compiler import CompileResult
from .game_metrics import GameMetrics
from .strategy_alignment import StrategyAlignmentResult


FAILED_GAME_PERFORMANCE = -1000.0
WORST_GAME_OBJECTIVE = -1.0
LOW_ALIGNMENT_OBJECTIVE = 0.0


def build_objectives(
    *,
    compile_result: CompileResult | None,
    game_metrics: GameMetrics | None,
    alignment_result: StrategyAlignmentResult | None,
    failure_category: str | None = None,
) -> dict[str, float]:
    if failure_category is not None:
        return {
            "game_performance": FAILED_GAME_PERFORMANCE,
            "strategy_alignment": LOW_ALIGNMENT_OBJECTIVE,
        }
    return {
        "game_performance": float(game_metrics.objective if game_metrics else WORST_GAME_OBJECTIVE),
        "strategy_alignment": float(alignment_result.score if alignment_result else LOW_ALIGNMENT_OBJECTIVE),
    }
