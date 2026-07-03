"""Small prompt variation operators."""

from __future__ import annotations

from .candidate import CandidatePrompt


def mutate_prompt(candidate: CandidatePrompt, generation: int) -> CandidatePrompt:
    """Return a simple deterministic mutation for smoke experiments."""

    suffix = f"\n\nGeneration {generation}: prefer clear tactical priorities and compilable Java."
    return candidate.with_text(candidate.text.rstrip() + suffix, metadata={"operator": "mutate"})


def select_top(population: list[CandidatePrompt], fitness: dict[str, float], count: int) -> list[CandidatePrompt]:
    """Select the highest-fitness candidates."""

    return sorted(population, key=lambda item: fitness.get(item.candidate_id, float("-inf")), reverse=True)[:count]

