"""Crossover owns parent component selection for one generated child."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .candidate import Candidate


@dataclass(frozen=True)
class CrossoverContext:
    generation: int
    index: int
    rng: random.Random


def crossover(parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
    """Select one parent for each inheritable component and create the child genotype."""

    strategy_parent = context.rng.choice((parent_a, parent_b))
    generation_prompt_parent = context.rng.choice((parent_a, parent_b))
    component_parent_ids = (
        strategy_parent.id,
        generation_prompt_parent.id,
    )
    return Candidate(
        generation=context.generation,
        parent_ids=(parent_a.id, parent_b.id),
        strategy_prompt=strategy_parent.strategy_prompt,
        strategy_signature=dict(strategy_parent.strategy_signature),
        strategy_niche=strategy_parent.strategy_niche,
        generation_prompt=generation_prompt_parent.generation_prompt,
        operator="crossover",
        strategy_parent_id=strategy_parent.id,
        generation_prompt_parent_id=generation_prompt_parent.id,
        source_candidate_ids=tuple(dict.fromkeys(component_parent_ids)),
    )
