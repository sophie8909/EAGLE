"""Framework analysis helpers that avoid algorithm-specific branching."""

from __future__ import annotations

from typing import Any

from ..representation.fitness import normalize_fitness_dict


def objective_points(individuals: list[Any], objectives: list[str] | None = None) -> list[dict[str, float]]:
    """Return dict-based objective rows for plotting or GUI display."""
    rows: list[dict[str, float]] = []
    for individual in individuals:
        fitness = normalize_fitness_dict(getattr(individual, "fitness", {}))
        if objectives is not None:
            rows.append({name: float(fitness.get(name, 0.0)) for name in objectives})
        else:
            rows.append(fitness)
    return rows
