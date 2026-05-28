"""Core framework interfaces and registries."""

from .algorithm import BaseAlgorithm
from .individual import Individual
from .registry import (
    ALGORITHMS,
    CROSSOVER_OPERATORS,
    ENVIRONMENTAL_SELECTION,
    EVALUATORS,
    MUTATION_OPERATORS,
    PARENT_SELECTION,
    REFLECTION_OPERATORS,
    Registry,
)
from .result import EvaluationResult, ensure_evaluation_result

__all__ = [
    "ALGORITHMS",
    "BaseAlgorithm",
    "CROSSOVER_OPERATORS",
    "ENVIRONMENTAL_SELECTION",
    "EvaluationResult",
    "EVALUATORS",
    "Individual",
    "MUTATION_OPERATORS",
    "PARENT_SELECTION",
    "REFLECTION_OPERATORS",
    "Registry",
    "ensure_evaluation_result",
]
