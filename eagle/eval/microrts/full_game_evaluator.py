"""Full-game MicroRTS evaluation helpers for the EAGLE runtime pipeline."""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ...config import EAConfig
from ...envs.microrts.runner import run_java_agent_game, run_prompt_based_game
from ...objectives.registry import objective_eval_mode
from ...reflection.microrts.game_log_reflection_context import Reflection, read_max_turn_hint
from ...project import PROJECT_ROOT
from ...utils.component_pool import ComponentPool
from ...utils.match_score_recorder import MatchScoreRecorder
from ...evolution.component.individual import Individual
from ...utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl

DEFAULT_GAMEPLAY_OPPONENTS = [
    "ai.abstraction.LightRush",
    "ai.abstraction.HeavyRush",
]


class FullGameEvaluator:
    """Evaluate one MicroRTS individual through gameplay or policy-backed matches."""

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
        *,
        generation: int | None = None,
        profile_output_path: str | Path | None = None,
        match_score_recorder: MatchScoreRecorder | None = None,
        opponents: list[str] | None = None,
        allow_history_reuse: bool = False,
    ) -> dict[str, Any]:
        """Run gameplay evaluation across opponents and aggregate EA fitness."""
        active_llm_interval = self.config.set_active_llm_interval_for_generation(generation)
        prompt = self._construct_prompt(individual)
        resolved_opponents = list(opponents) if opponents is not None else self._configured_gameplay_opponents()
        surrogate = (
            str(getattr(self.config, "surrogate", ""))
            if str(getattr(self.config, "algorithm", "")).strip().lower() == "ga_surrogate"
            else ""
        )
        print(
            "[DEBUG] gameplay evaluate start "
            f"individual={individual.id} generation={generation} surrogate={surrogate} "
            f"objective_config={getattr(self.config, 'objective_config', {})} "
            f"opponents={resolved_opponents}",
            flush=True,
        )

        per_opponent_results: list[dict[str, Any]] = []
        evaluation_modes: list[str] = []

        opponent_results = self._evaluate_agent_opponents_parallel(
            resolved_opponents,
            lambda opponent: self._run_gameplay_mode(
                individual=individual,
                prompt=prompt,
                opponent=opponent,
                generation=generation,
                profile_output_path=profile_output_path,
                match_score_recorder=match_score_recorder,
                allow_history_reuse=allow_history_reuse,
            ),
            label="gameplay",
            individual_id=getattr(individual, "id", None),
            generation=generation,
        )
        for opponent, result in opponent_results:
            match_score = dict(result["match_score"])
            simulation_meta = dict(result.get("simulation_meta") or {})
            evaluation_mode = str(result.get("evaluation_mode") or "gameplay")
            evaluation_modes.append(evaluation_mode)

            self._record_match_score(
                individual=individual,
                prompt=prompt,
                match_score=match_score,
                opponent=opponent,
                evaluation_mode=evaluation_mode,
                generation=generation,
                stats=result.get("stats", {}),
                simulation_meta=simulation_meta,
                match_score_recorder=match_score_recorder,
            )

            if evaluation_mode == "gameplay":
                self._store_gameplay_match_metadata(
                    individual=individual,
                    match_score=match_score,
                    simulation_meta=simulation_meta,
                )

            parsed_log = simulation_meta.get("parsed_log")
            raw_score = self._raw_resource_advantage_score(match_score)
            per_opponent_results.append(
                {
                    "opponent": opponent,
                    "match_score": match_score,
                    "raw_resource_advantage_score": raw_score,
                    "winner": simulation_meta.get("winner"),
                    "timeout": simulation_meta.get("timeout"),
                    "log_path": simulation_meta.get("log_path"),
                    "trace_xml_path": simulation_meta.get("trace_xml_path"),
                    "parsed_summary": (parsed_log or {}).get("summary", {}) if isinstance(parsed_log, dict) else {},
                    "evaluation_mode": evaluation_mode,
                }
            )
            print(
                "[DEBUG] gameplay opponent result "
                f"individual={individual.id} opponent={opponent} mode={evaluation_mode} "
                f"match_score={match_score}",
                flush=True,
            )

        eval_result = self._aggregate_raw_eval_result({
            "eval_mode": objective_eval_mode(self.config, {"scores": per_opponent_results}),
            "evaluation_mode": "gameplay",
            "surrogate": surrogate,
            "opponents": resolved_opponents,
            "scores": per_opponent_results,
        })
        individual.rendered_prompt = prompt
        individual.evaluation_mode = (
            "history_reuse"
            if evaluation_modes and all(mode == "history_reuse" for mode in evaluation_modes)
            else "gameplay"
        )
        if hasattr(individual, "last_surrogate_evaluation"):
            delattr(individual, "last_surrogate_evaluation")
        individual.last_gameplay_evaluation = {
            "mode": "multi_opponent_opponent_vector",
            "surrogate": surrogate,
            "opponents": resolved_opponents,
            "llm_interval": active_llm_interval,
            "per_opponent": per_opponent_results,
            "eval_result": eval_result,
        }
        print(
            "[DEBUG] gameplay evaluate complete "
            f"individual={individual.id} eval_mode={eval_result['eval_mode']}",
            flush=True,
        )
        eval_result["prompt"] = prompt
        return eval_result

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
        resolved_opponents = list(opponents) if opponents is not None else self._configured_gameplay_opponents()

        per_opponent_scores: list[dict[str, object]] = []
        surrogate = str(getattr(self.config, "surrogate", "round")).strip().lower()
        if surrogate == "round":
            print(
                "[GA Surrogate] using round surrogate once "
                f"individual={getattr(individual, 'id', None)} generation={generation} "
                "opponents=none",
                flush=True,
            )
            result = self.run_round_surrogate(
                individual=individual,
                prompt=prompt,
                opponent=None,
                generation=generation,
            )
            match_score = dict(result["match_score"])
            raw_score = self._raw_resource_advantage_score(match_score)
            per_opponent_scores = [
                {
                    "match_score": dict(match_score),
                    "raw_resource_advantage_score": raw_score,
                }
            ]
            resolved_opponents = []
        else:
            if surrogate == "policy_agent":
                self._prepare_policy_agent(prompt)
            elif surrogate == "java_agent":
                if not self._prepare_generated_java_agent(prompt):
                    per_opponent_scores = [
                        {
                            "opponent": opponent,
                            "match_score": {"win_score": 0.0, "raw_resource_advantage_score": 0.0},
                            "raw_resource_advantage_score": 0.0,
                        }
                        for opponent in resolved_opponents
                    ]
            if not per_opponent_scores:
                opponent_results = self._evaluate_agent_opponents_parallel(
                    resolved_opponents,
                    lambda opponent: self._run_surrogate_agent_opponent(
                        surrogate=surrogate,
                        individual=individual,
                        prompt=prompt,
                        opponent=opponent,
                        generation=generation,
                    ),
                    label=surrogate,
                    individual_id=getattr(individual, "id", None),
                    generation=generation,
                )
                for opponent, result in opponent_results:
                    match_score = dict(result["match_score"])
                    raw_score = self._raw_resource_advantage_score(match_score)
                    per_opponent_scores.append(
                        {
                            "opponent": opponent,
                            "match_score": match_score,
                            "raw_resource_advantage_score": raw_score,
                        }
                    )

        eval_result = self._aggregate_raw_eval_result({
            "eval_mode": "java_surrogate",
            "evaluation_mode": "surrogate",
            "surrogate": surrogate,
            "opponents": resolved_opponents,
            "scores": per_opponent_scores,
        })
        individual.rendered_prompt = prompt
        individual.evaluation_mode = "surrogate"
        individual.last_surrogate_evaluation = {
            "mode": "multi_opponent_opponent_vector",
            "opponents": resolved_opponents,
            "llm_interval": active_llm_interval,
            "scores": per_opponent_scores,
            "eval_result": eval_result,
        }
        eval_result["prompt"] = prompt
        return eval_result

    def run_round_surrogate(
        self,
        *,
        individual: Individual,
        prompt: str | None = None,
        opponent: str | None = None,
        generation: int | None = None,
    ) -> dict[str, Any]:
        """Evaluate one candidate with the local round evaluator without launching Java."""
        from .round_evaluator import Evaluator as RoundEvaluator

        rendered_prompt = prompt if prompt is not None else self._construct_prompt(individual)
        round_evaluator = RoundEvaluator(
            self.component_pool,
            self.config,
            runtime_logs_dir=self.runtime_logs_dir,
        )
        round_eval_result = round_evaluator.evaluate(individual, generation=generation)
        round_score = self._round_surrogate_score(round_eval_result)
        return {
            "prompt": rendered_prompt,
            "match_score": {
                "win_score": 0.0,
                "raw_resource_advantage_score": round_score,
            },
            "simulation_meta": {
                "winner": None,
                "timeout": False,
                "round_eval_result": round_eval_result,
                "opponent": opponent,
            },
            "stats": {},
            "evaluation_mode": "round",
        }

    def _run_surrogate_agent_opponent(
        self,
        *,
        surrogate: str,
        individual: Individual,
        prompt: str,
        opponent: str | None,
        generation: int | None,
    ) -> dict[str, Any]:
        """Run one prepared Java-backed surrogate match for one opponent."""
        if surrogate == "java_agent":
            return self.run_java_based_agent(
                individual=individual,
                prompt=prompt,
                opponent=opponent,
                ai1_class="ai.abstraction.eagleJava",
                log_prefix="run_eagle_java",
                evaluation_mode="java_agent",
                compile_first=False,
                generation=generation,
            )
        if surrogate == "policy_agent":
            return self.run_java_based_agent(
                individual=individual,
                prompt=prompt,
                opponent=opponent,
                ai1_class="ai.abstraction.eaglePolicy",
                log_prefix="run_eagle_policy",
                evaluation_mode="policy_agent",
                compile_first=False,
                generation=generation,
            )
        raise ValueError(
            f"Unsupported surrogate={surrogate!r}. "
            "Expected one of: round, policy_agent, java_agent."
        )

    def _evaluate_agent_opponents_parallel(
        self,
        opponents: list[str | None],
        evaluate_one: Any,
        *,
        label: str,
        individual_id: Any,
        generation: int | None,
    ) -> list[tuple[str | None, dict[str, Any]]]:
        """Evaluate one Java-backed agent against opponents with bounded threads."""
        if not opponents:
            return []
        workers = self._agent_eval_parallel_workers(len(opponents))
        print(
            "[DEBUG] agent parallel start "
            f"label={label} individual={individual_id} generation={generation} "
            f"opponents={len(opponents)} workers={workers}",
            flush=True,
        )
        if workers <= 1:
            return [(opponent, evaluate_one(opponent)) for opponent in opponents]

        results: list[tuple[str | None, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(evaluate_one, opponent): opponent
                for opponent in opponents
            }
            for future in as_completed(futures):
                opponent = futures[future]
                results.append((opponent, future.result()))
        order = {opponent: index for index, opponent in enumerate(opponents)}
        return sorted(results, key=lambda item: order.get(item[0], 0))

    def _agent_eval_parallel_workers(self, opponent_count: int) -> int:
        """Return the bounded worker count for Java-backed agent evaluation."""
        try:
            configured = int(getattr(self.config, "agent_eval_parallel_workers", opponent_count))
        except (TypeError, ValueError):
            configured = opponent_count
        return max(1, min(int(opponent_count), configured))

    def _prepare_policy_agent(self, prompt: str) -> None:
        """Render and compile the reusable policy agent once before parallel matches."""
        from eagle.envs.microrts.compiler import compile_microrts
        from eagle.surrogate.compiler.eagle_policy_spec import compile_prompt_to_eagle_policy_spec
        from eagle.surrogate.eval.eagle_policy_renderer import render_eagle_policy_agent

        eagle_policy_spec = compile_prompt_to_eagle_policy_spec(prompt)[1]
        render_eagle_policy_agent(self.repo_root, prompt, eagle_policy_spec)
        compile_microrts(self.repo_root)

    def _prepare_generated_java_agent(self, prompt: str) -> bool:
        """Render and compile the generated eagleJava agent once before parallel matches."""
        from eagle.surrogate.java.eagle_java_compiler import compile_eagle_java_agent
        from eagle.surrogate.java.eagle_java_renderer import render_eagle_java_from_prompt

        cache_root = self.repo_root / "logs" / "eagle_java"
        java_code = render_eagle_java_from_prompt(prompt)
        return bool(compile_eagle_java_agent(java_code, str(cache_root)))

    def _run_gameplay_mode(
        self,
        *,
        individual: Individual,
        prompt: str,
        opponent: str | None,
        generation: int | None,
        profile_output_path: str | Path | None,
        match_score_recorder: MatchScoreRecorder | None,
        allow_history_reuse: bool,
    ) -> dict[str, Any]:
        """Dispatch one gameplay match according to the configured surrogate."""
        return self.run_prompt_based_agent(
            individual=individual,
            prompt=prompt,
            opponent=opponent,
            generation=generation,
            profile_output_path=profile_output_path,
            match_score_recorder=match_score_recorder,
            allow_history_reuse=allow_history_reuse,
        )

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
        """Run one gameplay EAGLE match and return the raw single-match payload."""
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
                generation=generation,
                individual_id=getattr(individual, "id", None) if individual is not None else None,
            )
        stats["microrts_compile_time"] = float(simulation_meta.get("compile_time_sec", 0.0) or 0.0)
        summarize_total_eval_time(stats)

        if profile_output_path is not None:
            self._write_gameplay_match_profile(
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
            "evaluation_mode": "gameplay",
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
        log_prefix: str = "run_eagle_policy",
        evaluation_mode: str = "policy_agent",
        compile_first: bool = True,
        generation: int | None = None,
    ) -> dict[str, Any]:
        """Run one policy-backed Java-agent match and return the raw single-match payload."""
        rendered_prompt = prompt if prompt is not None else self._construct_prompt(individual)
        stats: dict[str, float] = {}
        with timer("game_play_time", stats):
            if ai1_class == "ai.abstraction.eaglePolicy":
                if compile_first:
                    self._prepare_policy_agent(rendered_prompt)
                match_score, simulation_meta = self._run_java_match(
                    rendered_prompt,
                    opponent,
                    ai1_class=ai1_class,
                    llm_interval=llm_interval,
                    test=test,
                    log_prefix=log_prefix,
                    compile_first=False,
                    generation=generation,
                    individual_id=getattr(individual, "id", None) if individual is not None else None,
                )
            else:
                match_score, simulation_meta = self._run_java_match(
                    rendered_prompt,
                    opponent,
                    ai1_class=ai1_class,
                    llm_interval=llm_interval,
                    test=test,
                    log_prefix=log_prefix,
                    compile_first=compile_first,
                    generation=generation,
                    individual_id=getattr(individual, "id", None) if individual is not None else None,
                )
        stats["microrts_compile_time"] = float(simulation_meta.get("compile_time_sec", 0.0) or 0.0)
        summarize_total_eval_time(stats)
        return {
            "prompt": rendered_prompt,
            "match_score": dict(match_score),
            "simulation_meta": simulation_meta,
            "stats": stats,
            "evaluation_mode": evaluation_mode,
        }

    def run_generated_java_agent(
        self,
        *,
        individual: Individual | None = None,
        prompt: str | None = None,
        opponent: str | None = None,
    ) -> dict[str, Any]:
        """Compile and run the generated eagleJava agent for one match."""
        from eagle.surrogate.eval.eagle_java_match_evaluator import evaluate_with_eagle_java

        rendered_prompt = prompt if prompt is not None else self._construct_prompt(individual)
        match_score = evaluate_with_eagle_java(
            rendered_prompt,
            repo_root=self.repo_root,
            config=self.config,
            opponent=opponent,
        )
        return {
            "prompt": rendered_prompt,
            "match_score": dict(match_score),
            "simulation_meta": {},
            "stats": {},
            "evaluation_mode": "java_agent",
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
        generation: int | None = None,
        individual_id: Any | None = None,
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
                generation=generation,
                individual_id=individual_id,
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
        log_prefix: str = "run_eagle_policy",
        compile_first: bool = True,
        generation: int | None = None,
        individual_id: Any | None = None,
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
                compile_first=compile_first,
                log_prefix=log_prefix if not test else f"{log_prefix.replace('run_', 'run_test_', 1)}",
                runtime_logs_dir=self.runtime_logs_dir,
                record_trace=True,
                generation=generation,
                individual_id=individual_id,
            )
            return self._normalize_match_score(match_score), simulation_meta
        finally:
            self.config.set_active_llm_interval(original_interval)

    def _configured_gameplay_opponents(self) -> list[str]:
        configured_opponents = list(getattr(self.config, "gameplay_opponents", []) or [])
        return configured_opponents or list(DEFAULT_GAMEPLAY_OPPONENTS)

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
        simulation_meta: dict[str, Any],
        match_score_recorder: MatchScoreRecorder | None,
    ) -> None:
        if match_score_recorder is None:
            return
        parsed_log = simulation_meta.get("parsed_log")
        summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else {}
        match_score_recorder.record_match_score(
            {
                "individual_id": getattr(individual, "id", None),
                "generation": generation,
                "prompt": prompt,
                "match_score": dict(match_score),
                "opponent": opponent,
                "evaluation_mode": evaluation_mode,
                "evaluation_time": stats.get("total_eval_time", 0.0),
                "log_path": simulation_meta.get("log_path"),
                "trace_xml_path": simulation_meta.get("trace_xml_path"),
                "winner": simulation_meta.get("winner"),
                "timeout": simulation_meta.get("timeout"),
                "timeout_type": simulation_meta.get("timeout_type"),
                "llm_calls": simulation_meta.get("llm_calls"),
                "game_time_sec": simulation_meta.get("game_time_sec"),
                "parsed_summary": summary,
                "stats": dict(stats),
                "components": {
                    "game_rule": individual.game_rule,
                    "component_indices": dict(individual.component_indices),
                },
            }
        )

    def _store_gameplay_match_metadata(
        self,
        *,
        individual: Individual,
        match_score: dict[str, float],
        simulation_meta: dict[str, Any],
    ) -> None:
        parsed_log = simulation_meta.get("parsed_log")
        timeout = bool(simulation_meta.get("timeout", False))
        summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else {}
        individual.last_gameplay_evaluation = {
            "winner": simulation_meta.get("winner"),
            "timeout": timeout,
            "log_path": simulation_meta.get("log_path"),
            "trace_xml_path": simulation_meta.get("trace_xml_path"),
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

    def _write_gameplay_match_profile(
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
                "evaluation_mode": "gameplay",
                "opponent": opponent,
                "prompt": prompt,
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
                "trace_xml_path": simulation_meta.get("trace_xml_path"),
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
            "microrts_compile_time",
            "total_eval_time",
        ):
            record[key] = stats.get(key, 0.0)
        if isinstance(parsed_log, dict):
            summary = parsed_log.get("summary", {})
            record["parsed_summary"] = summary
            record["llm_calls"] = summary.get("segment_count", llm_calls)
        write_jsonl(record, profile_output_path)

    @staticmethod
    def _aggregate_raw_eval_result(eval_result: dict[str, Any]) -> dict[str, Any]:
        """Add top-level raw metrics averaged across opponent match results."""
        scores = list(eval_result.get("scores") or [])
        if not scores:
            eval_result.update(
                {
                    "resource_diff": 0.0,
                    "ally_units": 0.0,
                    "enemy_units": 0.0,
                    "winner": 0.0,
                    "game_ticks": 0.0,
                    "timeout": False,
                }
            )
            return eval_result

        resource_total = 0.0
        win_total = 0.0
        tick_total = 0.0
        ally_total = 0.0
        enemy_total = 0.0
        timeout = False
        for score in scores:
            match_score = dict(score.get("match_score") or {})
            resource_total += float(match_score.get("raw_resource_advantage_score", 0.0))
            win_total += float(match_score.get("win_score", 0.0))
            timeout = timeout or bool(score.get("timeout", False))
            summary = dict(score.get("parsed_summary") or {})
            resource_history = list(summary.get("resource_history") or [])
            if resource_history:
                tick_total += float(resource_history[-1].get("time", 0.0))
            feature_history = list(summary.get("feature_history") or [])
            if feature_history:
                final_features = dict(feature_history[-1])
                ally_total += sum(float(value) for value in dict(final_features.get("ally") or {}).values())
                enemy_total += sum(float(value) for value in dict(final_features.get("enemy") or {}).values())

        count = float(len(scores))
        eval_result.update(
            {
                "resource_diff": resource_total / count,
                "ally_units": ally_total / count,
                "enemy_units": enemy_total / count,
                "winner": win_total / count,
                "game_ticks": tick_total / count,
                "timeout": timeout,
            }
        )
        return eval_result

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
    def _round_surrogate_score(round_eval_result: dict[str, Any] | None) -> float:
        """Extract a scalar score from the round evaluator result."""
        if not isinstance(round_eval_result, dict):
            return 0.0
        for key in ("fitness", "round_score", "raw_resource_advantage_score", "score"):
            value = round_eval_result.get(key)
            if isinstance(value, dict):
                value = next(iter(value.values()), 0.0)
            elif isinstance(value, (list, tuple)):
                value = value[0] if value else 0.0
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0
