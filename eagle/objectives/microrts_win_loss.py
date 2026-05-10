"""MicroRTS win/loss gameplay objective plugin."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import BaseObjective


class MicroRTSWinLossObjective(BaseObjective):
    """Score one configured MicroRTS opponent by match outcome only."""

    name = "microrts_win_loss"
    evaluator = "gameplay"
    target_based = True
    calculation_label = "win_score"

    def __call__(
        self,
        match_score: dict[str, Any] | None,
        *,
        config,
        target: str | None = None,
        index: int = 0,
    ) -> float:
        """Return the win/loss score for one opponent result."""
        if not match_score:
            return 0.0
        try:
            return float(match_score.get("win_score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def objective_key(self, target: str | None, index: int) -> str:
        """Create a stable objective key for one configured opponent."""
        if target is None:
            return f"win_loss_{index}"
        short_name = str(target).split(".")[-1]
        return f"{short_name}_win_loss" if short_name else f"win_loss_{index}"

    def describe(self, target: str | None, index: int, *, single_objective: bool) -> str:
        """Return the calculation details shown in the GUI."""
        objective_key = self.objective_key(target, index)
        mode = (
            "single-objective GA uses only this selected target"
            if single_objective
            else "multi-objective NSGA-II uses every listed target as one objective"
        )
        return (
            f"{objective_key} against {target}: "
            "objective = win_score; "
            "win_score = 1 for win, -1 for loss, 0 for draw/unknown. "
            f"Current mode: {mode}."
        )
