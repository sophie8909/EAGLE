"""Generic task plugin interface for prompt-search applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from eagle.core.result import EvaluationResult


@dataclass
class ParsedOutput:
    """Task-neutral parsed model output."""

    raw_text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class ObjectiveValues:
    """Task-neutral objective values keyed by objective name."""

    values: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TaskPlugin(Protocol):
    """Protocol every task plugin must implement."""

    name: str

    def build_dynamic_context(self, individual: Any, context: Any | None = None) -> dict[str, Any]:
        """Build task-specific dynamic context for one candidate."""

    def parse_output(self, output: str, context: Any | None = None) -> ParsedOutput:
        """Parse a model/runtime output into task-neutral data."""

    def compute_objectives(
        self,
        evaluation: EvaluationResult | ParsedOutput,
        context: Any | None = None,
    ) -> ObjectiveValues:
        """Compute task objective values from parsed or evaluated output."""

    def evaluate(self, individual: Any, context: Any | None = None) -> EvaluationResult:
        """Evaluate one candidate for this task."""

    def create_evaluator(self, config: Any | None = None, **kwargs: Any) -> Any:
        """Create the task-specific evaluator selected by config."""


class BaseTaskPlugin:
    """Base class with explicit errors for optional plugin methods."""

    name = ""

    def build_dynamic_context(self, individual: Any, context: Any | None = None) -> dict[str, Any]:
        """Build task-specific dynamic context for one candidate."""
        raise NotImplementedError

    def parse_output(self, output: str, context: Any | None = None) -> ParsedOutput:
        """Parse a model/runtime output into task-neutral data."""
        raise NotImplementedError

    def compute_objectives(
        self,
        evaluation: EvaluationResult | ParsedOutput,
        context: Any | None = None,
    ) -> ObjectiveValues:
        """Compute task objective values from parsed or evaluated output."""
        raise NotImplementedError

    def evaluate(self, individual: Any, context: Any | None = None) -> EvaluationResult:
        """Evaluate one candidate for this task."""
        raise NotImplementedError

    def create_evaluator(self, config: Any | None = None, **kwargs: Any) -> Any:
        """Create the task-specific evaluator selected by config."""
        raise NotImplementedError
