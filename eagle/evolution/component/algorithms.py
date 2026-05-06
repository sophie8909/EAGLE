"""Registry entries for generic component-evolution algorithms."""

from __future__ import annotations

from eagle.core.registry import ALGORITHMS

from .ga import GA
from .nsga2 import NSGA2


def register_component_algorithms() -> None:
    """Register application-neutral component algorithm names."""
    ALGORITHMS.register("component_ga", GA)
    ALGORITHMS.register("component_nsga2", NSGA2)


register_component_algorithms()
