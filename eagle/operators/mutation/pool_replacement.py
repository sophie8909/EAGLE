"""Pool-replacement mutation mode plugin."""

from __future__ import annotations

import random

from eagle.evolution.component.individual import Individual
from eagle.operators.mutation import support
from eagle.operators.mutation.strategy_mode import BaseStrategyMutationMode


class PoolReplacementMutation(BaseStrategyMutationMode):
    """Replace one strategy component with another component-pool candidate."""

    name = "pool_replacement"
    mutation_mode = "pool_replacement"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return an individual mutated by pool replacement."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        updated_strategy = self._current_strategy(individual, component_pool)
        allowed_targets = support.allowed_pool_targets(component_pool)

        if not allowed_targets:
            metadata = support.build_metadata(
                mutation_mode="pool_replacement",
                changed_components=[],
                old_identity=None,
                new_identity=None,
                repair_triggered=False,
                rewrite_prompt_summary="pool_replacement: no active strategy targets",
            )
            return self._finish_strategy_mutation(
                individual,
                component_pool,
                updated_strategy,
                metadata,
                0.0,
            )

        target_component = random.choice(allowed_targets)
        strategy_identity_key = support.identity_key(component_pool)
        old_identity = support.component_index(updated_strategy, strategy_identity_key)
        replacement_index = support.sample_replacement_index(
            component_pool,
            target_component,
            updated_strategy.get(target_component),
        )
        updated_strategy[target_component] = replacement_index

        changed_components = [target_component]
        repair_triggered = False
        rewrite_prompt_summary = ""
        elapsed = 0.0

        if strategy_identity_key is not None and target_component == strategy_identity_key:
            repair_triggered = True
            repair_targets = support.dependent_targets(component_pool)
            updated_strategy, rewrite_prompt_summary, elapsed = support.rewrite_targets(
                updated_strategy,
                component_pool,
                repair_targets,
                mode_name="crossover_repair_rewrite",
                purpose=(
                    "The strategy identity was replaced by pool mutation. "
                    "Repair the dependent strategy components so they become coherent with the new identity."
                ),
                preserve_identity=True,
            )
            changed_components.extend(
                target for target in repair_targets if target not in changed_components
            )

        metadata = support.build_metadata(
            mutation_mode="pool_replacement",
            changed_components=changed_components,
            old_identity=old_identity,
            new_identity=support.component_index(updated_strategy, strategy_identity_key),
            repair_triggered=repair_triggered,
            rewrite_prompt_summary=rewrite_prompt_summary,
        )
        return self._finish_strategy_mutation(
            individual,
            component_pool,
            updated_strategy,
            metadata,
            elapsed,
        )
