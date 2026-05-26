"""Shared helpers used by mutation operator plugins."""

from __future__ import annotations

import random
import time
from copy import deepcopy
from typing import Any

from eagle.evolution.component.individual import Individual
from eagle.llm import LLM


MIXABLE_MUTATION_OPERATORS: tuple[str, ...] = (
    "bitmask_flip",
    "identity_preserving_rewrite",
    "identity_shift_rewrite",
    "pool_replacement",
)

_mutation_component_weights: dict[str, float] = {}
_mutation_component_fail_counts: dict[str, int] = {}


def sample_mutation_mode(config) -> str:
    """Sample one mutation mode from adaptive roulette weights."""
    configured_weights = config.strategy_mutation_mode_weights()
    modes = [
        mode
        for mode, weight in configured_weights.items()
        if mode in MIXABLE_MUTATION_OPERATORS and float(weight) > 0.0
    ]
    if not modes:
        raise ValueError("No configured strategy mutation modes available.")

    for mode in modes:
        _mutation_component_weights.setdefault(mode, 1.0)
        _mutation_component_fail_counts.setdefault(mode, 0)

    mode_weights = [
        configured_weights[mode] * _mutation_component_weights[mode]
        for mode in modes
    ]
    return random.choices(modes, weights=mode_weights, k=1)[0]


def update_mutation_component_feedback(mutation_mode: str | None, improved: bool) -> None:
    """Update roulette statistics for one mutation component based on outcome."""
    if not mutation_mode:
        return

    weight = float(_mutation_component_weights.get(mutation_mode, 1.0))
    fail_count = int(_mutation_component_fail_counts.get(mutation_mode, 0))

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
    _mutation_component_weights[mutation_mode] = weight
    _mutation_component_fail_counts[mutation_mode] = fail_count


def current_strategy(individual: Individual, component_pool) -> dict[str, int]:
    """Return a complete mutable strategy index map for one individual."""
    return ensure_complete_strategy(index_map(individual), component_pool)


def finish_strategy_mutation(
    individual: Individual,
    component_pool,
    component_indices: dict[str, int],
    metadata: dict,
    elapsed: float,
) -> Individual:
    """Copy the individual, apply component indices, and attach metadata."""
    mutated_individual = individual.copy()
    completed_indices = ensure_complete_strategy(component_indices, component_pool)

    for key, value in completed_indices.items():
        mutated_individual.set_component_index(key, value)

    mutated_individual._sync_component_indices()
    mutated_individual.ea_llm_call_time = (
        getattr(mutated_individual, "ea_llm_call_time", 0.0) or 0.0
    ) + elapsed
    mutated_individual.mutation_metadata = metadata
    return mutated_individual


def allowed_pool_targets(component_pool) -> list[str]:
    """Return strategy buckets that are eligible for discrete pool replacement."""
    return [
        key for key in component_pool.evolving_component_keys
        if key not in getattr(component_pool, "CODE_MANAGED_COMPONENT_KEYS", set())
    ]


def identity_key(component_pool) -> str | None:
    """Return the active strategy identity key from the component pool metadata."""
    configured_key = getattr(component_pool, "identity_component_key", None)
    if configured_key in getattr(component_pool, "evolving_component_keys", []):
        return configured_key
    return None


def dependent_targets(component_pool) -> list[str]:
    """Return strategy rewrite targets derived from the loaded component JSON."""
    configured = list(getattr(component_pool, "dependent_strategy_keys", []) or [])
    if configured:
        return [
            target
            for target in configured
            if target in component_pool.evolving_component_keys
            and target not in getattr(component_pool, "CODE_MANAGED_COMPONENT_KEYS", set())
        ]

    configured_identity = identity_key(component_pool)
    return [
        target
        for target in component_pool.evolving_component_keys
        if target != configured_identity
        and target not in getattr(component_pool, "CODE_MANAGED_COMPONENT_KEYS", set())
    ]


def ensure_complete_strategy(strategy: dict[str, int], component_pool) -> dict[str, int]:
    """Ensure every active evolving component has a valid selected candidate."""
    completed = {
        str(key): coerce_index(value)
        for key, value in dict(strategy or {}).items()
    }

    for component_key in component_pool.evolving_component_keys:
        if component_key in getattr(component_pool, "CODE_MANAGED_COMPONENT_KEYS", set()):
            continue
        if component_key not in completed:
            completed[component_key] = component_pool.get_random_component_index(
                component_key
            )

    return completed


