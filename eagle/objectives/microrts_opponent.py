"""MicroRTS opponent-score objective plugin."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import BaseObjective
from eagle.utils.fitness_calculator import combined_match_score


class MicroRTSOpponentObjective(BaseObjective):
    """Score one configured MicroRTS opponent slot."""

    name = "microrts_opponent"
    evaluator = "gameplay"
    target_based = True
    calculation_label = "raw_resource_advantage_score + win_bonus * win_score"

    def __call__(
        self,
        match_score: dict[str, Any] | None,
        *,
        config,
        target: str | None = None,
        index: int = 0,
    ) -> float:
        """Calculate the scalar objective for one opponent result."""
        return combined_match_score(match_score, win_bonus=config.win_bonus)

    def objective_key(self, target: str | None, index: int) -> str:
        """Create a stable objective key for one configured opponent."""
        if target is None:
            return f"objective_{index}"
        short_name = str(target).split(".")[-1]
        return short_name or f"objective_{index}"

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
            "match_score = calculate_match_score(log, resource_advantage_weights); "
            "raw_resource_advantage_score = weighted ally material/resources - weighted enemy material/resources; "
            "win_score = 1 for win, -1 for loss, 0 for draw/unknown; "
            f"objective = {self.calculation_label}. "
            f"Current mode: {mode}."
        )
