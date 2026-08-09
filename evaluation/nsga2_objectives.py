"""Convert pipeline results into NSGA-II objective values."""
from __future__ import annotations
from .code_quality import CodeQualityBreakdown, FAILED_CODE_QUALITY
from .game_metrics import GameMetrics
FAILED_GAME_PERFORMANCE = -1000.0
FAILED_OBJECTIVES = {
    "game_performance": FAILED_GAME_PERFORMANCE,
    "code_quality": FAILED_CODE_QUALITY,
}
OBJECTIVE_DIRECTIONS = {"game_performance": "maximize", "code_quality": "maximize"}

def build_objectives(
    *,
    game_metrics: GameMetrics | None,
    code_quality: CodeQualityBreakdown,
    game_failure: bool = False,
) -> dict[str, float]:
    failed = game_failure or game_metrics is None or code_quality.code_quality == FAILED_CODE_QUALITY
    if failed:
        return dict(FAILED_OBJECTIVES)
    return {
        "game_performance": float(game_metrics.objective),
        "code_quality": float(code_quality.code_quality),
    }
