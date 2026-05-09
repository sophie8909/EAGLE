"""Shared base class for strategy mutation mode plugins."""

from __future__ import annotations

from eagle.operators.base import BaseMutation
from eagle.operators.mutation import support


class BaseStrategyMutationMode(BaseMutation):
    """Base class for mutation modes that update component indices."""

    mutation_mode: str = ""

    def _current_strategy(self, individual, component_pool) -> dict[str, int]:
        """Return a complete mutable strategy index map for one individual."""
        return support.current_strategy(individual, component_pool)

    def _finish_strategy_mutation(
        self,
        individual,
        component_pool,
        component_indices: dict[str, int],
        metadata: dict,
        elapsed: float,
    ):
        """Copy the individual, apply component indices, and attach metadata."""
        return support.finish_strategy_mutation(
            individual,
            component_pool,
            component_indices,
            metadata,
            elapsed,
        )
