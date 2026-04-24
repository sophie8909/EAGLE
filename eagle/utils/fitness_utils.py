"""Utilities for working with the project's fixed-width two-slot fitness vectors."""

from __future__ import annotations

from collections.abc import Sequence

FITNESS_DIMENSIONS = 2
DEFAULT_FITNESS = [0.0, 0.0]


def normalize_fitness(fitness) -> list[float]:
    """
    Normalize any fitness representation into a fixed-width score vector.

    Accepted inputs:
    - None
    - a single int/float
    - a sequence of numeric values
    """
    if fitness is None:
        return DEFAULT_FITNESS.copy()

    if isinstance(fitness, (int, float)):
        return [float(fitness), 0.0]

    if isinstance(fitness, Sequence) and not isinstance(fitness, (str, bytes)):
        values = []
        for value in fitness[:FITNESS_DIMENSIONS]:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values.append(0.0)
        while len(values) < FITNESS_DIMENSIONS:
            values.append(0.0)
        return values

    return DEFAULT_FITNESS.copy()


def fitness_key(fitness) -> tuple[float, float]:
    """
    Comparable key for fixed-width two-slot ranking.
    """
    normalized = normalize_fitness(fitness)
    return tuple(normalized)
