"""Evaluation helpers for the current EAGLE runtime pipeline."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ..config import EAConfig
from ..envs.microrts.runner import run_java_agent_game, run_prompt_based_game
from ..evolution.operators.reflection import Reflection, read_max_turn_hint
from ..project import PROJECT_ROOT
from ..utils.component_pool import ComponentPool
from ..utils.fitness_calculator import (
    combined_match_score,
    raw_resource_advantage_score,
)
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.individual import Individual
from ..utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl

DEFAULT_REAL_EVAL_OPPONENTS = [
    "ai.abstraction.LightRush",
    "ai.abstraction.HeavyRush",
]


class Evaluator:
    """Evaluate individuals with either real MicroRTS matches or the Java surrogate."""

    def __init__(
        self,
        component_pool: ComponentPool,
        config: EAConfig | None = None,
        runtime_logs_dir: str | Path | None = None,
    ):
        self.component_pool = component_pool
        self.config = config or EAConfig()
        self.repo_root = PROJECT_ROOT
        self.runtime_logs_dir = Path(runtime_logs_dir) if runtime_logs_dir is not None else None
        setattr(self.config, "runtime_logs_dir", self.runtime_logs_dir)



    def evaluate(self, individual: Individual) -> dict[str, Any]:
        """ Main control flow for evaluating one individual
            1. calling run_prompt_based_agent 
            2. save the evaluation log 
        """

        pass

    def surrogate(self, individual: Individual) -> dict[str, Any]:
        """ Main control flow for evaluating one individual with surrogate evaluation
            1. calling run_java_based_agent 
        """
        pass

    # game play with prompt based agent
    def run_prompt_based_agent(self, individual: Individual) -> dict[str, Any]:
        pass

    # game play with java based agent
    def run_java_based_agent(self, individual: Individual) -> dict[str, Any]:
        pass