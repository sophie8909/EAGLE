"""Minimal experiment orchestration."""

from __future__ import annotations

from agents.workspace import AgentWorkspace
from evaluation.evaluator import CandidateEvaluator
from generation.backend import build_generation_backend

from .config import ExperimentConfig
from .population import EvaluatedCandidate, run_population_loop


def run_experiment(config: ExperimentConfig) -> list[EvaluatedCandidate]:
    backend = build_generation_backend(config.generation_backend)
    workspace = AgentWorkspace(config.generated_agent_dir)
    evaluator = CandidateEvaluator(
        microrts_dir=config.microrts_dir,
        opponent=config.opponent,
        tick_limit=config.tick_limit,
        dry_run=config.dry_run,
    )
    return run_population_loop(config, backend, workspace, evaluator)

