"""MicroRTS task plugin implementation."""

from __future__ import annotations

import json
from typing import Any

from eagle.core.plugin import BaseTaskPlugin, ObjectiveValues, ParsedOutput
from eagle.core.result import EvaluationResult, ensure_evaluation_result
from eagle.eval.microrts.full_game_evaluator import FullGameEvaluator
from eagle.objectives.aggregation import aggregate_fitness
from eagle.plugins.microrts.prompt import MicroRTSPromptRenderer


class MicroRTSPlugin(BaseTaskPlugin):
    """Task plugin for the bundled MicroRTS prompt-search case study."""

    name = "microrts"

    def __init__(self, component_pool: Any | None = None, config: Any | None = None, runtime_logs_dir: Any = None):
        """Store optional runtime dependencies for plugin-bound evaluation."""
        self.component_pool = component_pool
        self.config = config
        self.runtime_logs_dir = runtime_logs_dir

    def build_dynamic_context(self, individual: Any, context: Any | None = None) -> dict[str, Any]:
        """Build MicroRTS dynamic context metadata for one individual."""
        del context
        if self.component_pool is None or self.config is None:
            return {}
        prompt = MicroRTSPromptRenderer(self.component_pool, self.config).render(individual)
        return {"prompt": prompt}

    def parse_output(self, output: str, context: Any | None = None) -> ParsedOutput:
        """Parse strict JSON model output for MicroRTS-style action responses."""
        del context
        try:
            parsed = json.loads(str(output or ""))
        except json.JSONDecodeError as exc:
            return ParsedOutput(raw_text=str(output or ""), errors=[str(exc)])
        if not isinstance(parsed, dict):
            return ParsedOutput(raw_text=str(output or ""), errors=["Parsed output is not a JSON object."])
        return ParsedOutput(raw_text=str(output or ""), data=parsed)

    def compute_objectives(
        self,
        evaluation: EvaluationResult | ParsedOutput,
        context: Any | None = None,
    ) -> ObjectiveValues:
        """Compute configured MicroRTS objective values from an evaluation result."""
        del context
        if self.config is None:
            return ObjectiveValues()
        if isinstance(evaluation, ParsedOutput):
            metrics = dict(evaluation.data)
        else:
            metrics = dict(ensure_evaluation_result(evaluation).metrics)
        fitness = aggregate_fitness(metrics, self.config)
        values = dict(fitness) if isinstance(fitness, dict) else {"score": float(fitness)}
        return ObjectiveValues(values=values, metrics=metrics)

    def evaluate(self, individual: Any, context: Any | None = None) -> EvaluationResult:
        """Evaluate one candidate through the existing MicroRTS evaluator."""
        if self.component_pool is None or self.config is None:
            raise ValueError("MicroRTSPlugin.evaluate requires component_pool and config.")
        evaluator = FullGameEvaluator(
            self.component_pool,
            self.config,
            runtime_logs_dir=self.runtime_logs_dir,
        )
        if isinstance(context, dict):
            return ensure_evaluation_result(evaluator.evaluate(individual, **context))
        return ensure_evaluation_result(evaluator.evaluate(individual, context=context))

    def register_defaults(self) -> None:
        """Import MicroRTS registrations for algorithms, evaluators, and objectives."""
        from eagle.eval.microrts import algorithms as _algorithms  # noqa: F401
        from eagle.objectives import registry as _registry  # noqa: F401
        from eagle.plugins.microrts import objectives as _objectives  # noqa: F401
