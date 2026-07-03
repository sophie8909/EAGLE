"""Compatibility exports for MicroRTS objectives."""

from eagle.objectives.microrts.full_game import (  # noqa: F401
    PromptTokenCountObjective,
    ResourceAdvantageObjective,
    TimeToWinObjective,
    TokenLengthMinimumObjective,
    WinScoreObjective,
)
from eagle.objectives.microrts.round import StrategyAlignmentObjective  # noqa: F401

__all__ = [
    "PromptTokenCountObjective",
    "ResourceAdvantageObjective",
    "StrategyAlignmentObjective",
    "TimeToWinObjective",
    "TokenLengthMinimumObjective",
    "WinScoreObjective",
]
