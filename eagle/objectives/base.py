"""Common interfaces for replaceable fitness objectives."""

from __future__ import annotations

from typing import Any


class BaseObjective:
    """Base class for objective plugins."""

    name: str = ""
    calculation_label: str = ""
    evaluator: str = ""
    target_based: bool = True
    objective_count: int = 1

    def __init__(self, config: dict | None = None):
        """Store optional objective-local configuration."""
        self.config = dict(config or {})

    def __call__(self, *args: Any, **kwargs: Any) -> float:
        """Calculate one objective value."""
        raise NotImplementedError

    def objective_key(self, target: str | None, index: int) -> str:
        """Return the stable objective key for one configured target."""
        raise NotImplementedError

    def describe(self, target: str | None, index: int, *, single_objective: bool) -> str:
        """Return a human-readable calculation summary for the GUI."""
        raise NotImplementedError
