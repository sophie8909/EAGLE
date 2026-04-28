"""Strategy mutation methods for the genetic algorithm."""

from __future__ import annotations

import random
import time
from typing import Any

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool
from .individual import Individual
from eagle.utils.llm import LLM


class Mutation:
    """Mutation operators over flattened prompt components."""

    STATIC_POOL_MUTATION_MODE = "static_pool_replacement"
    STATIC_REWRITE_MUTATION_MODE = "static_rewrite"
    _mutation_component_weights: dict[str, float] = {}
    _mutation_component_fail_counts: dict[str, int] = {}

    @classmethod
    def all_strategy_components(cls, component_pool: ComponentPool) -> list[str]:
        """Compatibility wrapper returning the active evolving component set."""
        return list(component_pool.evolving_component_keys)

    @classmethod
    def mutate_strategy(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        config: EAConfig,
        mode: str | None = None,
    ) -> Individual:
        """Dispatch one component mutation mode and attach mutation metadata."""
        mutated_individual = individual.copy()

        component_indices = cls._ensure_complete_strategy(
            cls._index_map(mutated_individual),
            component_pool,
        )

        mutated_individual.ea_llm_call_time = 0.0

        selected_mode = mode or cls._sample_mutation_mode(config)
        if selected_mode == "bitmask_flip":
            return cls.apply_enabled_bit_flip(mutated_individual, component_pool)

        if selected_mode == "pool_replacement":
            component_indices, metadata, elapsed = cls.apply_pool_replacement(
                component_indices,
                component_pool,
            )
        elif selected_mode == "identity_preserving_rewrite":
            component_indices, metadata, elapsed = cls.apply_identity_preserving_rewrite(
                component_indices,
                component_pool,
            )
        elif selected_mode == "identity_shift_rewrite":
            component_indices, metadata, elapsed = cls.apply_identity_shift_rewrite(
                component_indices,
                component_pool,
            )
        else:
            raise ValueError(f"Unsupported strategy mutation mode: {selected_mode}")

        completed_indices = cls._ensure_complete_strategy(component_indices, component_pool)

        for key, value in completed_indices.items():
            mutated_individual.set_component_index(key, value)

        mutated_individual._sync_component_indices()
        mutated_individual.ea_llm_call_time += elapsed
        mutated_individual.mutation_metadata = metadata

        return mutated_individual

    @classmethod
    def apply_enabled_bit_flip(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
    ) -> Individual:
        """Flip 1 to 4 component-inclusion bits."""
        mutated_individual = individual.copy()

        if not component_pool.component_keys:
            mutated_individual.mutation_metadata = {
                "mutation_mode": "bitmask_flip",
                "changed_components": [],
                "flipped_indices": [],
            }
            return mutated_individual

        flip_count = random.randint(1, min(4, len(component_pool.component_keys)))
        flipped_indices = sorted(random.sample(range(len(component_pool.component_keys)), k=flip_count))
        flipped_components = [component_pool.component_keys[index] for index in flipped_indices]
        old_bits: list[int] = []
        new_bits: list[int] = []
        for component_key in flipped_components:
            old_bit, new_bit = mutated_individual.flip_component_enabled(component_key)
            old_bits.append(old_bit)
            new_bits.append(new_bit)

        mutated_individual.ea_llm_call_time = getattr(mutated_individual, "ea_llm_call_time", 0.0) or 0.0
        mutated_individual.mutation_metadata = {
            "mutation_mode": "bitmask_flip",
            "changed_components": flipped_components,
            "flipped_indices": flipped_indices,
            "old_bits": old_bits,
            "new_bits": new_bits,
        }
        return mutated_individual

    @classmethod
    def mutate_individual(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        config: EAConfig,
    ) -> Individual:
        """Mutate one flattened component from the config-enabled search space."""
        component_pool.configure_non_evolving_keys(
            getattr(config, "non_evolving_prompt_components", None)
        )
        return cls.mutate_strategy(individual, component_pool, config)

    @classmethod
    def mutate_static_component(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        static_targets: list[str],
    ) -> Individual:
        """Mutate one config-enabled static component via LLM rewrite."""
        mutated_individual = individual.copy()
        target_component = random.choice(list(static_targets))
        return cls.rewrite_static_component(
            mutated_individual,
            component_pool,
            target_component,
        )

    @classmethod
    def rewrite_static_component(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        target_component: str,
    ) -> Individual:
        """Rewrite one component while keeping the rest of the prompt stable."""
        mutated_individual = individual.copy()
        previous_index = mutated_individual.get_component_index(target_component)
        current_text = component_pool.get_component_str(target_component, previous_index)

        instruction = cls._build_static_rewrite_instruction(
            individual=mutated_individual,
            component_pool=component_pool,
            target_component=target_component,
        )

        rewritten_text, elapsed = cls.rewrite_component_with_llm(current_text, instruction)
        rewritten_component = component_pool.parse_rewritten_component(
            target_component,
            rewritten_text,
        )
        new_index = component_pool.add_component(target_component, rewritten_component)

        mutated_individual.set_component_index(target_component, new_index)
        mutated_individual._sync_component_indices()
        mutated_individual.ea_llm_call_time = (
            getattr(mutated_individual, "ea_llm_call_time", 0.0) or 0.0
        ) + elapsed
        mutated_individual.mutation_metadata = {
            "mutation_mode": cls.STATIC_REWRITE_MUTATION_MODE,
            "changed_components": [target_component],
            "old_index": previous_index,
            "new_index": new_index,
        }

        return mutated_individual

    @classmethod
    def apply_pool_replacement(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> tuple[dict[str, int], dict[str, Any], float]:
        """Replace one strategy component with another pool candidate."""
        updated_strategy = dict(strategy or {})
        allowed_targets = cls._allowed_pool_targets(component_pool)

        if not allowed_targets:
            return (
                updated_strategy,
                cls._build_metadata(
                    mutation_mode="pool_replacement",
                    changed_components=[],
                    old_identity=None,
                    new_identity=None,
                    repair_triggered=False,
                    rewrite_prompt_summary="pool_replacement: no active strategy targets",
                ),
                0.0,
            )

        target_component = random.choice(allowed_targets)
        identity_key = cls._identity_key(component_pool)
        old_identity = cls._component_index(updated_strategy, identity_key)

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

        if identity_key is not None and target_component == identity_key:
            repair_triggered = True
            dependent_targets = cls._dependent_targets(component_pool)
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
            new_identity=cls._component_index(updated_strategy, identity_key),
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
        identity_key = cls._identity_key(component_pool)
        old_identity = cls._component_index(updated_strategy, identity_key)
        available_targets = cls._dependent_targets(component_pool)

        if not available_targets:
            return (
                updated_strategy,
                cls._build_metadata(
                    mutation_mode="identity_preserving_rewrite",
                    changed_components=[],
                    old_identity=old_identity,
                    new_identity=cls._component_index(updated_strategy, identity_key),
                    repair_triggered=False,
                    rewrite_prompt_summary=(
                        "identity_preserving_rewrite: no available dependent targets"
                    ),
                ),
                0.0,
            )

        target_count = min(len(available_targets), 1 if random.random() < 0.7 else 2)
        selected_targets = random.sample(available_targets, k=target_count)

        updated_strategy, rewrite_summary, elapsed = cls._rewrite_targets(
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

        metadata = cls._build_metadata(
            mutation_mode="identity_preserving_rewrite",
            changed_components=selected_targets,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, identity_key),
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
        identity_key = cls._identity_key(component_pool)
        old_identity = cls._component_index(updated_strategy, identity_key)
        elapsed = 0.0

        identity_summary = "identity_shift_rewrite: no identity target configured"

        if identity_key is not None:
            updated_strategy, identity_summary, identity_elapsed = cls._rewrite_targets(
                updated_strategy,
                component_pool,
                [identity_key],
                mode_name="identity_shift_rewrite",
                purpose=(
                    f"Create a new {identity_key} with a clearly different overall strategic style. "
                    "Define aggression level, economy commitment, pressure timing, defense bias, "
                    "risk tolerance, and preferred win path."
                ),
                preserve_identity=False,
            )
            elapsed += identity_elapsed

        dependent_targets = cls._dependent_targets(component_pool)
        updated_strategy, dependent_summary, dependent_elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            dependent_targets,
            mode_name="identity_shift_rewrite",
            purpose=(
                "The configured identity component has changed. Rewrite the dependent strategy components so the whole strategy "
                "becomes coherent with the new identity across the active strategy component set."
            ),
            preserve_identity=True,
        )
        elapsed += dependent_elapsed

        metadata = cls._build_metadata(
            mutation_mode="identity_shift_rewrite",
            changed_components=([identity_key] if identity_key is not None else [])
            + dependent_targets,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, identity_key),
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
        identity_key = cls._identity_key(component_pool)
        old_identity = cls._component_index(updated_strategy, identity_key)
        repair_targets = cls._dependent_targets(component_pool)

        if not repair_targets:
            return (
                updated_strategy,
                cls._build_metadata(
                    mutation_mode="crossover_repair_rewrite",
                    changed_components=[],
                    old_identity=old_identity,
                    new_identity=cls._component_index(updated_strategy, identity_key),
                    repair_triggered=False,
                    rewrite_prompt_summary="crossover_repair_rewrite: no available repair targets",
                ),
                0.0,
            )

        updated_strategy, rewrite_summary, elapsed = cls._rewrite_targets(
            updated_strategy,
            component_pool,
            repair_targets,
            mode_name="crossover_repair_rewrite",
            purpose=(
                "This strategy may have been assembled from mixed parents or mixed pool components. "
                "Repair contradictions across the active strategy components so the result becomes coherent with the chosen identity component. "
                "Preserve useful inherited content where possible, but rewrite whatever is necessary for internal consistency."
            ),
            preserve_identity=True,
        )

        metadata = cls._build_metadata(
            mutation_mode="crossover_repair_rewrite",
            changed_components=repair_targets,
            old_identity=old_identity,
            new_identity=cls._component_index(updated_strategy, identity_key),
            repair_triggered=True,
            rewrite_prompt_summary=rewrite_summary,
        )

        return updated_strategy, metadata, elapsed

    @classmethod
    def repair_strategy_after_crossover(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
    ) -> Individual:
        """Repair one crossover child so its dependent components become coherent."""
        repaired_individual = individual.copy()
        component_indices = cls._ensure_complete_strategy(
            cls._index_map(repaired_individual),
            component_pool,
        )

        repaired_individual.ea_llm_call_time = (
            getattr(repaired_individual, "ea_llm_call_time", 0.0) or 0.0
        )

        component_indices, metadata, elapsed = cls.apply_crossover_repair_rewrite(
            component_indices,
            component_pool,
        )

        for key, value in cls._ensure_complete_strategy(
            component_indices,
            component_pool,
        ).items():
            repaired_individual.set_component_index(key, value)

        repaired_individual._sync_component_indices()
        repaired_individual.ea_llm_call_time += elapsed
        repaired_individual.mutation_metadata = metadata

        return repaired_individual

    @staticmethod
    def rewrite_component_with_llm(
        component: str,
        rewrite_instruction: str,
    ) -> tuple[str, float]:
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
    def _sample_mutation_mode(cls, config: EAConfig) -> str:
        """Sample one mutation mode from adaptive roulette weights."""
        configured_weights = config.strategy_mutation_mode_weights()
        modes = list(configured_weights.keys())
        if not modes:
            raise ValueError("No configured strategy mutation modes available.")

        for mode in modes:
            cls._mutation_component_weights.setdefault(mode, 1.0)
            cls._mutation_component_fail_counts.setdefault(mode, 0)

        mode_weights = [cls._mutation_component_weights[mode] for mode in modes]
        return random.choices(modes, weights=mode_weights, k=1)[0]

    @classmethod
    def update_mutation_component_feedback(
        cls,
        mutation_mode: str | None,
        improved: bool,
    ) -> None:
        """Update roulette statistics for one mutation component based on outcome."""
        if not mutation_mode:
            return

        weight = float(cls._mutation_component_weights.get(mutation_mode, 1.0))
        fail_count = int(cls._mutation_component_fail_counts.get(mutation_mode, 0))

        if improved:
            weight *= 1.25
            fail_count = 0
        else:
            weight *= 0.85
            fail_count += 1

        if fail_count >= 3:
            weight = 1.0
            fail_count = 0

        weight = min(10.0, max(1.0, weight))
        cls._mutation_component_weights[mutation_mode] = weight
        cls._mutation_component_fail_counts[mutation_mode] = fail_count

    @classmethod
    def _allowed_pool_targets(cls, component_pool: ComponentPool) -> list[str]:
        """Return strategy buckets that are eligible for discrete pool replacement."""
        return list(component_pool.evolving_component_keys)

    @staticmethod
    def _identity_key(component_pool: ComponentPool) -> str | None:
        """Return the active strategy identity key from the component pool metadata."""
        identity_key = getattr(component_pool, "identity_component_key", None)
        if identity_key in getattr(component_pool, "evolving_component_keys", []):
            return identity_key
        return None

    @classmethod
    def _dependent_targets(cls, component_pool: ComponentPool) -> list[str]:
        """Return strategy rewrite targets derived from the loaded component JSON."""
        configured = list(getattr(component_pool, "dependent_strategy_keys", []) or [])

        if configured:
            return [
                target
                for target in configured
                if target in component_pool.evolving_component_keys
            ]

        identity_key = cls._identity_key(component_pool)
        return [
            target
            for target in component_pool.evolving_component_keys
            if target != identity_key
        ]

    @classmethod
    def _ensure_complete_strategy(
        cls,
        strategy: dict[str, int],
        component_pool: ComponentPool,
    ) -> dict[str, int]:
        """Ensure every active evolving component has a valid selected candidate."""
        completed = {
            str(key): cls._coerce_index(value)
            for key, value in dict(strategy or {}).items()
        }

        for component_key in component_pool.evolving_component_keys:
            if component_key not in completed:
                completed[component_key] = component_pool.get_random_component_index(
                    component_key
                )

        return completed

    @staticmethod
    def _coerce_index(value: Any) -> int:
        if isinstance(value, dict):
            value = value.get("index", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _index_map(cls, individual: Individual) -> dict[str, int]:
        return {
            key: cls._coerce_index(value)
            for key, value in dict(getattr(individual, "component_indices", {}) or {}).items()
        }

    @classmethod
    def _sample_replacement_index(
        cls,
        component_pool: ComponentPool,
        strategy_key: str,
        current_index: int | None,
    ) -> int:
        """Sample a replacement index, preferring a different candidate when possible."""
        candidates = component_pool.components[strategy_key]

        if len(candidates) <= 1:
            return 0 if current_index is None else int(current_index)

        replacement_index = component_pool.get_random_component_index(strategy_key)

        if current_index is None:
            return replacement_index

        for _ in range(8):
            if replacement_index != current_index:
                return replacement_index
            replacement_index = component_pool.get_random_component_index(strategy_key)

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

            rewritten_component = component_pool.parse_rewritten_component(
                target,
                rewritten_text,
            )
            new_index = component_pool.add_component(target, rewritten_component)

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
        identity_key = cls._identity_key(component_pool)
        identity_text = cls._component_text(component_pool, strategy, identity_key)

        unchanged_components = [
            key for key in component_pool.component_keys if key != target_component
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
            f"- Active component keys loaded from JSON: {', '.join(component_pool.component_keys)}.\n"
            f"- Identity key loaded from JSON: {identity_key or 'none'}.\n"
            "- Keep the rewritten component coherent with the active strategy keys and their current meanings.\n\n"
            "Global rewrite constraints:\n"
            "1. Modify only the allowed strategy component named above.\n"
            "2. Preserve all non-strategy sections completely.\n"
            "3. Preserve JSON schema and action definitions completely.\n"
            "4. The rewritten component must become MORE specific, MORE detailed, and MORE operational than the original.\n"
            "5. Do not summarize, shorten, generalize, or weaken the strategy.\n"
            "6. Add concrete decision rules, trigger conditions, priorities, and fallback behavior where appropriate.\n"
            "7. Mention specific MicroRTS concepts when useful: workers, bases, barracks, resources, light/heavy/ranged units, enemy base, enemy workers, combat units, idle units.\n"
            "8. Avoid vague phrases such as 'play carefully', 'balance economy and army', 'adapt to the situation', 'make good decisions', or 'attack when ready' unless they are followed by concrete conditions.\n"
            "9. Prefer explicit if-then rules, ordered priorities, and phase-specific actions.\n"
            "10. Keep the rewritten text compatible with the unchanged components.\n"
            f"11. {'Preserve the identity component exactly as written.' if preserve_identity else 'You may change the identity component because this is an identity shift.'}\n\n"
            f"Current identity component ({identity_key or 'none'}):\n{identity_text}\n\n"
            f"Current strategy snapshot:\n{strategy_snapshot}\n\n"
            f"Unchanged strategy components to stay consistent with:\n{unchanged_snapshot}\n\n"
            "Output requirements:\n"
            "- Return 3 to 7 bullet points or short imperative rules.\n"
            "- Each bullet must contain at least one concrete condition, target, or action.\n"
            "- Do not return a high-level paragraph.\n"
            "- Do not use generic strategy language without MicroRTS-specific details.\n\n"
            f"Return only the rewritten text for [{target_component}] with no explanation."
        )

    @classmethod
    def _build_static_rewrite_instruction(
        cls,
        *,
        individual: Individual,
        component_pool: ComponentPool,
        target_component: str,
    ) -> str:
        """Assemble the rewrite prompt for one non-strategy component."""
        static_snapshot = cls._format_static_snapshot(
            individual,
            component_pool,
            exclude={target_component},
        )
        strategy_snapshot = cls._format_strategy_snapshot(
            individual.component_indices,
            component_pool,
        )
        current_text = component_pool.get_component_str(
            target_component,
            individual.get_component_index(target_component),
        )

        return (
            "Mutation mode: static_rewrite\n"
            f"Rewrite target: {target_component}\n\n"
            "Goal:\n"
            "- Rewrite only the named non-strategy component.\n"
            "- Keep the overall agent style and intent consistent with the current strategy components.\n"
            "- Preserve compatibility with the rest of the prompt.\n"
            "- Do not rewrite examples or field requirement sections.\n"
            "- Keep the result concrete and operational rather than generic.\n\n"
            f"Current target text:\n[{target_component}]\n{current_text}\n\n"
            f"Other static components to stay consistent with:\n{static_snapshot}\n\n"
            f"Current strategy snapshot:\n{strategy_snapshot}\n\n"
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
        for key in component_pool.component_keys:
            blocks.append(f"[{key}]\n{cls._component_text(component_pool, strategy, key)}")
        return "\n\n".join(blocks)

    @classmethod
    def _format_static_snapshot(
        cls,
        individual: Individual,
        component_pool: ComponentPool,
        *,
        exclude: set[str] | None = None,
    ) -> str:
        """Render selected components into a readable rewrite context."""
        excluded = set(exclude or set())
        blocks: list[str] = []

        for key in component_pool.component_keys:
            if key in excluded:
                continue
            if key not in individual.component_indices:
                continue

            component_index = individual.get_component_index(key)
            blocks.append(
                f"[{key}]\n{component_pool.get_component_str(key, component_index)}"
            )

        return "\n\n".join(blocks)

    @classmethod
    def _component_text(
        cls,
        component_pool: ComponentPool,
        strategy: dict[str, int],
        strategy_key: str | None,
    ) -> str:
        """Read one strategy component as a newline-joined text block."""
        if strategy_key is None:
            return ""

        index = cls._coerce_index(strategy.get(strategy_key))

        if strategy_key not in strategy:
            return ""

        try:
            return "\n".join(component_pool.get_component(strategy_key, int(index)))
        except (IndexError, KeyError, ValueError):
            return "\n".join(component_pool.get_component(strategy_key, 0))

    @staticmethod
    def _component_index(
        strategy: dict[str, int],
        strategy_key: str | None,
    ) -> int | None:
        """Return one selected component index from the strategy dict."""
        if strategy_key is None:
            return None
        if strategy_key not in dict(strategy or {}):
            return None
        return Mutation._coerce_index(dict(strategy or {}).get(strategy_key))

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
