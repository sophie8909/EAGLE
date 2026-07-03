"""Base interfaces and helpers for modular objectives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from eagle.core.result import ensure_evaluation_result


class Objective(ABC):
    """Base class for one named optimization objective."""

    key: str = ""
    label: str = ""
    direction: str = "max"
    application: str = ""
    eval_modes: set[str] = set()
    required_metrics: set[str] = set()

    def __init__(self) -> None:
        """Validate static objective metadata when instantiated."""
        if self.direction not in {"max", "min"}:
            raise ValueError(f"Unsupported objective direction: {self.direction!r}.")

    @abstractmethod
    def compute(self, eval_result: dict) -> float:
        """Compute the raw objective value from one evaluator result."""

    def optimization_value(self, eval_result: dict[str, Any]) -> float:
        """Return the value stored in fitness for maximization algorithms."""
        value = float(self.compute(ensure_evaluation_result(eval_result).metrics))
        return value if self.direction == "max" else -value


BaseObjective = Objective
