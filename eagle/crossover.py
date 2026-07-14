"""Candidate-component crossover operators."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .candidate import Candidate


@dataclass(frozen=True)
class CrossoverContext:
    generation: int
    index: int
    rng: random.Random


class Crossover:
    def __init__(self, *, method: str = "uniform") -> None:
        self.method = method

    def crossover(
        self,
        parent_a: Candidate,
        parent_b: Candidate,
        context: CrossoverContext,
    ) -> Candidate:
        if self.method != "uniform":
            raise ValueError(f"Unknown crossover method: {self.method}")

        strategy_parent = context.rng.choice((parent_a, parent_b))
        previous_code_parent = context.rng.choice((parent_a, parent_b))
        generation_prompt_parent = context.rng.choice((parent_a, parent_b))
        component_parent_ids = (
            strategy_parent.id,
            previous_code_parent.id,
            generation_prompt_parent.id,
        )
        return Candidate(
            generation=context.generation,
            parent_ids=(parent_a.id, parent_b.id),
            strategy_prompt=strategy_parent.strategy_prompt,
            previous_code=previous_code_parent.inheritable_previous_code,
            generation_prompt=generation_prompt_parent.generation_prompt,
            operator="crossover",
            strategy_parent_id=strategy_parent.id,
            previous_code_parent_id=previous_code_parent.id,
            generation_prompt_parent_id=generation_prompt_parent.id,
            source_candidate_ids=tuple(dict.fromkeys(component_parent_ids)),
        )
