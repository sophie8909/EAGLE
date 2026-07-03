"""Shared helpers for crossover operator plugins."""

from __future__ import annotations

import random
import time
from copy import deepcopy

from eagle.evolution.component.individual import Individual
from eagle.llm import LLM
from eagle.operators.mutation import support as mutation_support


def _average_objective_fitness(left_fitness: dict, right_fitness: dict) -> dict[str, float]:
    """Average two objective-name keyed fitness dictionaries."""
    averaged: dict[str, float] = {}
    objective_names = list(left_fitness.keys())
    objective_names.extend(key for key in right_fitness.keys() if key not in left_fitness)

    for objective_name in objective_names:
        left_value = left_fitness.get(objective_name)
        right_value = right_fitness.get(objective_name)
        if left_value is None:
            averaged[str(objective_name)] = float(right_value)
        elif right_value is None:
            averaged[str(objective_name)] = float(left_value)
        else:
            averaged[str(objective_name)] = (float(left_value) + float(right_value)) / 2
    return averaged


def average_parent_fitness(child: Individual, parent1: Individual, parent2: Individual) -> Individual:
    """Attach the mean parent fitness to one crossover child."""
    parent1_fitness = parent1.fitness
    parent2_fitness = parent2.fitness

    if isinstance(parent1_fitness, dict) and isinstance(parent2_fitness, dict):
        child.fitness = _average_objective_fitness(parent1_fitness, parent2_fitness)
    else:
        child.fitness = [
            (left + right) / 2
            for left, right in zip(parent1_fitness, parent2_fitness)
        ]
    return child


def max_training_examples(config, component_pool) -> int:
    """Return the maximum examples carried by one child."""
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


def example_key(example: dict) -> str:
    """Return the normalized action-level example identity."""
    moves = example.get("moves")
    move = moves[0] if isinstance(moves, list) and moves else {}
    if not isinstance(move, dict):
        move = {}
    return "|".join(
        str(move.get(field, "")).strip().lower()
        for field in ("raw_move", "action_type", "unit_type")
    ) or "\n".join(str(line).strip().lower() for line in example.get("content", []))


def parent_training_examples(parent: Individual, component_pool, max_examples: int) -> list[dict]:
    """Return examples carried by a parent, falling back to the runtime pool."""
    examples = list(getattr(parent, "training_examples", []) or [])
    if not examples:
        examples = component_pool.sample_training_examples(max_examples)
    return [deepcopy(example) for example in examples[:max_examples]]


def uniform_crossover_training_examples(component_pool, parent1: Individual, parent2: Individual, config) -> list[dict]:
    """Sample child examples independently from parent A and parent B examples."""
    max_examples = max_training_examples(config, component_pool)
    if max_examples <= 0:
        return []
    left_examples = parent_training_examples(parent1, component_pool, max_examples)
    right_examples = parent_training_examples(parent2, component_pool, max_examples)
    child_examples: list[dict] = []
    seen: set[str] = set()
    max_len = max(len(left_examples), len(right_examples))

    for index in range(max_len):
        choices = []
        if index < len(left_examples):
            choices.append(left_examples[index])
        if index < len(right_examples):
            choices.append(right_examples[index])
        if not choices:
            continue
        selected = deepcopy(random.choice(choices))
        key = example_key(selected)
        if key in seen:
            continue
        child_examples.append(selected)
        seen.add(key)
        if len(child_examples) >= max_examples:
            break

    return child_examples


def repair_after_crossover(individual: Individual, component_pool) -> Individual:
    """Repair a crossover child by rewriting dependent components around its identity."""
    strategy = mutation_support.current_strategy(individual, component_pool)
    strategy_identity_key = mutation_support.identity_key(component_pool)
    old_identity = mutation_support.component_index(strategy, strategy_identity_key)
    repair_targets = mutation_support.dependent_targets(component_pool)

    if not repair_targets:
        metadata = mutation_support.build_metadata(
            mutation_mode="crossover_repair_rewrite",
            changed_components=[],
            old_identity=old_identity,
            new_identity=mutation_support.component_index(strategy, strategy_identity_key),
            repair_triggered=False,
            rewrite_prompt_summary="crossover_repair_rewrite: no available repair targets",
        )
        return mutation_support.finish_strategy_mutation(
            individual,
            component_pool,
            strategy,
            metadata,
            0.0,
        )

    updated_strategy, rewrite_summary, elapsed = mutation_support.rewrite_targets(
        strategy,
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
    metadata = mutation_support.build_metadata(
        mutation_mode="crossover_repair_rewrite",
        changed_components=repair_targets,
        old_identity=old_identity,
        new_identity=mutation_support.component_index(updated_strategy, strategy_identity_key),
        repair_triggered=True,
        rewrite_prompt_summary=rewrite_summary,
    )
    return mutation_support.finish_strategy_mutation(
        individual,
        component_pool,
        updated_strategy,
        metadata,
        elapsed,
    )


def combine_parent_component(
    component_pool,
    component_key: str,
    parent1: Individual,
    parent2: Individual,
) -> tuple[int, float]:
    """Merge one component semantically through the LLM and store it in the pool."""
    parent1_text = component_pool.get_component_str(
        component_key,
        parent1.get_component_index(component_key),
    )
    parent2_text = component_pool.get_component_str(
        component_key,
        parent2.get_component_index(component_key),
    )
    instruction = (
        f"Semantically merge the two parent variants for [{component_key}]. "
        "Keep concrete operational rules from both parents, remove contradictions, "
        "and return one coherent component that can replace the original component."
    )

    start = time.perf_counter()
    try:
        merged_text = LLM.llama_cpp_combine_components(
            parent1_text,
            parent2_text,
            instruction,
            model="local",
        )
        elapsed = time.perf_counter() - start
        merged_component = component_pool.parse_rewritten_component(component_key, merged_text)
        return component_pool.add_component(component_key, merged_component), elapsed
    except Exception:
        elapsed = time.perf_counter() - start
        fallback_parent = random.choice([parent1, parent2])
        return fallback_parent.get_component_index(component_key), elapsed
