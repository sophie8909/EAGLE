"""Prompt mutation operators."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate import Candidate
from .config import ExperimentConfig
from .offspring import normalize_prompt


@dataclass(frozen=True)
class MutationContext:
    generation: int
    index: int


class Mutation:
    """Apply one configured mutation method."""

    def __init__(self, config: ExperimentConfig, *, method: str = "default") -> None:
        self.config = config
        self.method = method

    def mutate(self, candidate: Candidate, context: MutationContext) -> Candidate:
        if self.method == "default":
            return self._default(candidate, context)
        raise ValueError(f"Unknown mutation method: {self.method}")

    def _default(self, candidate: Candidate, context: MutationContext) -> Candidate:
        prompt = (
            f"{candidate.strategy_prompt.rstrip()}\n\n"
            f"Mutation {context.index + 1}: {self.config.mutation_suffix} "
            "Emphasize one concrete MicroRTS behavior such as economy, defense, scouting, or pressure."
        )
        operator = candidate.metadata.get("operator", "mutation")
        if operator == "crossover":
            operator = "crossover+mutation"
        elif operator == "seed_mutation":
            operator = "seed_mutation"
        else:
            operator = "mutation"
        return Candidate(
            generation=context.generation,
            parent_ids=candidate.parent_ids or (candidate.id,),
            strategy_prompt=normalize_prompt(
                prompt,
                max_chars=self.config.max_prompt_chars,
                max_lines=self.config.max_prompt_lines,
            ),
            metadata={**candidate.metadata, "operator": operator},
        )
