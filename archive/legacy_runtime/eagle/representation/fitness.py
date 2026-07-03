"""Fitness normalization helpers for objective-name dictionaries."""

from __future__ import annotations

from typing import Any, Iterable


DEFAULT_OBJECTIVE_PREFIX = "objective"


def normalize_fitness_dict(
    fitness: Any,
    objective_names: Iterable[str] | None = None,
) -> dict[str, float]:
    """Convert scalar/list fitness payloads into objective dictionaries."""
    if isinstance(fitness, dict):
        return {str(key): _safe_float(value) for key, value in fitness.items()}
    if fitness is None:
        return {}
    if isinstance(fitness, (int, float)):
        names = list(objective_names or ["score"])
        return {str(names[0]): float(fitness)}
    try:
        values = list(fitness)
    except TypeError:
        return {}
    names = list(objective_names or [])
    result: dict[str, float] = {}
    for index, value in enumerate(values):
        key = str(names[index]) if index < len(names) else f"{DEFAULT_OBJECTIVE_PREFIX}_{index}"
        result[key] = _safe_float(value)
    return result


def fitness_objectives(fitness: Any) -> list[str]:
    """Return objective names in deterministic order for any fitness payload."""
    if isinstance(fitness, dict):
        return list(fitness.keys())
    values = normalize_fitness_dict(fitness)
    return list(values.keys())


def fitness_values(
    fitness: Any,
    objective_names: Iterable[str] | None = None,
) -> list[float]:
    """Return ordered objective values from either dict or sequence fitness."""
    normalized = normalize_fitness_dict(fitness, objective_names)
    if objective_names is not None:
        return [float(normalized.get(str(name), 0.0)) for name in objective_names]
    return [float(value) for value in normalized.values()]


def fitness_sort_key(fitness: Any, objective_names: Iterable[str] | None = None) -> tuple[float, ...]:
    """Build a lexicographic maximization key for single-objective survivor sorting."""
    return tuple(fitness_values(fitness, objective_names))


def _safe_float(value: Any) -> float:
    """Coerce one objective value to float, treating invalid values as zero."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
