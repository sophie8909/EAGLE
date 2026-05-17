"""Objective aggregation from raw evaluator metrics into EA fitness."""

from __future__ import annotations

from typing import Any

from eagle.objectives.registry import (
    _normalize_name,
    get_objective,
    validate_objective_config,
    validate_required_metrics,
)


def aggregate_fitness(eval_result: dict[str, Any], config: Any) -> float | dict[str, float]:
    """Convert raw eval_result metrics into scalar or objective-dict fitness."""
    application = _normalize_name(getattr(config, "application", "microrts") or "microrts")
    objective_result = dict(eval_result)
    objective_result.setdefault("min_token_length", getattr(config, "min_token_length", 1))
    objective_config = validate_objective_config(config, objective_result)
    mode = objective_config["mode"]

    if mode == "single":
        objective = get_objective(application, objective_config["objective"])
        validate_required_metrics(objective, objective_result)
        return objective.optimization_value(objective_result)

    if mode == "weighted_mix":
        weighted_value = 0.0
        for key, weight in objective_config["weights"].items():
            objective = get_objective(application, key)
            validate_required_metrics(objective, objective_result)
            weighted_value += float(weight) * objective.optimization_value(objective_result)
        return weighted_value

    fitness: dict[str, float] = {}
    for key in objective_config["objectives"]:
        objective = get_objective(application, key)
        validate_required_metrics(objective, objective_result)
        fitness[key] = objective.optimization_value(objective_result)
    return fitness
