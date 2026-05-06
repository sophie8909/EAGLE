"""Core framework interfaces and registries."""

from .algorithm import BaseAlgorithm
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

__all__ = [
    "ALGORITHMS",
    "BaseAlgorithm",
    "CROSSOVER_OPERATORS",
    "ENVIRONMENTAL_SELECTION",
    "EVALUATORS",
    "MUTATION_OPERATORS",
    "PARENT_SELECTION",
    "REFLECTION_OPERATORS",
    "Registry",
]
