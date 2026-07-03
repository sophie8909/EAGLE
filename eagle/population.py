"""Population initialization and evolution loop."""

from __future__ import annotations

from dataclasses import dataclass

from agents.workspace import AgentWorkspace
from evaluation.evaluator import CandidateEvaluator
from generation.backend import GenerationBackend

from .candidate import CandidatePrompt
from .config import ExperimentConfig
from .operators import mutate_prompt, select_top


@dataclass(frozen=True)
class EvaluatedCandidate:
    candidate: CandidatePrompt
    fitness: float
    artifacts: dict[str, str]


def initialize_population(config: ExperimentConfig) -> list[CandidatePrompt]:
    prompts = [CandidatePrompt(text=prompt) for prompt in config.seed_prompts]
    while len(prompts) < config.population_size:
        source = prompts[len(prompts) % len(config.seed_prompts)]
        prompts.append(source.with_text(source.text, metadata={"operator": "clone"}))
    return prompts[: config.population_size]


def run_population_loop(
    config: ExperimentConfig,
    backend: GenerationBackend,
    workspace: AgentWorkspace,
    evaluator: CandidateEvaluator,
) -> list[EvaluatedCandidate]:
    config.validate()
    population = initialize_population(config)
    last_results: list[EvaluatedCandidate] = []

    for generation in range(config.generations):
        last_results = []
        fitness: dict[str, float] = {}
        for candidate in population:
            java_source = backend.generate(candidate)
            source_path = workspace.write_source(candidate, java_source)
            result = evaluator.evaluate(candidate, source_path)
            fitness[candidate.candidate_id] = result.fitness
            last_results.append(EvaluatedCandidate(candidate, result.fitness, result.artifacts))

        parents = select_top(population, fitness, max(1, min(len(population), config.population_size // 2 or 1)))
        next_population = list(parents)
        while len(next_population) < config.population_size:
            parent = parents[len(next_population) % len(parents)]
            next_population.append(mutate_prompt(parent, generation + 1))
        population = next_population

    return last_results

