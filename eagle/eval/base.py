"""Evaluator interface for prompt-search domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from eagle.core.result import EvaluationResult


@dataclass
class EvaluationContext:
    """Runtime metadata passed to evaluator plugins."""

    generation: int | None = None
    profile_output_path: str | None = None
    match_score_recorder: Any = None
    opponents: list[str] | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseEvaluator(ABC):
    """Common evaluator contract returning a normalized evaluation result."""

    @abstractmethod
    def evaluate(self, individual: Any, context: Any = None, **kwargs: Any) -> EvaluationResult:
        """Evaluate one individual and return raw metrics plus optional artifacts."""
