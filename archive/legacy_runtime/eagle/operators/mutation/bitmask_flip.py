"""Enabled-bit mutation plugin."""

from __future__ import annotations

import random

from eagle.evolution.component.individual import Individual
from eagle.operators.base import BaseMutation


class BitmaskFlipMutation(BaseMutation):
    """Flip one component enabled bit on a copied individual."""

    name = "bitmask_flip"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return a copied individual with one enabled bit flipped."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        mutated_individual = Individual.from_existing(individual)
        mutable_components = list(getattr(component_pool, "component_keys", []) or [])

        if not mutable_components:
            mutated_individual.mutation_metadata = {
                "mutation_mode": "bitmask_flip",
                "changed_components": [],
                "flipped_indices": [],
            }
            return mutated_individual

        flip_count = random.randint(1, min(4, len(mutable_components)))
        flipped_components = random.sample(mutable_components, k=flip_count)
        flipped_indices = sorted(
            component_pool.component_keys.index(key) for key in flipped_components
        )
        old_bits: list[int] = []
        new_bits: list[int] = []
        for component_key in flipped_components:
            old_bit, new_bit = mutated_individual.flip_component_enabled(component_key)
            old_bits.append(old_bit)
            new_bits.append(new_bit)

        mutated_individual.ea_llm_call_time = (
            getattr(mutated_individual, "ea_llm_call_time", 0.0) or 0.0
        )
        mutated_individual.mutation_metadata = {
            "mutation_mode": "bitmask_flip",
            "changed_components": flipped_components,
            "flipped_indices": flipped_indices,
            "old_bits": old_bits,
            "new_bits": new_bits,
        }
        return mutated_individual
