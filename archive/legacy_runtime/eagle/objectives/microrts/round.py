"""Objectives for MicroRTS generated-round evaluation."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import Objective


class StrategyAlignmentObjective(Objective):
    """Optimize LLM-judged strategy alignment for a sampled round state."""

    key = "strategy_alignment"
    label = "Strategy alignment"
    direction = "max"
    application = "microrts"
    eval_modes = {"round"}
    required_metrics = {"strategy_alignment_score"}

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return the normalized LLM strategy-alignment score."""
        return float(eval_result["strategy_alignment_score"])
