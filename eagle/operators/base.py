"""Common interfaces for replaceable evolutionary operators."""

from __future__ import annotations

from typing import Any


class BaseOperator:
    """Base class for all plugin-style evolutionary operators."""

    name: str = ""

    def __init__(self, config: dict | None = None):
        """Store an optional operator-local configuration dictionary."""
        self.config = dict(config or {})

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the operator."""
        raise NotImplementedError


class BaseMutation(BaseOperator):
    """Interface for mutation operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Mutate one individual."""
        raise NotImplementedError


class BaseCrossover(BaseOperator):
    """Interface for crossover operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Recombine parent individuals."""
        raise NotImplementedError


class BaseParentSelection(BaseOperator):
    """Interface for parent-selection operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Select one or more parents."""
        raise NotImplementedError


class BaseReplacement(BaseOperator):
    """Interface for pool or environmental replacement operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Select the next population."""
        raise NotImplementedError
