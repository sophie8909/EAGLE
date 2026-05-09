"""Weighted mutation-mode plugin."""

from __future__ import annotations

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseMutation
from eagle.operators.mutation import support


class MixMutation(BaseMutation):
    """Sample one registered mutation operator according to adaptive weights."""

    name = "mix"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return an individual mutated by one weighted mutation operator."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        selected_mode = support.sample_mutation_mode(config)

        from eagle.operators.registry import get_operator

        mutation_operator = get_operator("mutation", selected_mode)
        return Individual.from_existing(
            mutation_operator(individual, component_pool, config)
        )

    def update_feedback(self, mutation_mode: str | None, improved: bool) -> None:
        """Forward adaptive mutation feedback to the weighted mutation state."""
        support.update_mutation_component_feedback(mutation_mode, improved)
