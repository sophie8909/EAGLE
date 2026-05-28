"""Evaluator interface for prompt-search domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from eagle.core.result import EvaluationResult


class BaseEvaluator(ABC):
    """Common evaluator contract returning a normalized evaluation result."""

    @abstractmethod
    def evaluate(self, individual: Any, context: Any = None, **kwargs: Any) -> EvaluationResult:
        """Evaluate one individual and return raw metrics plus optional artifacts."""
