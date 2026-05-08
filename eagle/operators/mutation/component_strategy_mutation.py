"""Default component-strategy mutation plugin."""

from __future__ import annotations

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseMutation
from eagle.operators.component.mutation import Mutation


class ComponentStrategyMutation(BaseMutation):
    """Apply the existing adaptive component mutation strategy."""

    name = "component_strategy_mutation"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return a mutated copy of one individual."""
        return Individual.from_existing(
            Mutation.mutate_individual(
                individual,
                component_pool,
                config,
            )
        )

    def update_feedback(self, mutation_mode: str | None, improved: bool) -> None:
        """Forward adaptive mutation feedback to the underlying strategy."""
        Mutation.update_mutation_component_feedback(mutation_mode, improved)
