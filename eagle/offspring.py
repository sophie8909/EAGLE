"""Prompt mutation, crossover, and offspring construction."""

from __future__ import annotations

import random
from collections.abc import Callable

from .candidate import Candidate
from .config import ExperimentConfig

ParentSelector = Callable[[list[Candidate], random.Random], Candidate]


def make_offspring(
    population: list[Candidate],
    *,
    config: ExperimentConfig,
    generation: int,
    rng: random.Random,
    parent_selector: ParentSelector,
) -> list[Candidate]:
    """Create one generation of child prompts from selected parents."""

    offspring: list[Candidate] = []
    while len(offspring) < config.population_size:
        parent_a = parent_selector(population, rng)
        parent_b = parent_selector(population, rng)
        operator = "mutation"

        # Crossover blends two parent prompts into one generation request.
        if len(population) > 1 and rng.random() < config.crossover_rate:
            prompt = crossover_prompts(parent_a.strategy_prompt, parent_b.strategy_prompt)
            parent_ids = (parent_a.id, parent_b.id)
            operator = "crossover"
        else:
            prompt = parent_a.strategy_prompt
            parent_ids = (parent_a.id,)

        # Mutation appends a small instruction that nudges the strategy.
        if rng.random() < config.mutation_rate:
            prompt = mutate_prompt(prompt, config.mutation_suffix, clone_index=len(offspring))
            operator = f"{operator}+mutation" if operator == "crossover" else "mutation"

        offspring.append(
            Candidate(
                generation=generation,
                parent_ids=parent_ids,
                strategy_prompt=prompt,
                metadata={"operator": operator},
            )
        )
    return offspring


def mutate_prompt(prompt: str, mutation_suffix: str, *, clone_index: int) -> str:
    """Append a simple mutation instruction to a strategy prompt."""

    return (
        f"{prompt.rstrip()}\n\n"
        f"Mutation {clone_index + 1}: {mutation_suffix} "
        "Emphasize one concrete MicroRTS behavior such as economy, defense, scouting, or pressure."
    )


def crossover_prompts(prompt_a: str, prompt_b: str) -> str:
    """Combine two strategy prompts into one child prompt."""

    return (
        "Blend these two MicroRTS strategy prompts into one Java-agent generation request.\n\n"
        f"Parent strategy A:\n{prompt_a.rstrip()}\n\n"
        f"Parent strategy B:\n{prompt_b.rstrip()}\n\n"
        "Child strategy: keep the strongest compatible ideas from both parents and avoid runtime LLM calls."
    )
