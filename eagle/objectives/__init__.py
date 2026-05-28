"""Objective plugin interfaces and registry helpers."""

from .base import BaseObjective, Objective
from .registry import (
    OBJECTIVE_REGISTRY,
    get_objective,
    get_objectives,
    list_objective_names,
    register_objective,
    selected_objective_names,
    validate_objective_config,
)
from .aggregation import aggregate_fitness

__all__ = [
    "BaseObjective",
    "Objective",
    "OBJECTIVE_REGISTRY",
    "aggregate_fitness",
    "get_objective",
    "get_objectives",
    "list_objective_names",
    "register_objective",
    "selected_objective_names",
    "validate_objective_config",
]
