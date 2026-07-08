"""Prompt crossover operators."""

from __future__ import annotations

from dataclasses import dataclass

from .candidate import Candidate
from .config import ExperimentConfig
from .offspring import normalize_prompt


@dataclass(frozen=True)
class CrossoverContext:
    generation: int
    index: int


class Crossover:
    """Apply one configured crossover method."""

    def __init__(self, config: ExperimentConfig, *, method: str = "uniform") -> None:
        self.config = config
        self.method = method

    def crossover(self, parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
        if self.method == "uniform":
            return self._uniform(parent_a, parent_b, context)
        raise ValueError(f"Unknown crossover method: {self.method}")

    def _uniform(self, parent_a: Candidate, parent_b: Candidate, context: CrossoverContext) -> Candidate:
        prompt = (
            "Blend these two MicroRTS strategy prompts into one Java-agent generation request.\n\n"
            f"Parent strategy A:\n{parent_a.strategy_prompt.rstrip()}\n\n"
            f"Parent strategy B:\n{parent_b.strategy_prompt.rstrip()}\n\n"
            "Child strategy: keep the strongest compatible ideas from both parents and avoid runtime LLM calls."
        )
        return Candidate(
            generation=context.generation,
            parent_ids=(parent_a.id, parent_b.id),
            strategy_prompt=normalize_prompt(
                prompt,
                max_chars=self.config.max_prompt_chars,
                max_lines=self.config.max_prompt_lines,
            ),
            metadata={"operator": "crossover"},
        )
