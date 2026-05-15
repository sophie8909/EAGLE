"""Objectives for full-game MicroRTS evaluation."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import Objective


class ResourceAdvantageObjective(Objective):
    """Optimize final resource and material advantage."""

    key = "resource_advantage"
    label = "Resource advantage"
    direction = "max"
    application = "microrts"
    eval_modes = {"round", "full_game", "java_surrogate"}
    required_metrics = {"resource_diff"}

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return the evaluator-provided resource difference."""
        return float(eval_result["resource_diff"])


class WinScoreObjective(Objective):
    """Optimize match result."""

    key = "win_score"
    label = "Win score"
    direction = "max"
    application = "microrts"
    eval_modes = {"full_game", "java_surrogate"}
    required_metrics = {"winner"}

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return 1 for wins, -1 for losses, and 0 for draws or unknown results."""
        winner = eval_result["winner"]
        if winner in {1, "1", "win", "winner", True}:
            return 1.0
        if winner in {-1, "-1", "loss", False}:
            return -1.0
        return 0.0


class TimeToWinObjective(Objective):
    """Reward faster wins without rewarding non-winning matches."""

    key = "time_to_win"
    label = "Time to win"
    direction = "max"
    application = "microrts"
    eval_modes = {"full_game", "java_surrogate"}
    required_metrics = {"winner", "game_ticks", "timeout"}

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return inverse game duration for wins, otherwise 0."""
        if WinScoreObjective().compute(eval_result) <= 0 or bool(eval_result["timeout"]):
            return 0.0
        ticks = max(1.0, float(eval_result["game_ticks"]))
        return 1.0 / ticks


class PromptTokenCountObjective(Objective):
    """Minimize the rendered prompt token count."""

    key = "prompt_token_count"
    label = "Prompt token count"
    direction = "min"
    application = "microrts"
    eval_modes = {"round", "full_game", "java_surrogate"}
    required_metrics = {"prompt_token_count"}

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return the rendered prompt token count."""
        return float(eval_result["prompt_token_count"])
