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
    def __init__(self, *, method: str="uniform") -> None: self.method=method
    def crossover(self,parent_a: Candidate,parent_b: Candidate,context: CrossoverContext)->Candidate:
        if self.method != "uniform": raise ValueError(f"Unknown crossover method: {self.method}")
        behavior_parent=context.rng.choice([parent_a,parent_b])
        return Candidate(generation=context.generation,parent_ids=(parent_a.id,parent_b.id),strategy_prompt=context.rng.choice([parent_a.strategy_prompt,parent_b.strategy_prompt]),previous_code=behavior_parent.previous_code,generation_prompt=context.rng.choice([parent_a.generation_prompt,parent_b.generation_prompt]),module_prompts=behavior_parent.module_prompts,module_bodies=behavior_parent.module_bodies,metadata={"operator":"crossover","behavior_parent":behavior_parent.id})
