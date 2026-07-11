"""Prompt crossover operators."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .candidate import Candidate, MODULE_NAMES


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
        # Uniform crossover chooses each function module independently from either parent.
        module_prompts = {}
        module_bodies = {}
        for module_name in MODULE_NAMES:
            prompt_parent = context.rng.choice([parent_a, parent_b])
            body_parent = context.rng.choice([parent_a, parent_b])
            module_prompts[module_name] = prompt_parent.module_prompts[module_name]
            module_bodies[module_name] = body_parent.module_bodies[module_name]
        return Candidate(
            generation=context.generation,
            parent_ids=(parent_a.id, parent_b.id),
            strategy_prompt=module_prompts["controller"],
            previous_code=context.rng.choice([parent_a.previous_code, parent_b.previous_code]),
            generation_prompt=context.rng.choice([parent_a.generation_prompt, parent_b.generation_prompt]),
            module_prompts=module_prompts,
            module_bodies=module_bodies,
            metadata={"operator": "crossover"},
        )
