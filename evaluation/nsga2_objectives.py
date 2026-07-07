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
    prompt_chars: int = 0,
    max_prompt_chars: int = 4000,
    evaluation_failed: bool = False,
) -> dict[str, float]:
    prompt_length_score = max(0.0, 1.0 - (prompt_chars / max(1, max_prompt_chars)))
    if evaluation_failed or compile_result is None or not compile_result.ok:
        return {
            "game_performance": FAILED_GAME_PERFORMANCE,
            "strategy_alignment": LOW_ALIGNMENT_OBJECTIVE,
            "prompt_length": prompt_length_score,
        }
    return {
        "game_performance": float(game_metrics.objective if game_metrics else WORST_GAME_OBJECTIVE),
        "strategy_alignment": float(alignment_result.score if alignment_result else LOW_ALIGNMENT_OBJECTIVE),
        "prompt_length": prompt_length_score,
    }
