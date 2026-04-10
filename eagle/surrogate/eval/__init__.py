"""Runtime-side surrogate evaluation helpers."""

from .agent_generator import render_surrogate_agent
from .evaluator import surrogate_evaluation_game_round, surrogate_evaluation_policy

__all__ = [
    "render_surrogate_agent",
    "surrogate_evaluation_game_round",
    "surrogate_evaluation_policy",
]
