"""Round evaluator legality/alignment objective plugin."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import BaseObjective


class RoundLegalityAlignmentObjective(BaseObjective):
    """Describe the two fixed objectives emitted by the round evaluator."""

    name = "round_legality_alignment"
    evaluator = "round"
    target_based = False
    objective_count = 2
    calculation_label = "normalized legality and normalized strategy alignment"

    def __call__(
        self,
        round_score: list[float] | tuple[float, ...] | dict[str, Any] | None,
        *,
        config,
        target: str | None = None,
        index: int = 0,
    ) -> float:
        """Return one round objective from an existing round score payload."""
        if isinstance(round_score, dict):
            values = round_score.get("fitness", [])
        else:
            values = round_score or []
        try:
            return float(list(values)[index])
        except (IndexError, TypeError, ValueError):
            return 0.0

    def objective_key(self, target: str | None, index: int) -> str:
        """Return the stable objective key for one round-evaluator dimension."""
        return ("legality", "strategy_alignment")[index] if index < 2 else f"round_objective_{index}"

    def describe(self, target: str | None, index: int, *, single_objective: bool) -> str:
        """Return the calculation details shown in the GUI."""
        objective_key = self.objective_key(target, index)
        if objective_key == "legality":
            calculation = (
                "legality = normalized legal/action-quality score from the generated state response. "
                "Invalid or missing moves receive the configured missing-moves penalty."
            )
        else:
            calculation = (
                "strategy_alignment = normalized LLM-judged alignment between the base prompt, "
                "generated game state, and returned action JSON."
            )
        mode = (
            "single-objective GA uses the first round objective"
            if single_objective
            else "multi-objective NSGA-II uses both round objectives"
        )
        return f"{objective_key}: {calculation} Current mode: {mode}."
