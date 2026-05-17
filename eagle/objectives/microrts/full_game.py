"""Objectives for full-game MicroRTS evaluation."""

from __future__ import annotations

from typing import Any

from eagle.objectives.base import Objective
from eagle.utils.token_count import count_prompt_tokens


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


class TokenLengthMinimumObjective(Objective):
    """Reward prompts that meet a configured minimum token length."""

    key = "token_length_minimum"
    label = "Token length minimum"
    direction = "max"
    application = "microrts"
    eval_modes = {"round", "full_game", "java_surrogate"}
    required_metrics = set()

    def compute(self, eval_result: dict[str, Any]) -> float:
        """Return a bounded length-sufficiency score in [0, 1]."""
        min_length = max(1.0, float(eval_result.get("min_token_length", 1) or 1))
        token_length = self._token_length(eval_result)
        return max(0.0, min(1.0, token_length / min_length))

    def _token_length(self, eval_result: dict[str, Any]) -> float:
        """Read existing token count, falling back to the shared prompt counter."""
        value = eval_result.get("prompt_token_count")
        if value is not None:
            return max(0.0, float(value))
        return float(count_prompt_tokens(str(eval_result.get("prompt", "")))[0])
