"""Core framework interfaces and registries."""

from .algorithm import BaseAlgorithm
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
    "BaseAlgorithm",
    "BaseTaskPlugin",
    "CROSSOVER_OPERATORS",
    "ENVIRONMENTAL_SELECTION",
    "EvaluationResult",
    "EVALUATORS",
    "Individual",
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
