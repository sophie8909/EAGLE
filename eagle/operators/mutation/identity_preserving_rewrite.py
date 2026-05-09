"""Identity-preserving rewrite mutation mode plugin."""

from __future__ import annotations

import random

from eagle.evolution.component.individual import Individual
from eagle.operators.mutation import support
from eagle.operators.mutation.strategy_mode import BaseStrategyMutationMode


class IdentityPreservingRewriteMutation(BaseStrategyMutationMode):
    """Rewrite dependent strategy components while preserving identity."""

    name = "identity_preserving_rewrite"
    mutation_mode = "identity_preserving_rewrite"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return an individual mutated by identity-preserving rewrite."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        updated_strategy = self._current_strategy(individual, component_pool)
        strategy_identity_key = support.identity_key(component_pool)
        old_identity = support.component_index(updated_strategy, strategy_identity_key)
        available_targets = support.dependent_targets(component_pool)

        if not available_targets:
            metadata = support.build_metadata(
                mutation_mode="identity_preserving_rewrite",
                changed_components=[],
                old_identity=old_identity,
                new_identity=support.component_index(updated_strategy, strategy_identity_key),
                repair_triggered=False,
                rewrite_prompt_summary=(
                    "identity_preserving_rewrite: no available dependent targets"
                ),
            )
            return self._finish_strategy_mutation(
                individual,
                component_pool,
                updated_strategy,
                metadata,
                0.0,
            )

        target_count = min(len(available_targets), 1 if random.random() < 0.7 else 2)
        selected_targets = random.sample(available_targets, k=target_count)
        updated_strategy, rewrite_summary, elapsed = support.rewrite_targets(
            updated_strategy,
            component_pool,
            selected_targets,
            mode_name="identity_preserving_rewrite",
            purpose=(
                "Keep the configured identity component unchanged and rewrite only the selected dependent strategy components "
                "so they better fit the current identity and remain consistent with the other existing strategy components."
            ),
            preserve_identity=True,
        )
        metadata = support.build_metadata(
            mutation_mode="identity_preserving_rewrite",
            changed_components=selected_targets,
            old_identity=old_identity,
            new_identity=support.component_index(updated_strategy, strategy_identity_key),
            repair_triggered=False,
            rewrite_prompt_summary=rewrite_summary,
        )
        return self._finish_strategy_mutation(
            individual,
            component_pool,
            updated_strategy,
            metadata,
            elapsed,
        )