def coerce_index(value: Any) -> int:
    """Coerce component-index payloads into integer candidate indices."""
    if isinstance(value, dict):
        value = value.get("index", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def index_map(individual: Individual) -> dict[str, int]:
    """Return the individual's component index map with integer values."""
    return {
        key: coerce_index(value)
        for key, value in dict(getattr(individual, "component_indices", {}) or {}).items()
    }


def sample_replacement_index(component_pool, strategy_key: str, current_index: int | None) -> int:
    """Sample a replacement index, preferring a different candidate when possible."""
    candidates = component_pool.flat_components[strategy_key]
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


def rewrite_targets(
    strategy: dict[str, int],
    component_pool,
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
        current_text = component_text(component_pool, updated_strategy, target)
        instruction = build_rewrite_instruction(
            strategy=updated_strategy,
            component_pool=component_pool,
            target_component=target,
            mode_name=mode_name,
            purpose=purpose,
            preserve_identity=preserve_identity,
        )
        rewritten_text, elapsed = rewrite_component_with_llm(current_text, instruction)
        total_elapsed += elapsed
        rewritten_component = component_pool.parse_rewritten_component(
            target,
            rewritten_text,
        )
        updated_strategy[target] = component_pool.add_component(target, rewritten_component)
        rewritten_targets.append(target)

    return updated_strategy, f"{mode_name}: rewrote {', '.join(rewritten_targets)}", total_elapsed


def rewrite_component_with_llm(component: str, rewrite_instruction: str) -> tuple[str, float]:
    """Rewrite one strategy component through the LLM and time the call."""
    start = time.perf_counter()
    try:
        rewritten_component = LLM.llama_cpp_rewrite_component(
            original_text=component,
            instruction=rewrite_instruction,
            model="local",
        )
    except Exception:
        rewritten_component = component
    return rewritten_component, time.perf_counter() - start


def build_rewrite_instruction(
    *,
    strategy: dict[str, int],
    component_pool,
    target_component: str,
    mode_name: str,
    purpose: str,
    preserve_identity: bool,
) -> str:
    """Assemble the rewrite constraints used by rewrite-based mutations."""
    strategy_snapshot = format_strategy_snapshot(strategy, component_pool)
    configured_identity = identity_key(component_pool)
    identity_text = component_text(component_pool, strategy, configured_identity)
    unchanged_components = [
        key for key in component_pool.component_keys if key != target_component
    ]
    unchanged_snapshot = "\n\n".join(
        f"[{key}]\n{component_text(component_pool, strategy, key)}"
        for key in unchanged_components
    )

    return (
        f"Mutation mode: {mode_name}\n"
        f"Rewrite target: {target_component}\n"
        f"Purpose: {purpose}\n\n"
        "Strategy component design:\n"
        f"- Active component keys loaded from JSON: {', '.join(component_pool.component_keys)}.\n"
        f"- Identity key loaded from JSON: {configured_identity or 'none'}.\n"
        "- Keep the rewritten component coherent with the active strategy keys and their current meanings.\n\n"
        "Global rewrite constraints:\n"
        "1. Modify only the allowed strategy component named above.\n"
        "2. Preserve all non-strategy sections completely.\n"
        "3. Preserve JSON schema and action definitions completely.\n"
        "4. The rewritten component must become MORE specific, MORE detailed, and MORE operational than the original.\n"
        "5. Do not summarize, shorten, generalize, or weaken the strategy.\n"
        "6. Add concrete decision rules, trigger conditions, priorities, and fallback behavior where appropriate.\n"
        f"7. {domain_rewrite_guidance(component_pool)}\n"
        "8. Avoid vague phrases such as 'play carefully', 'balance economy and army', 'adapt to the situation', 'make good decisions', or 'attack when ready' unless they are followed by concrete conditions.\n"
        "9. Prefer explicit if-then rules, ordered priorities, and phase-specific actions.\n"
        "10. Keep the rewritten text coherent with the unchanged components.\n"
        f"11. {'Preserve the identity component exactly as written.' if preserve_identity else 'You may change the identity component because this is an identity shift.'}\n\n"
        f"Current identity component ({configured_identity or 'none'}):\n{identity_text}\n\n"
        f"Current strategy snapshot:\n{strategy_snapshot}\n\n"
        f"Unchanged strategy components to stay consistent with:\n{unchanged_snapshot}\n\n"
        "Output requirements:\n"
        "- Return 3 to 7 bullet points or short imperative rules.\n"
        "- Each bullet must contain at least one concrete condition, target, or action.\n"
        "- Do not return a high-level paragraph.\n"
        "- Do not use generic strategy language without domain-specific details.\n\n"
        f"Return only the rewritten text for [{target_component}] with no explanation."
    )


def domain_rewrite_guidance(component_pool) -> str:
    """Return application-specific rewrite guidance supplied by component metadata."""
    metadata = dict(getattr(component_pool, "metadata", {}) or {})
    guidance = metadata.get("rewrite_domain_guidance")
    if guidance:
        return str(guidance)
    return (
        "Mention concrete domain objects, constraints, action names, and state conditions "
        "from the active component pool when useful."
    )


def format_strategy_snapshot(strategy: dict[str, int], component_pool) -> str:
    """Render the current strategy dictionary into a readable rewrite context."""
    blocks = []
    for key in component_pool.component_keys:
        blocks.append(f"[{key}]\n{component_text(component_pool, strategy, key)}")
    return "\n\n".join(blocks)


def component_text(component_pool, strategy: dict[str, int], strategy_key: str | None) -> str:
    """Read one strategy component as a newline-joined text block."""
    if strategy_key is None or strategy_key not in strategy:
        return ""
    index = coerce_index(strategy.get(strategy_key))
    try:
        return "\n".join(component_pool.get_component(strategy_key, int(index)))
    except (IndexError, KeyError, ValueError):
        return "\n".join(component_pool.get_component(strategy_key, 0))


def component_index(strategy: dict[str, int], strategy_key: str | None) -> int | None:
    """Return one selected component index from the strategy dict."""
    if strategy_key is None or strategy_key not in dict(strategy or {}):
        return None
    return coerce_index(dict(strategy or {}).get(strategy_key))


def build_metadata(
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


def mutate_training_examples_from_pool(individual: Individual, component_pool, config) -> Individual:
    """Insert or replace examples from the code-managed runtime pool."""
    example_memory = getattr(component_pool, "example_memory", None)
    pool_examples = list(getattr(example_memory, "examples", []) or [])
    if not pool_examples:
        return individual

    max_examples = max_training_examples(config, component_pool)
    if max_examples <= 0:
        return individual

    mutated = individual.copy()
    current_examples = [
        deepcopy(example)
        for example in list(getattr(mutated, "training_examples", []) or [])
        if isinstance(example, dict)
    ][:max_examples]
    seen = {training_example_key(example) for example in current_examples}
    available = [
        deepcopy(example)
        for example in pool_examples
        if training_example_key(example) not in seen
    ]
    if not available:
        return mutated

    selected = random.choice(available)
    if not current_examples or len(current_examples) < max_examples and random.random() < 0.5:
        current_examples.append(selected)
    else:
        current_examples[random.randrange(len(current_examples))] = selected

    deduped: list[dict] = []
    deduped_keys: set[str] = set()
    for example in current_examples:
        key = training_example_key(example)
        if key in deduped_keys:
            continue
        deduped.append(example)
        deduped_keys.add(key)
        if len(deduped) >= max_examples:
            break
    mutated.training_examples = deduped
    metadata = dict(getattr(mutated, "mutation_metadata", {}) or {})
    metadata["example_mutation"] = {
        "mode": "pool_insert_or_replace",
        "pool_size": len(pool_examples),
        "example_count": len(mutated.training_examples),
    }
    mutated.mutation_metadata = metadata
    return mutated


def max_training_examples(config, component_pool) -> int:
    """Return the maximum examples carried by one individual."""
    configured = getattr(
        config,
        "max_examples",
        getattr(
            config,
            "training_example_max_examples",
            getattr(component_pool, "MAX_TRAINING_EXAMPLES_PER_RENDER", 4),
        ),
    )
    return max(0, int(configured))


def training_example_key(example: dict) -> str:
    """Return a normalized duplicate key for one training example."""
    moves = example.get("moves")
    move = moves[0] if isinstance(moves, list) and moves else {}
    if not isinstance(move, dict):
        move = {}
    unit_position = move.get("unit_position")
    position_key = ",".join(str(value) for value in unit_position) if isinstance(unit_position, list) else ""
    key = "|".join(
        (
            str(move.get("raw_move", "")).strip().lower(),
            position_key,
            str(move.get("action_type", "")).strip().lower(),
        )
    )
    if key.strip("|"):
        return key
    return "\n".join(str(line).strip().lower() for line in example.get("content", []))
