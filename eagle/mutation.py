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
    game_performance: float | None = None
    player_resource: float | None = None
    enemy_resource: float | None = None
    resource_breakdown: dict[str, object] | None = None
    alignment_score: float | None = None
    alignment_reason: str = ""


class Mutation:
    """Apply one configured mutation method."""

    def __init__(self, config: ExperimentConfig, *, method: str = "strategy_reflection") -> None:
        self.config = config
        self.method = method

    def mutate(self, candidate: Candidate, context: MutationContext) -> Candidate:
        if self.method == "strategy_reflection":
            return self._strategy_reflection(candidate, context)
        if self.method == "code_generation_reflection":
            return self._code_generation_reflection(candidate, context)
        raise ValueError(f"Unknown mutation method: {self.method}")

    def _strategy_reflection(self, candidate: Candidate, context: MutationContext) -> Candidate:
        # Strategy reflection improves what the agent should do using game outcome feedback.
        prompt = (
            f"{candidate.strategy_prompt.rstrip()}\n\n"
            f"Strategy reflection {context.index + 1}: game_performance={format_feedback(context.game_performance)}, "
            f"player_resource={format_feedback(context.player_resource)}, "
            f"enemy_resource={format_feedback(context.enemy_resource)}, "
            f"resource_details={context.resource_breakdown or {}}. "
            f"{self.config.mutation_suffix} "
            "Adjust the intended MicroRTS behavior while keeping the strategy concise."
        )
        return self._copy_candidate(
            candidate,
            context=context,
            strategy_prompt=normalize_prompt(
                prompt,
                max_chars=self.config.max_prompt_chars,
                max_lines=self.config.max_prompt_lines,
            ),
            previous_code=candidate.previous_code,
        )

    def _code_generation_reflection(self, candidate: Candidate, context: MutationContext) -> Candidate:
        # Code-generation reflection improves how code should be generated from the strategy context.
        reflection = (
            "\n\n/* Code generation reflection "
            f"{context.index + 1}: alignment_score={format_feedback(context.alignment_score)}. "
            f"{context.alignment_reason or 'Keep the generated Java aligned with the strategy and scaffold rules.'} "
            "Use this as reference material only. */"
        )
        return self._copy_candidate(
            candidate,
            context=context,
            strategy_prompt=candidate.strategy_prompt,
            previous_code=f"{candidate.previous_code.rstrip()}{reflection}".strip(),
        )

    def _copy_candidate(
        self,
        candidate: Candidate,
        *,
        context: MutationContext,
        strategy_prompt: str,
        previous_code: str,
    ) -> Candidate:
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
            strategy_prompt=strategy_prompt,
            previous_code=previous_code,
            generation_prompt=candidate.generation_prompt,
            metadata={**candidate.metadata, "operator": operator},
        )


def format_feedback(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.3f}"
