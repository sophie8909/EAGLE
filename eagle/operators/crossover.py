"""Crossover owns parent component selection for one generated child."""

from __future__ import annotations

import random
from dataclasses import dataclass

from eagle.candidate import Candidate
from eagle.evaluation.determinism import derive_candidate_id


@dataclass(frozen=True)
class CrossoverContext:
    generation: int
    index: int
    rng: random.Random
    inherit_java: bool = False
    random_seed: int = 0
    strategy_only: bool = False


def crossover(parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
    """Select one parent for each inheritable component and create the child genotype."""

    if parent_a.java_materialization_mode != parent_b.java_materialization_mode:
        raise ValueError("Crossover cannot mix Java materialization modes.")
    strategy_only = context.strategy_only or parent_a.java_materialization_mode == "deterministic_dsl"
    if strategy_only and context.inherit_java:
        raise ValueError("Deterministic crossover cannot inherit Java.")
    if strategy_only and parent_a.java_compiler_version != parent_b.java_compiler_version:
        raise ValueError("Deterministic crossover requires matching compiler versions.")
    strategy_parent = context.rng.choice((parent_a, parent_b))
    generation_prompt_parent = None if strategy_only else context.rng.choice((parent_a, parent_b))
    java_parent = context.rng.choice((parent_a, parent_b)) if context.inherit_java else None
    component_parent_ids = (
        strategy_parent.id,
        *(() if generation_prompt_parent is None else (generation_prompt_parent.id,)),
        *(() if java_parent is None else (java_parent.id,)),
    )
    return Candidate(
        id=(
            derive_candidate_id(
                context.random_seed,
                generation=context.generation,
                index=context.index,
                role="crossover",
                parent_ids=(parent_a.id, parent_b.id),
            )
        ),
        generation=context.generation,
        parent_ids=(parent_a.id, parent_b.id),
        strategy_prompt=strategy_parent.strategy_prompt,
        strategy_signature=dict(strategy_parent.strategy_signature),
        strategy_niche=strategy_parent.strategy_niche,
        candidate_java_mode="inherited_genotype" if context.inherit_java else "generated_phenotype",
        java_materialization_mode=parent_a.java_materialization_mode,
        java_compiler_version=parent_a.java_compiler_version,
        generation_prompt="" if generation_prompt_parent is None else generation_prompt_parent.generation_prompt,
        operator="crossover",
        strategy_parent_id=strategy_parent.id,
        generation_prompt_parent_id=None if generation_prompt_parent is None else generation_prompt_parent.id,
        inherited_java=(
            "" if java_parent is None
            else java_parent.generated_java or java_parent.inherited_java
        ),
        java_parent_id=None if java_parent is None else java_parent.id,
        source_candidate_ids=tuple(dict.fromkeys(component_parent_ids)),
    )
