"""Enabled-bit mutation plugin."""

from __future__ import annotations

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseMutation
from eagle.operators.component.mutation import Mutation


class BitmaskFlipMutation(BaseMutation):
    """Flip one component enabled bit on a copied individual."""

    name = "bitmask_flip"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return a copied individual with one enabled bit flipped."""
        child = Individual.from_existing(individual)
        return Individual.from_existing(
            Mutation.apply_enabled_bit_flip(child, component_pool)
        )
