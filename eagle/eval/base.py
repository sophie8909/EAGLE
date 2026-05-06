"""Evaluator interface for prompt-search domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseEvaluator(ABC):
    """Common evaluator contract returning dict-based fitness values."""

    @abstractmethod
    def evaluate(self, individual: Any, **kwargs: Any) -> dict[str, Any]:
        """Evaluate one individual and update its fitness dictionary."""
