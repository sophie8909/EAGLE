"""Full-game MicroRTS evaluation helpers for the EAGLE runtime pipeline."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ...config import EAConfig
from ...envs.microrts.runner import run_java_agent_game, run_prompt_based_game
from ...objectives.registry import get_objective
from ...reflection.microrts.game_log_reflection_context import Reflection, read_max_turn_hint
from ...project import PROJECT_ROOT
from ...utils.component_pool import ComponentPool
from ...utils.match_score_recorder import MatchScoreRecorder
from ...evolution.component.individual import Individual
from ...utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl

DEFAULT_REAL_EVAL_OPPONENTS = [
    "ai.abstraction.LightRush",
    "ai.abstraction.HeavyRush",
]


class FullGameEvaluator:
    """Evaluate one MicroRTS individual through real or policy-backed matches."""

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
        self.objective = get_objective(
            getattr(self.config, "objective_operator", "microrts_opponent")
        )

    def evaluate(
        self,
        individual: Individual,
        *,
        generation: int | None = None,
        profile_output_path: str | Path | None = None,
        match_score_recorder: MatchScoreRecorder | None = None,
        opponents: list[str] | None = None,
        allow_history_reuse: bool = False,
    ) -> dict[str, Any]:
        """Run real evaluation across opponents and aggregate EA fitness."""
        active_llm_interval = self.config.set_active_llm_interval_for_generation(generation)
        prompt = self._construct_prompt(individual)
        resolved_opponents = list(opponents) if opponents is not None else self._configured_real_eval_opponents()

        opponent_scores: list[tuple[str | None, float]] = []
        per_opponent_results: list[dict[str, Any]] = []
        evaluation_modes: list[str] = []

        for opponent in resolved_opponents:
            result = self.run_prompt_based_agent(
                individual=individual,
                prompt=prompt,
                opponent=opponent,
                generation=generation,
                profile_output_path=profile_output_path,
                match_score_recorder=match_score_recorder,
                allow_history_reuse=allow_history_reuse,
            )
            match_score = dict(result["match_score"])
            simulation_meta = dict(result.get("simulation_meta") or {})
            evaluation_mode = str(result.get("evaluation_mode") or "real")
            evaluation_modes.append(evaluation_mode)

            self._record_match_score(
                individual=individual,
                prompt=prompt,
                match_score=match_score,
                opponent=opponent,
                evaluation_mode=evaluation_mode,
                generation=generation,
                stats=result.get("stats", {}),
                match_score_recorder=match_score_recorder,
            )

            if evaluation_mode == "real":
                self._store_real_match_metadata(
                    individual=individual,
                    match_score=match_score,
                    simulation_meta=simulation_meta,
                )

            parsed_log = simulation_meta.get("parsed_log")
            raw_score = self._raw_resource_advantage_score(match_score)
            combined_score = self.objective(
                match_score,
                config=self.config,
                target=opponent,
                index=len(opponent_scores),
            )
            opponent_scores.append((opponent, combined_score))
            per_opponent_results.append(
                {
                    "opponent": opponent,
                    "match_score": match_score,
                    "combined_score": combined_score,
                    "raw_resource_advantage_score": raw_score,
                    "winner": simulation_meta.get("winner"),
                    "timeout": simulation_meta.get("timeout"),
                    "log_path": simulation_meta.get("log_path"),
                    "parsed_summary": (parsed_log or {}).get("summary", {}) if isinstance(parsed_log, dict) else {},
                    "evaluation_mode": evaluation_mode,
                }
            )

        aggregated_fitness = self._build_opponent_score_vector(
            opponent_scores,
            resolved_opponents,
            self.objective,
        )
        individual.fitness = dict(aggregated_fitness)
        individual.rendered_prompt = prompt
        individual.evaluation_mode = (
            "history_reuse"
            if evaluation_modes and all(mode == "history_reuse" for mode in evaluation_modes)
            else "real"
        )
        if hasattr(individual, "last_surrogate_evaluation"):
            delattr(individual, "last_surrogate_evaluation")
        individual.last_real_evaluation = {
            "mode": "multi_opponent_opponent_vector",
            "opponents": resolved_opponents,
            "llm_interval": active_llm_interval,
            "per_opponent": per_opponent_results,
            "aggregated_fitness": dict(aggregated_fitness),
        }
        return {
            "prompt": prompt,
            "fitness": dict(aggregated_fitness),
            "evaluation_mode": individual.evaluation_mode,
            "scores": per_opponent_results,
        }

    def surrogate(
        self,
        individual: Individual,
        *,
        generation: int | None = None,
        opponents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run surrogate evaluation across opponents and aggregate EA fitness."""
        active_llm_interval = self.config.set_active_llm_interval_for_generation(generation)
        prompt = self._construct_prompt(individual)
        resolved_opponents = list(opponents) if opponents is not None else self._configured_real_eval_opponents()

        opponent_scores: list[tuple[str | None, float]] = []
        per_opponent_scores: list[dict[str, object]] = []
        for opponent in resolved_opponents:
            result = self.run_java_based_agent(
                individual=individual,
                prompt=prompt,
                opponent=opponent,
            )
            match_score = dict(result["match_score"])
            raw_score = self._raw_resource_advantage_score(match_score)
            combined_score = self.objective(
                match_score,
                config=self.config,
                target=opponent,
                index=len(opponent_scores),
            )
            opponent_scores.append((opponent, combined_score))
            per_opponent_scores.append(
                {
                    "opponent": opponent,
                    "match_score": match_score,
                    "combined_score": combined_score,
                    "raw_resource_advantage_score": raw_score,
                }
            )

        aggregated_fitness = self._build_opponent_score_vector(
            opponent_scores,
            resolved_opponents,
            self.objective,
        )
        individual.fitness = dict(aggregated_fitness)
        individual.rendered_prompt = prompt
        individual.evaluation_mode = "surrogate"
        individual.last_surrogate_evaluation = {
            "mode": "multi_opponent_opponent_vector",
            "opponents": resolved_opponents,
            "llm_interval": active_llm_interval,
            "scores": per_opponent_scores,
            "aggregated_fitness": dict(aggregated_fitness),
        }
        return {
            "prompt": prompt,
            "fitness": dict(aggregated_fitness),
            "evaluation_mode": "surrogate",
            "scores": per_opponent_scores,
        }

    def run_prompt_based_agent(
        self,
        *,
        individual: Individual | None = None,
        prompt: str | None = None,
        opponent: str | None = None,
        generation: int | None = None,
        profile_output_path: str | Path | None = None,
        match_score_recorder: MatchScoreRecorder | None = None,
        allow_history_reuse: bool = False,
        llm_interval: int | None = None,
        test: bool = False,
    ) -> dict[str, Any]:
        """Run one real EAGLE match and return the raw single-match payload."""
        rendered_prompt = prompt if prompt is not None else self._construct_prompt(individual)
        stats: dict[str, float] = {}

        history_match_score = self._lookup_history_match_score(
            prompt=rendered_prompt,
            opponent=opponent,
            allow_history_reuse=allow_history_reuse,
            match_score_recorder=match_score_recorder,
        )
        if history_match_score is not None:
            return {
                "prompt": rendered_prompt,
                "match_score": dict(history_match_score),
                "simulation_meta": {},
                "stats": stats,
                "evaluation_mode": "history_reuse",
            }

        with timer("game_play_time", stats):
            match_score, simulation_meta = self._run_prompt_match(
                rendered_prompt,
                opponent,
                llm_interval=llm_interval,
                test=test,
            )
        summarize_total_eval_time(stats)

        if profile_output_path is not None:
            self._write_real_match_profile(
                individual=individual,
                generation=generation,
                prompt=rendered_prompt,
                opponent=opponent,
                match_score=dict(match_score),
                stats=stats,
                simulation_meta=simulation_meta,
                profile_output_path=profile_output_path,
            )

        return {
            "prompt": rendered_prompt,
            "match_score": dict(match_score),
            "simulation_meta": simulation_meta,
            "stats": stats,
            "evaluation_mode": "real",
        }

    def run_java_based_agent(
        self,
        *,
        individual: Individual | None = None,
        prompt: str | None = None,
        opponent: str | None = None,
        ai1_class: str = "ai.abstraction.eaglePolicy",
        llm_interval: int | None = None,
        test: bool = False,
    ) -> dict[str, Any]:
        """Run one policy-backed Java-agent match and return the raw single-match payload."""
        rendered_prompt = prompt if prompt is not None else self._construct_prompt(individual)
        stats: dict[str, float] = {}
        with timer("game_play_time", stats):
            match_score, simulation_meta = self._run_java_match(
                rendered_prompt,
                opponent,
                ai1_class=ai1_class,
                llm_interval=llm_interval,
                test=test,
            )
        summarize_total_eval_time(stats)
        return {
            "prompt": rendered_prompt,
            "match_score": dict(match_score),
            "simulation_meta": simulation_meta,
            "stats": stats,
            "evaluation_mode": "surrogate",
        }

    def _construct_prompt(self, individual: Individual) -> str:
        prompt_lines = self.component_pool.render_prompt_lines(
            individual.component_indices,
            include_identity_component=self.config.include_strategy_identity_in_prompt,
        )
        return "\n".join(prompt_lines)

    def _run_prompt_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        llm_interval: int | None = None,
        test: bool = False,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            match_score, simulation_meta = run_prompt_based_game(
                project_root=self.repo_root,
                config=self.config,
                prompt=prompt,
                opponent=opponent,
                test=test,
                runtime_logs_dir=self.runtime_logs_dir,
            )
            return self._normalize_match_score(match_score), simulation_meta
        finally:
            self.config.set_active_llm_interval(original_interval)

    def _run_java_match(
        self,
        prompt: str,
        opponent: str | None,
        *,
        ai1_class: str,
        llm_interval: int | None = None,
        test: bool = False,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        original_interval = getattr(self.config, "_active_llm_interval", None)
        if llm_interval is not None:
            self.config.set_active_llm_interval(int(llm_interval))
        try:
            match_score, simulation_meta = run_java_agent_game(
                project_root=self.repo_root,
                config=self.config,
                ai1_class=ai1_class,
                opponent=opponent,
                prompt=prompt,
                compile_first=True,
                log_prefix="run_eagle_policy" if not test else "run_test_eagle_policy",
                runtime_logs_dir=self.runtime_logs_dir,
                record_trace=bool(test and getattr(self.config, "save_trace_on_test", False)),
            )
            return self._normalize_match_score(match_score), simulation_meta
        finally:
            self.config.set_active_llm_interval(original_interval)

    def _configured_real_eval_opponents(self) -> list[str]:
        configured_opponents = list(getattr(self.config, "real_eval_opponents", []) or [])
        return configured_opponents or list(DEFAULT_REAL_EVAL_OPPONENTS)

    def _lookup_history_match_score(
        self,
        *,
        prompt: str,
        opponent: str | None,
        allow_history_reuse: bool,
        match_score_recorder: MatchScoreRecorder | None,
    ) -> dict[str, float] | None:
        if match_score_recorder is None or not allow_history_reuse:
            return None
        matches = match_score_recorder.find_matching_history(prompt, opponent)
        if not matches:
            return None
        cached_match = matches[random.randint(0, len(matches) - 1)]
        return self._normalize_match_score(cached_match.get("match_score"))

    def _record_match_score(
        self,
        *,
        individual: Individual,
        prompt: str,
        match_score: dict[str, float],
        opponent: str | None,
        evaluation_mode: str,
        generation: int | None,
        stats: dict[str, float],
        match_score_recorder: MatchScoreRecorder | None,
    ) -> None:
        if match_score_recorder is None:
            return
        match_score_recorder.record_match_score(
            {
                "individual_id": getattr(individual, "id", None),
                "generation": generation,
                "prompt": prompt,
                "match_score": dict(match_score),
                "opponent": opponent,
                "evaluation_mode": evaluation_mode,
                "evaluation_time": stats.get("total_eval_time", 0.0),
                "components": {
                    "game_rule": individual.game_rule,
                    "component_indices": dict(individual.component_indices),
                },
            }
        )

    def _store_real_match_metadata(
        self,
        *,
        individual: Individual,
        match_score: dict[str, float],
        simulation_meta: dict[str, Any],
    ) -> None:
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
                match_score=match_score,
                timeout=timeout,
                max_turn_hint=read_max_turn_hint(self.repo_root),
            ),
            "raw_resource_advantage_score": self._raw_resource_advantage_score(match_score),
        }

    def _write_real_match_profile(
        self,
        *,
        individual: Individual | None,
        generation: int | None,
        prompt: str,
        opponent: str | None,
        match_score: dict[str, float],
        stats: dict[str, float],
        simulation_meta: dict[str, Any],
        profile_output_path: str | Path,
    ) -> None:
        parsed_log = simulation_meta.get("parsed_log")
        llm_calls = simulation_meta.get("llm_calls", 0)
        record = build_base_record(
            generation=generation,
            individual_id=getattr(individual, "id", None) if individual is not None else None,
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
                "ea_llm_call_time": 0.0,
                "match_score": dict(match_score),
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
    def _normalize_match_score(match_score: Any) -> dict[str, float]:
        if isinstance(match_score, dict):
            return {
                "win_score": float(match_score.get("win_score", 0.0)),
                "raw_resource_advantage_score": float(match_score.get("raw_resource_advantage_score", 0.0)),
            }
        if isinstance(match_score, (list, tuple)):
            win_score = float(match_score[0]) if len(match_score) > 0 else 0.0
            raw_resource_score = float(match_score[1]) if len(match_score) > 1 else 0.0
            return {
                "win_score": win_score,
                "raw_resource_advantage_score": raw_resource_score,
            }
        return {
            "win_score": 0.0,
            "raw_resource_advantage_score": 0.0,
        }

    @staticmethod
    def _raw_resource_advantage_score(match_score: dict[str, Any] | None) -> float:
        if not isinstance(match_score, dict):
            return 0.0
        try:
            return float(match_score.get("raw_resource_advantage_score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _build_opponent_score_vector(
        opponent_scores: list[tuple[str | None, float]],
        configured_opponents: list[str | None],
        objective=None,
    ) -> dict[str, float]:
        if not configured_opponents:
            configured_opponents = [None]
        score_by_opponent = {opponent: score for opponent, score in opponent_scores}
        objective = objective or get_objective("microrts_opponent")
        return {
            objective.objective_key(opponent, index): float(score_by_opponent.get(opponent, 0.0))
            for index, opponent in enumerate(configured_opponents)
        }
