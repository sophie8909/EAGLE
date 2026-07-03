"""Identity-shift rewrite mutation mode plugin."""

from __future__ import annotations

from eagle.evolution.component.individual import Individual
from eagle.operators.mutation import support
from eagle.operators.mutation.strategy_mode import BaseStrategyMutationMode


class IdentityShiftRewriteMutation(BaseStrategyMutationMode):
    """Rewrite the strategy identity and dependent components."""

    name = "identity_shift_rewrite"
    mutation_mode = "identity_shift_rewrite"

    def __call__(self, individual, component_pool, config) -> Individual:
        """Return an individual mutated by identity-shift rewrite."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        updated_strategy = self._current_strategy(individual, component_pool)
        strategy_identity_key = support.identity_key(component_pool)
        old_identity = support.component_index(updated_strategy, strategy_identity_key)
        elapsed = 0.0
        identity_summary = "identity_shift_rewrite: no identity target configured"

        if strategy_identity_key is not None:
            updated_strategy, identity_summary, identity_elapsed = support.rewrite_targets(
                updated_strategy,
                component_pool,
                [strategy_identity_key],
                mode_name="identity_shift_rewrite",
                purpose=(
                    f"Create a new {strategy_identity_key} with a clearly different overall strategic style. "
                    "Define aggression level, economy commitment, pressure timing, defense bias, "
                    "risk tolerance, and preferred win path."
                ),
                preserve_identity=False,
            )
            elapsed += identity_elapsed

        repair_targets = support.dependent_targets(component_pool)
        updated_strategy, dependent_summary, dependent_elapsed = support.rewrite_targets(
            updated_strategy,
            component_pool,
            repair_targets,
            mode_name="identity_shift_rewrite",
            purpose=(
                "The configured identity component has changed. Rewrite the dependent strategy components so the whole strategy "
                "becomes coherent with the new identity across the active strategy component set."
            ),
            preserve_identity=True,
        )
        elapsed += dependent_elapsed

        metadata = support.build_metadata(
            mutation_mode="identity_shift_rewrite",
            changed_components=(
                [strategy_identity_key] if strategy_identity_key is not None else []
            )
            + repair_targets,
            old_identity=old_identity,
            new_identity=support.component_index(updated_strategy, strategy_identity_key),
            repair_triggered=True,
            rewrite_prompt_summary=f"{identity_summary} | {dependent_summary}",
        )
        return self._finish_strategy_mutation(
            individual,
            component_pool,
            updated_strategy,
            metadata,
            elapsed,
        )
