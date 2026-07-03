"""Core result interfaces shared by evaluators, objectives, and algorithms."""

from __future__ import annotations

from typing import Any, Mapping


class EvaluationResult(dict):
    """Evaluation output with framework fields and dict-compatible metrics.

    The mapping payload is the metrics dictionary so older code that calls
    ``dict(result)`` or ``result.get(...)`` keeps reading raw evaluator metrics.
    Newer code can use the explicit ``fitness``, ``metrics``, and ``artifacts``
    fields.
    """

    def __init__(
        self,
        *,
        fitness: Mapping[str, float] | None = None,
        metrics: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, str] | None = None,
    ) -> None:
        """Create one normalized evaluator result."""
        super().__init__(dict(metrics or {}))
        self.fitness: dict[str, float] = {
            str(key): float(value) for key, value in dict(fitness or {}).items()
        }
        self.artifacts: dict[str, str] = {
            str(key): str(value) for key, value in dict(artifacts or {}).items()
        }

    @property
    def metrics(self) -> dict[str, Any]:
        """Return raw evaluator metrics."""
        return self

    def copy(self) -> "EvaluationResult":
        """Return a shallow copy preserving result metadata."""
        return EvaluationResult(
            fitness=dict(self.fitness),
            metrics=dict(self.metrics),
            artifacts=dict(self.artifacts),
        )

    def to_record(self) -> dict[str, Any]:
        """Return the explicit serializable framework result shape."""
        return {
            "fitness": dict(self.fitness),
            "metrics": dict(self.metrics),
            "artifacts": dict(self.artifacts),
        }


def ensure_evaluation_result(value: Any) -> EvaluationResult:
    """Normalize raw evaluator output into an EvaluationResult."""
    if isinstance(value, EvaluationResult):
        return value
    if isinstance(value, Mapping):
        explicit_metrics = value.get("metrics")
        if isinstance(explicit_metrics, Mapping):
            return EvaluationResult(
                fitness=value.get("fitness") if isinstance(value.get("fitness"), Mapping) else None,
                metrics=explicit_metrics,
                artifacts=value.get("artifacts") if isinstance(value.get("artifacts"), Mapping) else None,
            )
        return EvaluationResult(metrics=value)
    raise TypeError(f"Evaluator returned unsupported result type: {type(value).__name__}.")
