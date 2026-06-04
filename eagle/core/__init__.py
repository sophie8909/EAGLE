"""Core framework interfaces and registries."""

from .algorithm import BaseAlgorithm
from .config import algorithm_default_config, algorithm_objective_mode, is_surrogate_algorithm
from .individual import Individual
from .plugin import BaseTaskPlugin, ObjectiveValues, ParsedOutput, TaskPlugin
from .registry import (
    ALGORITHMS,
    CROSSOVER_OPERATORS,
    ENVIRONMENTAL_SELECTION,
    EVALUATORS,
    MUTATION_OPERATORS,
    PARENT_SELECTION,
    PLUGIN_REGISTRY,
    PluginSpec,
    REFLECTION_OPERATORS,
    Registry,
)
from .result import EvaluationResult, ensure_evaluation_result

__all__ = [
    "ALGORITHMS",
    "algorithm_default_config",
    "algorithm_objective_mode",
    "BaseAlgorithm",
    "BaseTaskPlugin",
    "CROSSOVER_OPERATORS",
    "ENVIRONMENTAL_SELECTION",
    "EvaluationResult",
    "EVALUATORS",
    "Individual",
    "is_surrogate_algorithm",
    "MUTATION_OPERATORS",
    "ObjectiveValues",
    "PARENT_SELECTION",
    "PLUGIN_REGISTRY",
    "PluginSpec",
    "ParsedOutput",
    "REFLECTION_OPERATORS",
    "Registry",
    "TaskPlugin",
    "ensure_evaluation_result",
]
