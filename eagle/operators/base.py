"""Common interfaces for replaceable evolutionary operators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OperatorContext:
    """Runtime dependencies passed to operator plugins."""

    component_pool: Any = None
    config: Any = None
    algorithm: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseOperator:
    """Base class for all plugin-style evolutionary operators."""

    name: str = ""

    def __init__(self, config: dict | None = None):
        """Store an optional operator-local configuration dictionary."""
        self.config = dict(config or {})

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the operator."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Execute the operator using the framework plugin call pattern."""
        raise NotImplementedError


class BaseMutation(BaseOperator):
    """Interface for mutation operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Mutate one individual."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Mutate the first parent using context-local dependencies."""
        parent = _first_parent(parents)
        if context is None:
            raise ValueError("Mutation operators require an OperatorContext.")
        return self(parent, context.component_pool, context.config)


class BaseCrossover(BaseOperator):
    """Interface for crossover operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Recombine parent individuals."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Recombine the first two parents using context-local dependencies."""
        parent_list = _parent_list(parents)
        if len(parent_list) < 2:
            raise ValueError("Crossover operators require at least two parents.")
        if context is None:
            raise ValueError("Crossover operators require an OperatorContext.")
        return self(context.component_pool, parent_list[0], parent_list[1], context.config)


class BaseParentSelection(BaseOperator):
    """Interface for parent-selection operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Select one or more parents."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Select parents from the algorithm stored in context."""
        del parents
        if context is None or context.algorithm is None:
            raise ValueError("Parent-selection operators require context.algorithm.")
        count = int(context.metadata.get("count", 1))
        return self(context.algorithm, count=count)


class BaseReplacement(BaseOperator):
    """Interface for pool or environmental replacement operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Select the next population."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Select survivors from population and offspring in context metadata."""
        del parents
        if context is None or context.algorithm is None:
            raise ValueError("Replacement operators require context.algorithm.")
        return self(
            context.algorithm,
            context.metadata.get("population", []),
            context.metadata.get("offspring", []),
        )


class BaseReflection(BaseOperator):
    """Interface for reflection operators."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Reflect on one or more parents."""
        raise NotImplementedError

    def apply(self, parents: Any, context: OperatorContext | None = None) -> Any:
        """Reflect on the first parent using context-local dependencies."""
        parent = _first_parent(parents)
        if context is None:
            raise ValueError("Reflection operators require an OperatorContext.")
        return self(parent, context.component_pool, context.config)


def _parent_list(parents: Any) -> list[Any]:
    """Normalize one parent payload to a list."""
    if parents is None:
        return []
    if isinstance(parents, (list, tuple)):
        return list(parents)
    return [parents]


def _first_parent(parents: Any) -> Any:
    """Return the first parent from a parent payload."""
    parent_list = _parent_list(parents)
    if not parent_list:
        raise ValueError("Operator requires at least one parent.")
    return parent_list[0]
