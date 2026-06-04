"""MicroRTS task plugin implementation."""

from __future__ import annotations

import json
from typing import Any

from eagle.core.plugin import BaseTaskPlugin, ObjectiveValues, ParsedOutput
from eagle.core.registry import PLUGIN_REGISTRY, PluginSpec
from eagle.core.result import EvaluationResult, ensure_evaluation_result
from eagle.plugins.microrts.evaluation.full_game_evaluator import FullGameEvaluator
from eagle.plugins.microrts.evaluation.round_evaluator import Evaluator as RoundEvaluator
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
        evaluator = self.create_evaluator(self.config)
        if isinstance(context, dict):
            return ensure_evaluation_result(evaluator.evaluate(individual, **context))
        return ensure_evaluation_result(evaluator.evaluate(individual, context=context))

    def create_evaluator(
        self,
        config: Any | None = None,
        *,
        component_pool: Any | None = None,
        runtime_logs_dir: Any = None,
    ) -> Any:
        """Create the MicroRTS evaluator selected by config."""
        active_config = config or self.config
        active_pool = component_pool or self.component_pool
        if active_pool is None or active_config is None:
            raise ValueError("MicroRTSPlugin.create_evaluator requires component_pool and config.")
        active_logs_dir = self.runtime_logs_dir if runtime_logs_dir is None else runtime_logs_dir
        mode = str(getattr(active_config, "evaluator", "") or "").strip().lower()
        algorithm = str(getattr(active_config, "algorithm", "") or "").strip().lower()
        if mode == "round":
            return RoundEvaluator(active_pool, active_config, runtime_logs_dir=active_logs_dir)
        if mode in {"", "gameplay", "surrogate", "final_test"}:
            return FullGameEvaluator(active_pool, active_config, runtime_logs_dir=active_logs_dir)
        if algorithm.endswith("_surrogate"):
            return FullGameEvaluator(active_pool, active_config, runtime_logs_dir=active_logs_dir)
        raise ValueError(f"Unsupported MicroRTS evaluator mode: {mode!r}.")

    def run_final_test(self, log_dir: str, generation: int | None, config: Any | None = None) -> Any:
        """Run MicroRTS final-test replay for one experiment log directory."""
        from eagle.plugins.microrts.evaluation.final_test_runner import run_final_test_suite

        return run_final_test_suite(log_dir, generation, config or self.config)

    def register_defaults(self) -> None:
        """Import MicroRTS registrations for algorithms, evaluators, and objectives."""
        register_framework_specs()
        from eagle.plugins.microrts.evaluation import algorithms as _algorithms  # noqa: F401
        from eagle.objectives import registry as _registry  # noqa: F401
        from eagle.plugins.microrts import objectives as _objectives  # noqa: F401


def register_framework_specs() -> None:
    """Register MicroRTS metadata for replaceable framework components."""
    for spec in (
        PluginSpec(
            kind="algorithm",
            id="ga",
            label="GA",
            mode="SO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSGA",
            default_config={
                "parent_selection_operator": "ga_fitness_tournament",
                "env_selection_operator": "ga_fitness_elitism",
                "objective_mode": "single",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="nsga2",
            label="NSGA-II",
            mode="MO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSNSGA2",
            default_config={
                "parent_selection_operator": "nsga2_tournament",
                "env_selection_operator": "nsga2_environmental",
                "objective_mode": "multi",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="ga_surrogate",
            label="GA + Surrogate",
            mode="SO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSGASurrogate",
            default_config={
                "parent_selection_operator": "ga_fitness_tournament",
                "env_selection_operator": "ga_fitness_elitism",
                "objective_mode": "single",
                "surrogate": "early_end",
            },
        ),
        PluginSpec(
            kind="algorithm",
            id="nsga2_surrogate",
            label="NSGA-II + Surrogate",
            mode="MO",
            factory="eagle.plugins.microrts.evaluation.algorithms:MicroRTSNSGA2Surrogate",
            default_config={
                "parent_selection_operator": "nsga2_tournament",
                "env_selection_operator": "nsga2_environmental",
                "objective_mode": "multi",
                "surrogate": "early_end",
            },
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="gameplay",
            label="Real Eval",
            default_config={"evaluator": "gameplay", "eval_mode": "gameplay"},
            factory="eagle.plugins.microrts.evaluation.full_game_evaluator:FullGameEvaluator",
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="early_end",
            label="Early End",
            default_config={
                "evaluator": "gameplay",
                "eval_mode": "early_end",
                "llm_call_limit": 10,
                "fitness_metric": "resource_diff_mean",
            },
            factory="eagle.plugins.microrts.evaluation.full_game_evaluator:FullGameEvaluator",
        ),
        PluginSpec(
            kind="evaluation_mode",
            id="final_test",
            label="Final Test",
            default_config={"runtime_only": True},
            factory="eagle.plugins.microrts.evaluation.final_test_runner:run_final_test_suite",
        ),
        PluginSpec(kind="surrogate", id="none", label="None", default_config={"surrogate": "none"}),
        PluginSpec(kind="surrogate", id="early_end", label="Early End", default_config={"surrogate": "early_end"}),
        PluginSpec(kind="surrogate", id="round", label="Round", default_config={"surrogate": "round"}),
        PluginSpec(kind="surrogate", id="policy_agent", label="Policy Agent", default_config={"surrogate": "policy_agent"}),
        PluginSpec(kind="surrogate", id="java_agent", label="Java Agent", default_config={"surrogate": "java_agent"}),
        PluginSpec(kind="objective_set", id="microrts", label="MicroRTS Objectives", mode="both"),
    ):
        PLUGIN_REGISTRY.register(spec)
