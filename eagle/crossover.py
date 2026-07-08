"""Prompt crossover operators."""

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
    """Apply one configured crossover method."""

    def __init__(self, *, method: str = "uniform") -> None:
        self.method = method

    def crossover(self, parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
        if self.method == "uniform":
            return self._uniform(parent_a, parent_b, context)
        raise ValueError(f"Unknown crossover method: {self.method}")

    def _uniform(self, parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
        # Uniform crossover chooses each candidate component independently from either parent.
        return Candidate(
            generation=context.generation,
            parent_ids=(parent_a.id, parent_b.id),
            strategy_prompt=context.rng.choice([parent_a.strategy_prompt, parent_b.strategy_prompt]),
            previous_code=context.rng.choice([parent_a.previous_code, parent_b.previous_code]),
            generation_prompt=context.rng.choice([parent_a.generation_prompt, parent_b.generation_prompt]),
            metadata={"operator": "crossover"},
        )
