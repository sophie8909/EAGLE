"""Evaluation helpers for the current EAGLE runtime pipeline."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ..config import EAConfig
from ..envs.microrts.runner import run_java_agent_game, run_prompt_based_game
from ..evolution.operators.reflection import Reflection, read_max_turn_hint
from ..project import PROJECT_ROOT
from ..surrogate.eval.evaluator import evaluate_with_java_surrogate
from ..utils.component_pool import ComponentPool
from ..utils.fitness_calculator import (
    raw_resource_advantage_score,
)
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.fitness_utils import normalize_fitness
from ..utils.individual import Individual
from ..utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl


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

    def evaluate(
        self,
        individual: Individual,
        use_real_evaluation: bool,
        opponent: str | None,
        allow_history_reuse_for_real: bool = False,
        profile_output_path: str | Path | None = None,
        generation: int | None = None,
        fitness_recorder: FitnessRecorder | None = None,
    ) -> None:
        """Evaluate one individual and write the normalized raw match score back.

        The evaluation path is intentionally staged in this order:
        1. Render the prompt once from the current individual.
        2. Try to reuse one cached historical match when allowed.
        3. Otherwise run either a real MicroRTS match or the surrogate evaluator.
        4. Normalize and persist the resulting single-match score.

        This function only manages one match against one opponent. Higher-level EA
        code is responsible for combining per-opponent match scores into EA fitness.
        """
        stats: dict[str, float] = {}

        with timer("prompt_render_time", stats):
            prompt = self.construct_prompt(individual)

        # Prefer cached history when the caller allows it. This keeps repeated
        # surrogate passes cheap and optionally lets "real" requests reuse an
        # identical prompt/opponent match if the caller opted in.
        requested_real_evaluation = bool(use_real_evaluation)
        history_match_score = self._lookup_history_match_score(
            prompt=prompt,
            opponent=opponent,
            requested_real_evaluation=requested_real_evaluation,
            allow_history_reuse_for_real=allow_history_reuse_for_real,
            fitness_recorder=fitness_recorder,
        )

        simulation_meta: dict[str, Any] = {}
        if history_match_score is not None:
            fitness = history_match_score
            use_real_evaluation = False
            evaluation_mode = "history_reuse"
        elif use_real_evaluation:
            fitness, simulation_meta = self.run_prompt_match(prompt, opponent, stats=stats)
            evaluation_mode = "real"
        else:
            with timer("EA_operator_time", stats):
                with timer("surrogate_time", stats):
                    fitness = self.surrogate_evaluation(prompt, opponent=opponent)
            evaluation_mode = "surrogate"

        fitness = normalize_fitness(fitness)
        self._record_match_score(
            individual=individual,
            prompt=prompt,
            fitness=fitness,
            opponent=opponent,
            evaluation_mode=evaluation_mode,
            generation=generation,
            stats=stats,
            fitness_recorder=fitness_recorder,
        )

        individual.fitness = fitness
        individual.evaluation_mode = evaluation_mode

        # Only real matches carry replayable logs and reflection context.
        if evaluation_mode == "real":
            self._store_real_evaluation(individual=individual, fitness=fitness, simulation_meta=simulation_meta)

        summarize_total_eval_time(stats)
        operator_profile = getattr(individual, "operator_profile", None)
        if isinstance(operator_profile, dict):
            for key in ("crossover_time", "mutation_time", "EA_operator_time"):
                stats[key] = stats.get(key, 0.0) + operator_profile.get(key, 0.0)
            summarize_total_eval_time(stats)

        if profile_output_path is not None and evaluation_mode == "real":
            self._write_real_evaluation_profile(
                individual=individual,
                generation=generation,
                prompt=prompt,
                opponent=opponent,
                fitness=fitness,
                stats=stats,
                operator_profile=operator_profile if isinstance(operator_profile, dict) else None,
                simulation_meta=simulation_meta,
                profile_output_path=profile_output_path,
            )

    def _lookup_history_match_score(
        self,
        *,
        prompt: str,
        opponent: str | None,
        requested_real_evaluation: bool,
        allow_history_reuse_for_real: bool,
        fitness_recorder: FitnessRecorder | None,
    ) -> list[float] | None:
        """Return one cached match score when history reuse is enabled for this call."""
        if fitness_recorder is None:
            return None
        if requested_real_evaluation and not allow_history_reuse_for_real:
            return None

        matches = fitness_recorder.find_matching_history(prompt, opponent)
        if not matches:
            return None

        cached_match = matches[random.randint(0, len(matches) - 1)]
        return cached_match.get("match_score", cached_match.get("fitness_score", [0.0, 0.0]))

    def _record_match_score(
        self,
        *,
        individual: Individual,
        prompt: str,
        fitness: list[float],
        opponent: str | None,
        evaluation_mode: str,
        generation: int | None,
        stats: dict[str, float],
        fitness_recorder: FitnessRecorder | None,
    ) -> None:
        """Persist one normalized single-match score into the history recorder."""
        if fitness_recorder is None:
            return

        fitness_recorder.record_fitness(
            {
                "individual_id": getattr(individual, "id", None),
                "generation": generation,
                "prompt": prompt,
                "match_score": fitness,
                "fitness": fitness,
                "fitness_score": fitness,
                "opponent": opponent,
                "evaluation_mode": evaluation_mode,
                "evaluation_time": stats.get("total_eval_time", 0.0),
                "components": {
                    "game_rule": individual.game_rule,
                    "static_components": dict(individual.static_components),
                    "strategy": dict(individual.strategy),
                },
            }
        )

    def _store_real_evaluation(
        self,
        *,
        individual: Individual,
        fitness: list[float],
        simulation_meta: dict[str, Any],
    ) -> None:
        """Attach rich real-match metadata used by reflection and later analysis."""
        parsed_log = simulation_meta.get("parsed_log")
        timeout = bool(simulation_meta.get("timeout", False))
        summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else {}
        individual.last_real_evaluation = {
            "winner": simulation_meta.get("winner"),
            "timeout": timeout,
            "log_path": simulation_meta.get("log_path"),
            "parsed_log": parsed_log,
            "parsed_summary": summary,
            "reflection_context": Reflection.build_compact_reflection_context(
                parsed_log=parsed_log,
                fitness=fitness,
                timeout=timeout,
                max_turn_hint=read_max_turn_hint(self.repo_root),
            ),
            "raw_resource_advantage_score": (
                raw_resource_advantage_score(parsed_log, self.config.resource_advantage_weights)
                if isinstance(parsed_log, dict)
                else 0.0
            ),
        }

    def _write_real_evaluation_profile(
        self,
        *,
        individual: Individual,
        generation: int | None,
        prompt: str,
        opponent: str | None,
        fitness: list[float],
        stats: dict[str, float],
        operator_profile: dict[str, Any] | None,
        simulation_meta: dict[str, Any],
        profile_output_path: str | Path,
    ) -> None:
        """Write one profile record for a real match evaluation."""
        parsed_log = simulation_meta.get("parsed_log")
        llm_calls = simulation_meta.get("llm_calls", 0)

        record = build_base_record(
            generation=generation,
            individual_id=getattr(individual, "id", None),
            record_type="evaluation",
        )
        record.update(
            {
                "evaluation_mode": "real",
                "opponent": opponent,
                "prompt_length": len(prompt),
                "winner": simulation_meta.get("winner"),
                "timeout": simulation_meta.get("timeout", False),
                "llm_calls": llm_calls,
                "avg_llm_call_time": None,
                "max_llm_call_time": None,
                "game_llm_call_time": None,
                "ea_llm_call_time": stats.get("surrogate_time", 0.0)
                + ((operator_profile or {}).get("ea_llm_call_time", 0.0)),
                "match_score": fitness,
                "fitness": fitness,
                "log_path": simulation_meta.get("log_path"),
            }
        )
        for key in (
            "prompt_render_time",
            "EA_operator_time",
            "mutation_time",
            "crossover_time",
            "surrogate_time",
            "game_launch_time",
            "game_play_time",
            "log_parse_time",
            "bookkeeping_time",
            "total_eval_time",
        ):
            record[key] = stats.get(key, 0.0)
        if isinstance(parsed_log, dict):
            summary = parsed_log.get("summary", {})
            record["parsed_summary"] = summary
            record["llm_calls"] = summary.get("segment_count", llm_calls)
        write_jsonl(record, profile_output_path)

    def construct_prompt(self, individual: Individual) -> str:
        static_prompt_lines = []
        if self.component_pool.has_category("game_rule"):
            static_prompt_lines = self.component_pool.render_selected_static_prompt_lines(
                individual.static_components,
                game_rule_index=individual.game_rule,
            )
        strategy_prompt_lines = self.component_pool.render_strategy_prompt_lines(
            individual.strategy,
            include_strategy_identity=self.config.include_strategy_identity_in_prompt,
        )
        prompt_lines = static_prompt_lines.copy()
        if prompt_lines and strategy_prompt_lines:
            prompt_lines.append("")
        prompt_lines.extend(strategy_prompt_lines)
        return "\n".join(prompt_lines)

    def run_prompt_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        llm_interval: int | None = None,
        test: bool = False,
        stats: dict[str, float] | None = None,
    ) -> tuple[list[float], dict[str, Any]]:
        """Run one real EAGLE match for an already-rendered prompt."""
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            if stats is None:
                return run_prompt_based_game(
                    project_root=self.repo_root,
                    config=self.config,
                    prompt=prompt,
                    opponent=opponent,
                    test=test,
                    runtime_logs_dir=self.runtime_logs_dir,
                )
            with timer("game_play_time", stats):
                return run_prompt_based_game(
                    project_root=self.repo_root,
                    config=self.config,
                    prompt=prompt,
                    opponent=opponent,
                    test=test,
                    runtime_logs_dir=self.runtime_logs_dir,
                )
        finally:
            self.config.set_active_llm_interval(original_interval)

    def run_surrogate_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        ai1_class: str = "ai.abstraction.EAGLESurrogate",
        llm_interval: int | None = None,
        test: bool = False,
        stats: dict[str, float] | None = None,
    ) -> tuple[list[float], dict[str, Any]]:
        """Run one generated Java surrogate match for an already-rendered prompt."""
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            if stats is None:
                return run_java_agent_game(
                    project_root=self.repo_root,
                    config=self.config,
                    ai1_class=ai1_class,
                    opponent=opponent,
                    prompt=prompt,
                    compile_first=True,
                    log_prefix="run_surrogate" if not test else "run_test_surrogate",
                    runtime_logs_dir=self.runtime_logs_dir,
                    record_trace=bool(test and getattr(self.config, "save_trace_on_test", False)),
                )
            with timer("game_play_time", stats):
                return run_java_agent_game(
                    project_root=self.repo_root,
                    config=self.config,
                    ai1_class=ai1_class,
                    opponent=opponent,
                    prompt=prompt,
                    compile_first=True,
                    log_prefix="run_surrogate" if not test else "run_test_surrogate",
                    runtime_logs_dir=self.runtime_logs_dir,
                    record_trace=bool(test and getattr(self.config, "save_trace_on_test", False)),
                )
        finally:
            self.config.set_active_llm_interval(original_interval)

    def surrogate_evaluation(
        self,
        prompt: str,
        opponent: str | None = None,
    ) -> list[float]:
        return evaluate_with_java_surrogate(
            prompt,
            repo_root=self.repo_root,
            config=self.config,
            opponent=opponent,
        )
