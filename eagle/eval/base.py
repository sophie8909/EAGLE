"""Generic evaluator contracts for prompt-search tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from eagle.core.result import EvaluationResult


@dataclass
class EvaluationRequest:
    """Task-neutral request for evaluating one candidate."""

    individual: Any | None = None
    prompt: str = ""
    context: Any = None
    runtime: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationContext:
    """Runtime metadata passed to evaluator plugins."""

    generation: int | None = None
    profile_output_path: str | None = None
    match_score_recorder: Any = None
    opponents: list[str] | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class Evaluator(ABC):
    """Common evaluator contract returning a normalized evaluation result."""

    @abstractmethod
    def evaluate(
        self,
        individual: Any | None = None,
        context: EvaluationContext | None = None,
        **runtime: Any,
    ) -> EvaluationResult:
        """Evaluate one individual or prompt with task runtime context."""


BaseEvaluator = Evaluator
