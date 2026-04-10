"""Strategy mutation methods for the genetic algorithm."""

from __future__ import annotations

import random
import time
from typing import Any

from ..tools.component_pool import ComponentPool
from ..config import EAConfig
from ..tools.individual import Individual
from ..tools.llm import LLM


class Mutation:
    """Mutation operators centered around strategy identity and phase coherence."""

    IDENTITY_KEY = "strategy_identity"
    DEPENDENT_COMPONENTS = [
        "phase_transition_rule",
        "early_game_plan",
        "mid_game_plan",
        "late_game_plan",
        "decision_priority",
    ]
    WEAKLY_DEPENDENT_COMPONENTS = [
        "tactical_heuristics",
        "anti_stall_rules",
    ]

    @classmethod
    def all_strategy_components(cls) -> list[str]:
        """Return the full ordered strategy component set."""
        return [
            cls.IDENTITY_KEY,
            *cls.DEPENDENT_COMPONENTS,
            *cls.WEAKLY_DEPENDENT_COMPONENTS,
        ]

    @staticmethod
    def rewrite_component_with_llm(component: str, rewrite_instruction: str) -> tuple[str, float]:
        """Rewrite one strategy component through the LLM and time the call."""
        start = time.perf_counter()
        try:
            rewritten_component = LLM.ollama_rewrite_component(
                original_text=component,
                instruction=rewrite_instruction,
                model="llama3.1:8b",
            )
        except Exception:
            rewritten_component = component
        elapsed = time.perf_counter() - start
        return rewritten_component, elapsed

    @classmethod
    def mutate_strategy(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        config: EAConfig,
        mode: str | None = None,
    ) -> Individual:
        """Dispatch one strategy mutation mode and attach mutation metadata."""
        mutated_individual = individual.copy()
        mutated_individual.strategy = cls._ensure_complete_strategy(
            dict(mutated_individual.strategy or {}),
            component_pool,
        )
        mutated_individual.ea_llm_call_time = 0.0

        selected_mode = mode or cls._sample_mutation_mode(config)
        if selected_mode == "pool_replacement":
            strategy, metadata, elapsed = cls.apply_pool_replacement(
                mutated_individual.strategy,
                component_pool,
            )
        elif selected_mode == "identity_preserving_rewrite":
            strategy, metadata, elapsed = cls.apply_identity_preserving_rewrite(
                mutated_individual.strategy,
                component_pool,
            )
        elif selected_mode == "identity_shift_rewrite":
            strategy, metadata, elapsed = cls.apply_identity_shift_rewrite(
                mutated_individual.strategy,
                component_pool,
            )
        elif selected_mode == "crossover_repair_rewrite":
            strategy, metadata, elapsed = cls.apply_crossover_repair_rewrite(
                mutated_individual.strategy,
                component_pool,
            )
        else:
            raise ValueError(f"Unsupported strategy mutation mode: {selected_mode}")

        mutated_individual.strategy = cls._ensure_complete_strategy(strategy, component_pool)
        mutated_individual.ea_llm_call_time += elapsed
        mutated_individual.mutation_metadata = metadata
        return mutated_individual

    @classmethod
    def apply_pool_replacement(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> tuple[dict[str, int], dict[str, Any], float]:
        """Replace one strategy component with another pool candidate."""
        updated_strategy = dict(strategy or {})
        target_component = random.choice(cls._allowed_pool_targets(component_pool))
        old_identity = cls._component_index(updated_strategy, cls.IDENTITY_KEY)
        replacement_index = cls._sample_replacement_index(
            component_pool,
            target_component,
            updated_strategy.get(target_component),
        )
        updated_strategy[target_component] = replacement_index

        changed_components = [target_component]
        repair_triggered = False
        rewrite_prompt_summary = ""
        elapsed = 0.0

        if target_component == cls.IDENTITY_KEY:
            repair_triggered = True
            dependent_targets = list(cls.DEPENDENT_COMPONENTS)
            updated_strategy, rewrite_summary, repair_elapsed = cls._rewrite_targets(
                updated_strategy,
                component_pool,
                dependent_targets,
                mode_name="crossover_repair_rewrite",
                purpose=(
                    "The strategy identity was replaced by pool mutation. "
                    "Repair the dependent strategy components so they become coherent with the new identity."
                ),
                preserve_identity=True,
            )
            elapsed += repair_elapsed
            rewrite_prompt_summary = rewrite_summary
            changed_components.extend(
                target for target in dependent_targets if target not in changed_components
            )

        metadata = cls._build_metadata(
            mutation_mode="pool_replacement",
            changed_components=changed_components,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, cls.IDENTITY_KEY),
            repair_triggered=repair_triggered,
            rewrite_prompt_summary=rewrite_prompt_summary,
        )
        return updated_strategy, metadata, elapsed

    @classmethod
    def apply_identity_preserving_rewrite(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> tuple[dict[str, int], dict[str, Any], float]:
        """Rewrite dependent components while keeping the current identity fixed."""
        updated_strategy = dict(strategy or {})
        old_identity = cls._component_index(updated_strategy, cls.IDENTITY_KEY)
        target_count = 1 if random.random() < 0.7 else 2
        selected_targets = random.sample(cls.DEPENDENT_COMPONENTS, k=target_count)
        updated_strategy, rewrite_summary, elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            selected_targets,
            mode_name="identity_preserving_rewrite",
            purpose=(
                "Keep strategy_identity unchanged and rewrite only the selected dependent strategy components "
                "so they better fit the current identity and remain consistent with the other existing strategy components."
            ),
            preserve_identity=True,
        )
        metadata = cls._build_metadata(
            mutation_mode="identity_preserving_rewrite",
            changed_components=selected_targets,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, cls.IDENTITY_KEY),
            repair_triggered=False,
            rewrite_prompt_summary=rewrite_summary,
        )
        return updated_strategy, metadata, elapsed

    @classmethod
    def apply_identity_shift_rewrite(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> tuple[dict[str, int], dict[str, Any], float]:
        """Rewrite strategy identity first, then rewrite dependent components to match it."""
        updated_strategy = dict(strategy or {})
        old_identity = cls._component_index(updated_strategy, cls.IDENTITY_KEY)
        elapsed = 0.0

        updated_strategy, identity_summary, identity_elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            [cls.IDENTITY_KEY],
            mode_name="identity_shift_rewrite",
            purpose=(
                "Create a new strategy_identity with a clearly different overall strategic style. "
                "The new identity should define aggression level, economy commitment, pressure timing, defense bias, "
                "risk tolerance, and preferred win path."
            ),
            preserve_identity=False,
        )
        elapsed += identity_elapsed

        dependent_targets = list(cls.DEPENDENT_COMPONENTS)
        updated_strategy, dependent_summary, dependent_elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            dependent_targets,
            mode_name="identity_shift_rewrite",
            purpose=(
                "The strategy_identity has changed. Rewrite the dependent strategy components so the whole strategy "
                "becomes coherent with the new identity across phase transition, early game, mid game, late game, "
                "and decision priority."
            ),
            preserve_identity=True,
        )
        elapsed += dependent_elapsed

        metadata = cls._build_metadata(
            mutation_mode="identity_shift_rewrite",
            changed_components=[cls.IDENTITY_KEY, *dependent_targets],
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, cls.IDENTITY_KEY),
            repair_triggered=True,
            rewrite_prompt_summary=f"{identity_summary} | {dependent_summary}",
        )
        return updated_strategy, metadata, elapsed

    @classmethod
    def apply_crossover_repair_rewrite(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> tuple[dict[str, int], dict[str, Any], float]:
        """Repair a mixed strategy so it becomes coherent with its chosen identity."""
        updated_strategy = dict(strategy or {})
        old_identity = cls._component_index(updated_strategy, cls.IDENTITY_KEY)
        repair_targets = list(cls.DEPENDENT_COMPONENTS)
        updated_strategy, rewrite_summary, elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            repair_targets,
            mode_name="crossover_repair_rewrite",
            purpose=(
                "This strategy may have been assembled from mixed parents or mixed pool components. "
                "Repair contradictions across phase plans and decision priority so the result becomes coherent with the chosen strategy_identity. "
                "Preserve useful inherited content where possible, but rewrite whatever is necessary for internal consistency."
            ),
            preserve_identity=True,
        )
        metadata = cls._build_metadata(
            mutation_mode="crossover_repair_rewrite",
            changed_components=repair_targets,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, cls.IDENTITY_KEY),
            repair_triggered=True,
            rewrite_prompt_summary=rewrite_summary,
        )
        return updated_strategy, metadata, elapsed

    @classmethod
    def mutate_component_from_pool(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        mutation_rate: float,
    ) -> Individual:
        """Backward-compatible wrapper for the cheap discrete pool mutation."""
        if mutation_rate <= 0:
            return individual
        config = EAConfig(
            mutation_rate=mutation_rate,
            strategy_mutation_pool_replacement_prob=1.0,
            strategy_mutation_identity_preserving_rewrite_prob=0.0,
            strategy_mutation_identity_shift_rewrite_prob=0.0,
            strategy_mutation_crossover_repair_rewrite_prob=0.0,
        )
        return cls.mutate_strategy(individual, component_pool, config, mode="pool_replacement")

    @classmethod
    def mutate_component_with_llm(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        mutation_rate: float,
    ) -> Individual:
        """Backward-compatible wrapper that samples among the rewrite-based modes."""
        if mutation_rate <= 0:
            return individual
        config = EAConfig(
            mutation_rate=mutation_rate,
            strategy_mutation_pool_replacement_prob=0.0,
            strategy_mutation_identity_preserving_rewrite_prob=0.58,
            strategy_mutation_identity_shift_rewrite_prob=0.25,
            strategy_mutation_crossover_repair_rewrite_prob=0.17,
        )
        return cls.mutate_strategy(individual, component_pool, config)

    @classmethod
    def _sample_mutation_mode(cls, config: EAConfig) -> str:
        """Sample one mutation mode from the configured strategy-mutation weights."""
        weights = config.strategy_mutation_mode_weights()
        modes = list(weights.keys())
        probabilities = [weights[mode] for mode in modes]
        return random.choices(modes, weights=probabilities, k=1)[0]

    @classmethod
    def _allowed_pool_targets(cls, component_pool: ComponentPool) -> list[str]:
        """Return strategy buckets that are eligible for discrete pool replacement."""
        return [
            key for key in cls.all_strategy_components()
            if key in component_pool.strategy_keys
        ]

    @classmethod
    def _ensure_complete_strategy(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> dict[str, int]:
        """Ensure every active strategy bucket has a valid selected candidate."""
        completed = dict(strategy or {})
        for strategy_key in component_pool.strategy_keys:
            if strategy_key not in completed:
                completed[strategy_key] = component_pool.get_random_strategy_component_index(strategy_key)
        return completed

    @classmethod
    def _sample_replacement_index(
        cls,
        component_pool: ComponentPool,
        strategy_key: str,
        current_index: int | None,
    ) -> int:
        """Sample a replacement index, preferring a different candidate when possible."""
        candidates = component_pool.components["strategy"][strategy_key]
        if len(candidates) <= 1:
            return 0 if current_index is None else current_index

        replacement_index = component_pool.get_random_strategy_component_index(strategy_key)
        if current_index is None:
            return replacement_index
        for _ in range(8):
            if replacement_index != current_index:
                return replacement_index
            replacement_index = component_pool.get_random_strategy_component_index(strategy_key)
        return replacement_index

    @classmethod
    def _rewrite_targets(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
        targets: list[str],
        *,
        mode_name: str,
        purpose: str,
        preserve_identity: bool,
    ) -> tuple[dict[str, int], str, float]:
        """Rewrite one or more strategy components using the LLM with full strategy context."""
        updated_strategy = dict(strategy or {})
        total_elapsed = 0.0
        rewritten_targets: list[str] = []

        for target in targets:
            current_text = cls._component_text(component_pool, updated_strategy, target)
            instruction = cls._build_rewrite_instruction(
                strategy=updated_strategy,
                component_pool=component_pool,
                target_component=target,
                mode_name=mode_name,
                purpose=purpose,
                preserve_identity=preserve_identity,
            )
            rewritten_text, elapsed = cls.rewrite_component_with_llm(
                current_text,
                instruction,
            )
            total_elapsed += elapsed
            rewritten_component = component_pool.parse_component_str(rewritten_text)
            new_index = component_pool.add_strategy_component(target, rewritten_component)
            updated_strategy[target] = new_index
            rewritten_targets.append(target)

        summary = f"{mode_name}: rewrote {', '.join(rewritten_targets)}"
        return updated_strategy, summary, total_elapsed

    @classmethod
    def _build_rewrite_instruction(
        cls,
        *,
        strategy: dict[str, int],
        component_pool: ComponentPool,
        target_component: str,
        mode_name: str,
        purpose: str,
        preserve_identity: bool,
    ) -> str:
        """Assemble the rewrite constraints used by all rewrite-based mutations."""
        strategy_snapshot = cls._format_strategy_snapshot(strategy, component_pool)
        identity_text = cls._component_text(component_pool, strategy, cls.IDENTITY_KEY)
        unchanged_components = [
            key for key in component_pool.strategy_keys
            if key != target_component
        ]
        unchanged_snapshot = "\n\n".join(
            f"[{key}]\n{cls._component_text(component_pool, strategy, key)}"
            for key in unchanged_components
        )

        return (
            f"Mutation mode: {mode_name}\n"
            f"Rewrite target: {target_component}\n"
            f"Purpose: {purpose}\n\n"
            "Strategy component design:\n"
            "- strategy_identity is the top-level style controller.\n"
            "- phase_transition_rule decides early/mid/late using state-based conditions over rigid turn thresholds.\n"
            "- early_game_plan, mid_game_plan, and late_game_plan should each integrate economy, production, combat, and pressure naturally.\n"
            "- decision_priority defines real-time priority when goals conflict.\n"
            "- tactical_heuristics and anti_stall_rules are stabilizers, not primary style drivers.\n\n"
            "Global rewrite constraints:\n"
            "1. Modify only the allowed strategy component named above.\n"
            "2. Preserve all non-strategy sections completely.\n"
            "3. Preserve JSON schema and action definitions completely.\n"
            "4. Keep the rewritten text concrete, operational, and actionable.\n"
            "5. Avoid vague generic advice.\n"
            "6. Avoid contradictions with unchanged strategy components.\n"
            "7. Keep tactical_heuristics and anti_stall_rules as stabilizers, not style drivers.\n"
            f"8. {'Preserve strategy_identity exactly as written.' if preserve_identity else 'You may change strategy_identity because this is an identity shift.'}\n\n"
            f"Current strategy_identity:\n{identity_text}\n\n"
            f"Current strategy snapshot:\n{strategy_snapshot}\n\n"
            f"Unchanged strategy components to stay consistent with:\n{unchanged_snapshot}\n\n"
            f"Return only the rewritten text for [{target_component}] with no explanation."
        )

    @classmethod
    def _format_strategy_snapshot(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> str:
        """Render the current strategy dictionary into a readable rewrite context."""
        blocks = []
        for key in component_pool.strategy_keys:
            blocks.append(f"[{key}]\n{cls._component_text(component_pool, strategy, key)}")
        return "\n\n".join(blocks)

    @classmethod
    def _component_text(
        cls,
        component_pool: ComponentPool,
        strategy: dict[str, int],
        strategy_key: str,
    ) -> str:
        """Read one strategy component as a newline-joined text block."""
        index = strategy.get(strategy_key)
        if index is None:
            return ""
        return "\n".join(component_pool.get_strategy_component(strategy_key, index))

    @staticmethod
    def _component_index(strategy: dict[str, int], strategy_key: str) -> int | None:
        """Return one selected component index from the strategy dict."""
        return dict(strategy or {}).get(strategy_key)

    @staticmethod
    def _build_metadata(
        *,
        mutation_mode: str,
        changed_components: list[str],
        old_identity: int | None,
        new_identity: int | None,
        repair_triggered: bool,
        rewrite_prompt_summary: str,
    ) -> dict[str, Any]:
        """Build mutation metadata for analysis and debugging."""
        return {
            "mutation_mode": mutation_mode,
            "changed_components": changed_components,
            "old_identity": old_identity,
            "new_identity": new_identity,
            "repair_triggered": repair_triggered,
            "rewrite_prompt_summary": rewrite_prompt_summary,
        }
