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
    combined_match_fitness_score,
    raw_resource_advantage_score,
)
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.fitness_utils import normalize_fitness
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
        3. Otherwise run one real MicroRTS match.
        4. Normalize and persist the resulting single-match score.

        This function only manages one match against one opponent. Higher-level EA
        code is responsible for combining per-opponent match scores into EA fitness.
        """
        if not use_real_evaluation:
            raise ValueError(
                "Evaluator.evaluate() now only supports real evaluation. "
                "Use Evaluator.evaluate_surrogate_individual() or Evaluator.run_surrogate_match() for surrogate paths."
            )

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
            evaluation_mode = "history_reuse"
        else:
            fitness, simulation_meta = self.run_prompt_match(prompt, opponent, stats=stats)
            evaluation_mode = "real"

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

    @staticmethod
    def _combined_match_score(
        fitness: list[float] | None,
        *,
        win_bonus: float,
        raw_resource_score: float | None = None,
    ) -> float:
        """Collapse one raw match score into one EA scalar slot."""
        normalized = normalize_fitness(fitness)
        if raw_resource_score is not None:
            return float(raw_resource_score) + float(win_bonus) * float(normalized[0])
        return combined_match_fitness_score(
            normalized,
            win_bonus=win_bonus,
        )

    @staticmethod
    def _build_opponent_score_vector(
        opponent_scores: list[tuple[str | None, float]],
        configured_opponents: list[str | None],
    ) -> list[float]:
        """Build the fixed-width EA fitness vector aligned to configured opponent order."""
        if not configured_opponents:
            configured_opponents = [None]

        score_by_opponent = {opponent: score for opponent, score in opponent_scores}
        values = [
            float(score_by_opponent.get(opponent, 0.0))
            for opponent in configured_opponents[:2]
        ]
        while len(values) < 2:
            values.append(0.0)
        return values

    def configured_real_eval_opponents(self) -> list[str]:
        """Return the ordered real-evaluation opponents that define EA fitness slots."""
        configured_opponents = list(getattr(self.config, "real_eval_opponents", []) or [])
        return configured_opponents or list(DEFAULT_REAL_EVAL_OPPONENTS)

    def evaluate_real_individual(
        self,
        individual: Individual,
        *,
        generation: int | None = None,
        profile_output_path: str | Path | None = None,
        fitness_recorder: FitnessRecorder | None = None,
        opponents: list[str] | None = None,
    ) -> list[float]:
        """Run the ordered real-opponent sweep and overwrite EA fitness on the individual."""
        active_llm_interval = self.config.set_active_llm_interval_for_generation(generation)
        real_eval_opponents = list(opponents or self.configured_real_eval_opponents())

        opponent_scores: list[tuple[str | None, float]] = []
        per_opponent_results: list[dict[str, Any]] = []

        for resolved_opponent in real_eval_opponents:
            self.evaluate(
                individual,
                use_real_evaluation=True,
                allow_history_reuse_for_real=bool(generation == -1),
                opponent=resolved_opponent,
                profile_output_path=profile_output_path,
                generation=generation,
                fitness_recorder=fitness_recorder,
            )
            normalized_fitness = normalize_fitness(individual.fitness)
            last_real_evaluation = getattr(individual, "last_real_evaluation", {}) or {}
            parsed_log = last_real_evaluation.get("parsed_log")
            raw_score = (
                raw_resource_advantage_score(
                    parsed_log,
                    self.config.resource_advantage_weights,
                )
                if isinstance(parsed_log, dict)
                else 0.0
            )
            combined_score = self._combined_match_score(
                normalized_fitness,
                win_bonus=self.config.win_bonus,
                raw_resource_score=raw_score,
            )
            opponent_scores.append((resolved_opponent, combined_score))
            per_opponent_results.append(
                {
                    "opponent": resolved_opponent,
                    "fitness": list(normalized_fitness),
                    "combined_score": combined_score,
                    "raw_resource_advantage_score": raw_score,
                    "winner": last_real_evaluation.get("winner"),
                    "timeout": last_real_evaluation.get("timeout"),
                    "log_path": last_real_evaluation.get("log_path"),
                    "parsed_summary": last_real_evaluation.get("parsed_summary"),
                }
            )

        individual.fitness = self._build_opponent_score_vector(opponent_scores, real_eval_opponents)
        individual.evaluation_mode = "real"
        if hasattr(individual, "last_surrogate_evaluation"):
            delattr(individual, "last_surrogate_evaluation")
        individual.last_real_evaluation = {
            "mode": "multi_opponent_opponent_vector",
            "opponents": real_eval_opponents,
            "llm_interval": active_llm_interval,
            "per_opponent": per_opponent_results,
            "aggregated_fitness": list(individual.fitness),
        }
        return list(individual.fitness)

    def evaluate_surrogate_individual(
        self,
        individual: Individual,
        *,
        opponent_list: list[str] | None = None,
        generation: int | None = None,
    ) -> list[float]:
        """Run explicit surrogate matches and aggregate them into EA fitness."""
        active_llm_interval = self.config.set_active_llm_interval_for_generation(generation)
        surrogate_mode = str(self.config.surrogate_mode).strip().lower()
        prompt = self.construct_prompt(individual)

        if surrogate_mode == "random":
            surrogate_opponent = random.choice(opponent_list) if opponent_list else None
            match_score, metadata = self.run_surrogate_match(
                prompt=prompt,
                opponent=surrogate_opponent,
            )
            raw_fitness = normalize_fitness(match_score)
            parsed_log = metadata.get("parsed_log") if isinstance(metadata, dict) else None
            raw_score = (
                raw_resource_advantage_score(
                    parsed_log,
                    self.config.resource_advantage_weights,
                )
                if isinstance(parsed_log, dict)
                else None
            )
            configured_opponents = list(opponent_list) if opponent_list else [surrogate_opponent]
            combined_score = self._combined_match_score(
                raw_fitness,
                win_bonus=self.config.win_bonus,
                raw_resource_score=raw_score,
            )
            individual.fitness = self._build_opponent_score_vector(
                [(surrogate_opponent, combined_score)],
                configured_opponents,
            )
            individual.last_surrogate_evaluation = {
                "mode": "random",
                "opponents": [surrogate_opponent],
                "llm_interval": active_llm_interval,
                "scores": [
                    {
                        "opponent": surrogate_opponent,
                        "fitness": raw_fitness,
                        "combined_score": combined_score,
                        "raw_resource_advantage_score": raw_score,
                    }
                ],
                "aggregated_fitness": list(individual.fitness),
            }
            individual.evaluation_mode = "surrogate"
            return list(individual.fitness)

        if surrogate_mode == "all_avg":
            opponents = list(opponent_list) if opponent_list else [None]
            opponent_scores: list[tuple[str | None, float]] = []
            per_opponent_scores: list[dict[str, object]] = []

            for surrogate_opponent in opponents:
                match_score, metadata = self.run_surrogate_match(
                    prompt=prompt,
                    opponent=surrogate_opponent,
                )
                sampled_fitness = normalize_fitness(match_score)
                parsed_log = metadata.get("parsed_log") if isinstance(metadata, dict) else None
                raw_score = (
                    raw_resource_advantage_score(
                        parsed_log,
                        self.config.resource_advantage_weights,
                    )
                    if isinstance(parsed_log, dict)
                    else None
                )
                combined_score = self._combined_match_score(
                    sampled_fitness,
                    win_bonus=self.config.win_bonus,
                    raw_resource_score=raw_score,
                )
                opponent_scores.append((surrogate_opponent, combined_score))
                per_opponent_scores.append(
                    {
                        "opponent": surrogate_opponent,
                        "fitness": sampled_fitness,
                        "combined_score": combined_score,
                        "raw_resource_advantage_score": raw_score,
                    }
                )

            aggregated_fitness = self._build_opponent_score_vector(opponent_scores, opponents)
            individual.fitness = list(aggregated_fitness)
            individual.evaluation_mode = "surrogate"
            individual.last_surrogate_evaluation = {
                "mode": "all_avg",
                "opponents": opponents,
                "llm_interval": active_llm_interval,
                "scores": per_opponent_scores,
                "aggregated_fitness": aggregated_fitness,
            }
            return list(individual.fitness)

        raise ValueError(f"Unsupported surrogate_mode: {self.config.surrogate_mode}")

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
