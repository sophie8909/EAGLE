"""Objective plugin interfaces and registry helpers."""

from .base import BaseObjective
from .registry import OBJECTIVE_REGISTRY, get_objective, list_objective_names

__all__ = [
    "BaseObjective",
    "OBJECTIVE_REGISTRY",
    "get_objective",
    "list_objective_names",
]
