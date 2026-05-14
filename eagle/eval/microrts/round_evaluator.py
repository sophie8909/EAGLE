"""Single-round prompt evaluator for generated MicroRTS states."""

from __future__ import annotations

import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from eagle.config import EAConfig
from eagle.project import MICRORTS_LOGS_DIR
from eagle.evolution.component.individual import Individual
from eagle.utils.component_pool import ComponentPool
from eagle.utils.log_parse import parse_dynamic_prompt_state
from eagle.utils.move_validator import validate_llm_move_against_state
from eagle.utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl

from .prompt_history import PromptHistory
from .state_generator import StateGenerator

class Evaluator:
    """Evaluate prompts by asking an LLM for one generated game-state response."""

    MISSING_MOVES_FITNESS_SCORE = -2.0
    DEFAULT_ACTION_TYPE_SCORES = {
        "idle": 0.0,
        "move": 10.0,
        "harvest": 2.0,
        "build": 10.0,
        "train": 3.0,
        "attack": 3.0,
    }
    THEORETICAL_ALIGNMENT_MAX = 100.0

    def __init__(
        self,
        component_pool: ComponentPool,
        config: EAConfig | None = None,
        runtime_logs_dir: str | Path | None = None,
    ):
        self.component_pool = component_pool
        self.config = config or EAConfig()
        self.runtime_logs_dir = Path(runtime_logs_dir) if runtime_logs_dir is not None else None
        self.state_generator = StateGenerator(seed=getattr(self.config, "round_state_seed", None))
        self.model = str(getattr(self.config, "round_eval_model", "llama3.1:8b"))
        default_history_path = MICRORTS_LOGS_DIR / "round_evol" / "history.jsonl"
        self.history = PromptHistory(
            getattr(self.config, "prompt_history_path", str(default_history_path))
        )

    
    def evaluate(
        self,
        individual: Individual,
        *,
        generation: int | None = None,
        profile_output_path: str | Path | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Generate states, ask for actions, and return raw objective metrics."""
        base_prompt = self._construct_prompt(individual)
        print(
            "[DEBUG] round evaluate start "
            f"individual={individual.id} generation={generation} rounds={self.config.one_eval_rounds}",
            flush=True,
        )
        

        cached_record = self.history.get_record(base_prompt)
        cached_fitness = cached_record.get("fitness") if cached_record is not None else None
        cached_metadata = dict(cached_record.get("metadata") or {}) if cached_record else {}
        cached_eval_result = dict(cached_metadata.get("eval_result") or {}) if cached_record else {}
        cached_sample_count = self._history_sample_count(cached_record)

        if cached_fitness is not None:
            if random.random() < 0.5:
                print(
                    f"Found cached fitness for prompt (hash={self.history._hash_prompt(base_prompt)}), "
                    "using existing averaged fitness.",
                    flush=True,
                )
                eval_result = self._round_eval_result_from_cached(cached_fitness, cached_eval_result)
                eval_result.update(
                    {
                        "prompt": base_prompt,
                        "evaluation_mode": "history_avg",
                        "generation": generation,
                        "history_decision": "use_existing_average",
                    }
                )
                individual.last_round_evaluation = {
                    "generation": generation,
                    "base_prompt": base_prompt,
                    "cached_fitness": cached_fitness,
                    "cached_sample_count": cached_sample_count,
                    "eval_result": eval_result,
                    "history_decision": "use_existing_average",
                }
                self._write_round_profile(
                    individual=individual,
                    generation=generation,
                    profile_output_path=profile_output_path,
                    base_prompt=base_prompt,
                    eval_result=eval_result,
                    samples=[],
                    history_decision="use_existing_average",
                )
                print(
                    "[DEBUG] round evaluate complete "
                    f"individual={individual.id} mode=history_avg",
                    flush=True,
                )
                return eval_result
            print(
                f"Found cached fitness for prompt (hash={self.history._hash_prompt(base_prompt)}), "
                "running a fresh LLM evaluation and averaging.",
                flush=True,
            )

        legality_score_sum = 0.0
        alignment_score_sum = 0.0
        legality_raw_sum = 0.0
        alignment_raw_sum = 0.0
        valid_json_count = 0
        legal_action_count = 0
        illegal_action_count = 0
        action_type_score_sum_total = 0.0
        theoretical_legality_max_total = 0.0
        resource_diff_sum = 0.0
        round_samples: list[dict[str, Any]] = []
        stats: dict[str, float] = {}
        n = self.config.one_eval_rounds
        dynamic_prompts = [self.state_generator.generate_text() for _ in range(n)]
        workers = self._round_eval_parallel_workers(n)
        print(
            "[DEBUG] round parallel samples "
            f"individual={individual.id} generation={generation} rounds={n} workers={workers}",
            flush=True,
        )
        with timer("round_parallel_wall_time", stats):
            sample_results = self._evaluate_round_samples_parallel(
                base_prompt=base_prompt,
                dynamic_prompts=dynamic_prompts,
                generation=generation,
                individual_id=str(individual.id),
                workers=workers,
            )
        for result in sample_results:
            sample = dict(result["sample_record"])
            legality_details = dict(sample.get("legality") or {})
            valid_json_count += int(bool(sample.get("format_valid")))
            legality_raw = float(sample.get("raw_legality_score", 0.0))
            alignment_raw = float(sample.get("raw_strategy_alignment_score", 0.0))
            legality_score = float(sample.get("legality_score", 0.0))
            alignment_score = float(sample.get("strategy_alignment_score", 0.0))
            legality_raw_sum += legality_raw
            alignment_raw_sum += alignment_raw
            legality_score_sum += legality_score
            alignment_score_sum += alignment_score
            legal_action_count += int(legality_details.get("applicable_actions", 0))
            returned_actions = int(legality_details.get("returned_actions", 0))
            legal_count = int(legality_details.get("applicable_actions", 0))
            illegal_action_count += max(0, returned_actions - legal_count)
            action_type_score_sum_total += float(legality_details.get("action_type_score_sum", 0.0))
            theoretical_legality_max_total += float(result.get("legality_max", 0.0))
            resource_diff_sum += float(result.get("resource_diff", 0.0))
            self._merge_stats(stats, dict(result.get("stats") or {}))
            round_samples.append(sample)

        summarize_total_eval_time(stats)
        if "round_parallel_wall_time" in stats:
            stats["total_eval_time"] = stats["round_parallel_wall_time"]
        latest_eval_result = {
            "eval_mode": "round",
            "evaluation_mode": "round_llm",
            "prompt": base_prompt,
            "valid_json": valid_json_count == n,
            "valid_json_count": valid_json_count,
            "legal_action_count": legal_action_count,
            "illegal_action_count": illegal_action_count,
            "action_type_score_sum": action_type_score_sum_total,
            "theoretical_legality_max": theoretical_legality_max_total,
            "resource_diff": resource_diff_sum / n,
            "strategy_alignment_score": alignment_score_sum / n,
            "raw_legality_score": legality_raw_sum / n,
            "raw_strategy_alignment_score": alignment_raw_sum / n,
            "timing": dict(stats),
            "round_eval_parallel_workers": workers,
        }
        eval_result = self._average_history_eval_result(
            cached_fitness,
            cached_eval_result,
            latest_eval_result,
            cached_sample_count,
        )
        eval_result.setdefault("round_score", float(eval_result.get("resource_diff", 0.0)))
        eval_result.setdefault("raw_resource_advantage_score", float(eval_result.get("resource_diff", 0.0)))
        fitness_sample_count = cached_sample_count + 1 if cached_fitness is not None else 1
        individual.last_round_evaluation = {
            "generation": generation,
            "base_prompt": base_prompt,
            "samples": round_samples,
            "dynamic_prompt": round_samples[-1]["dynamic_prompt"] if round_samples else "",
            "full_prompt": round_samples[-1]["full_prompt"] if round_samples else base_prompt,
            "raw_response": round_samples[-1]["raw_response"] if round_samples else "",
            "parsed_response": round_samples[-1]["parsed_response"] if round_samples else None,
            "legality": round_samples[-1]["legality"] if round_samples else {},
            "raw_legality_score": legality_raw_sum / n,
            "raw_strategy_alignment_score": alignment_raw_sum / n,
            "latest_eval_result": latest_eval_result,
            "eval_result": eval_result,
            "cached_fitness": cached_fitness,
            "cached_sample_count": cached_sample_count,
            "fitness_sample_count": fitness_sample_count,
            "round_eval_parallel_workers": workers,
        }

        self._write_round_profile(
            individual=individual,
            generation=generation,
            profile_output_path=profile_output_path,
            base_prompt=base_prompt,
            eval_result=eval_result,
            samples=round_samples,
            history_decision="fresh_average" if cached_fitness is not None else "fresh",
            stats=stats,
        )

        self.history.save(
            prompt=base_prompt,
            fitness=eval_result,
            metadata={
                "evaluation_mode": individual.evaluation_mode,
                "fitness_sample_count": fitness_sample_count,
                "latest_eval_result": latest_eval_result,
                "eval_result": eval_result,
                "cached_fitness": cached_fitness,
                "round": individual.last_round_evaluation,
            }
        )
        print(
            "[DEBUG] round evaluate complete "
            f"individual={individual.id} mode={eval_result.get('evaluation_mode')}",
            flush=True,
        )
        return eval_result

    def _evaluate_round_samples_parallel(
        self,
        *,
        base_prompt: str,
        dynamic_prompts: list[str],
        generation: int | None,
        individual_id: str,
        workers: int,
    ) -> list[dict[str, Any]]:
        """Evaluate generated round samples with bounded thread parallelism."""
        if workers <= 1:
            return [
                self._evaluate_round_sample(
                    base_prompt=base_prompt,
                    dynamic_prompt=dynamic_prompt,
                    sample_index=index,
                    sample_count=len(dynamic_prompts),
                    generation=generation,
                    individual_id=individual_id,
                )
                for index, dynamic_prompt in enumerate(dynamic_prompts, start=1)
            ]

        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    self._evaluate_round_sample,
                    base_prompt=base_prompt,
                    dynamic_prompt=dynamic_prompt,
                    sample_index=index,
                    sample_count=len(dynamic_prompts),
                    generation=generation,
                    individual_id=individual_id,
                )
                for index, dynamic_prompt in enumerate(dynamic_prompts, start=1)
            ]
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda item: int(item["sample_record"]["sample"]))

    def _evaluate_round_sample(
        self,
        *,
        base_prompt: str,
        dynamic_prompt: str,
        sample_index: int,
        sample_count: int,
        generation: int | None,
        individual_id: str,
    ) -> dict[str, Any]:
        """Evaluate one generated state sample and return aggregate-ready fields."""
        stats: dict[str, float] = {}
        print(
            "[DEBUG] round sample start "
            f"individual={individual_id} generation={generation} sample={sample_index}/{sample_count}",
            flush=True,
        )
        with timer("round_state_parse_time", stats):
            state = parse_dynamic_prompt_state(dynamic_prompt)
        full_prompt = self._build_round_prompt(base_prompt, dynamic_prompt)
        with timer("round_llm_action_time", stats):
            raw_response = self._ask_for_actions(full_prompt)
        with timer("round_response_parse_time", stats):
            parsed_response = self._extract_first_json_object(raw_response)
            format_valid, format_reason = self._validate_action_response_format(parsed_response)

        if format_valid:
            with timer("round_legality_score_time", stats):
                legality_raw, legality_details = self._score_legality(parsed_response, dynamic_prompt)
            with timer("round_llm_alignment_time", stats):
                alignment_raw = self._score_strategy_alignment(
                    base_prompt=base_prompt,
                    dynamic_prompt=dynamic_prompt,
                    raw_response=raw_response,
                )
        else:
            legality_raw = -100.0
            alignment_raw = -100.0
            legality_details = {
                "parseable": isinstance(parsed_response, dict),
                "format_valid": False,
                "format_error": format_reason,
                "max_actions": self._extract_max_actions(dynamic_prompt),
                "applicable_actions": 0,
                "action_type_score_sum": 0.0,
                "returned_actions": 0,
                "moves": [],
            }

        legality_max = self._theoretical_legality_max(dynamic_prompt, legality_details)
        alignment_max = self._theoretical_alignment_max()
        missing_moves = self._has_missing_or_empty_moves(parsed_response)
        if missing_moves:
            legality_score = self.MISSING_MOVES_FITNESS_SCORE
            alignment_score = self.MISSING_MOVES_FITNESS_SCORE
        else:
            legality_score = self._normalize_to_signed_unit_interval(legality_raw, legality_max)
            alignment_score = self._normalize_to_signed_unit_interval(alignment_raw, alignment_max)

        sample_record = {
            "sample": sample_index,
            "dynamic_prompt": dynamic_prompt,
            "full_prompt": full_prompt,
            "raw_response": raw_response,
            "parsed_response": parsed_response,
            "format_valid": format_valid,
            "format_reason": format_reason,
            "legality": legality_details,
            "legality_score": legality_score,
            "strategy_alignment_score": alignment_score,
            "raw_legality_score": legality_raw,
            "raw_strategy_alignment_score": alignment_raw,
        }
        print(
            "[DEBUG] round sample result "
            f"individual={individual_id} sample={sample_index}/{sample_count} "
            f"format_valid={format_valid} legality={legality_score:.4f} "
            f"alignment={alignment_score:.4f}",
            flush=True,
        )
        return {
            "sample_record": sample_record,
            "legality_max": legality_max,
            "resource_diff": self._round_resource_diff(state),
            "stats": stats,
        }

    def _round_eval_parallel_workers(self, sample_count: int) -> int:
        """Return the bounded worker count for round sample evaluation."""
        try:
            configured = int(getattr(self.config, "round_eval_parallel_workers", 1))
        except (TypeError, ValueError):
            configured = 1
        return max(1, min(int(sample_count), configured))

    @staticmethod
    def _merge_stats(target: dict[str, float], source: dict[str, float]) -> None:
        """Add numeric timing stats from one sample into the run-level stats."""
        for key, value in source.items():
            try:
                target[key] = target.get(key, 0.0) + float(value)
            except (TypeError, ValueError):
                continue

    def _write_round_profile(
        self,
        *,
        individual: Individual,
        generation: int | None,
        profile_output_path: str | Path | None,
        base_prompt: str,
        eval_result: dict[str, Any],
        samples: list[dict[str, Any]],
        history_decision: str,
        stats: dict[str, float] | None = None,
    ) -> None:
        """Append one prompt/output profile row for the GUI prompt inspector."""
        if profile_output_path is None:
            return
        record = build_base_record(
            generation=generation,
            individual_id=getattr(individual, "id", None),
            record_type="evaluation",
        )
        record.update(
            {
                "evaluation_mode": eval_result.get("evaluation_mode", "round_llm"),
                "eval_mode": "round",
                "history_decision": history_decision,
                "prompt": base_prompt,
                "prompt_length": len(base_prompt),
                "fitness": getattr(individual, "fitness", None),
                "eval_result": dict(eval_result),
                "round_samples": samples,
            }
        )
        for key, value in dict(stats or {}).items():
            record[key] = value
        write_jsonl(record, profile_output_path)

    @staticmethod
    def _history_sample_count(cached_record: dict[str, Any] | None) -> int:
        if cached_record is None:
            return 0
        metadata = dict(cached_record.get("metadata") or {})
        try:
            return max(1, int(metadata.get("fitness_sample_count", 1)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _round_eval_result_from_cached(
        cached_fitness: Any,
        cached_eval_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return round objective inputs from current or older history rows."""
        if cached_eval_result:
            return dict(cached_eval_result)
        if isinstance(cached_fitness, dict):
            if cached_fitness.get("eval_mode") == "round":
                return dict(cached_fitness)
            return {
                "eval_mode": "round",
                "evaluation_mode": "history_avg",
                "valid_json": bool(cached_fitness.get("format_validity", 1.0)),
                "legal_action_count": float(cached_fitness.get("action_legality_ratio", 0.0)),
                "illegal_action_count": 0.0,
                "action_type_score_sum": float(cached_fitness.get("action_type_score_ratio", 0.0)),
                "theoretical_legality_max": 1.0,
                "resource_diff": float(cached_fitness.get("resource_advantage", 0.0)),
                "strategy_alignment_score": float(cached_fitness.get("strategy_alignment", 0.0)),
            }
        values = list(cached_fitness or [])
        return {
            "eval_mode": "round",
            "evaluation_mode": "history_avg",
            "valid_json": True,
            "legal_action_count": float(values[0]) if len(values) > 0 else 0.0,
            "illegal_action_count": 0.0,
            "action_type_score_sum": float(values[1]) if len(values) > 1 else 0.0,
            "theoretical_legality_max": 1.0,
            "resource_diff": float(values[0]) if len(values) > 0 else 0.0,
            "strategy_alignment_score": float(values[1]) if len(values) > 1 else 0.0,
        }

    @classmethod
    def _average_history_eval_result(
        cls,
        cached_fitness: Any,
        cached_eval_result: dict[str, Any] | None,
        latest_eval_result: dict[str, Any],
        cached_sample_count: int,
    ) -> dict[str, Any]:
        """Average current round metrics with cached raw objective inputs."""
        if cached_fitness is None:
            return dict(latest_eval_result)
        cached = cls._round_eval_result_from_cached(cached_fitness, cached_eval_result)
        averaged = dict(latest_eval_result)
        for key in (
            "valid_json_count",
            "legal_action_count",
            "illegal_action_count",
            "action_type_score_sum",
            "theoretical_legality_max",
            "resource_diff",
            "strategy_alignment_score",
        ):
            averaged[key] = (
                (float(cached.get(key, 0.0)) * cached_sample_count)
                + float(latest_eval_result.get(key, 0.0))
            ) / (cached_sample_count + 1)
        averaged["valid_json"] = bool(averaged.get("valid_json_count", 0.0) >= 1.0)
        averaged["evaluation_mode"] = "round_llm_history_avg"
        return averaged

    def _round_resource_diff(self, state: dict[str, Any]) -> float:
        """Return weighted ally-minus-enemy resources/material for one round state."""
        weights = dict(getattr(self.config, "resource_advantage_weights", {}) or {})
        return (
            self._weighted_unit_total(dict(state.get("ally_units") or {}), weights)
            - self._weighted_unit_total(dict(state.get("enemy_units") or {}), weights)
        )

    @staticmethod
    def _weighted_unit_total(units: dict[Any, dict[str, Any]], weights: dict[str, float]) -> float:
        """Collapse parsed round units into the same weighted material scale."""
        total = 0.0
        for unit_info in units.values():
            unit_type = str(unit_info.get("type", "")).strip().lower()
            total += float(weights.get(unit_type, 0.0))
            if unit_type == "base":
                total += float(weights.get("resource", 1.0)) * float(unit_info.get("resources", 0.0))
        return total

    def _construct_prompt(self, individual: Individual) -> str:
        prompt_lines = self.component_pool.render_prompt_lines(
            individual.component_indices,
            include_identity_component=getattr(self.config, "include_strategy_identity_in_prompt", True),
        )
        return "\n".join(prompt_lines)

    def _build_round_prompt(self, base_prompt: str, dynamic_prompt: str) -> str:
        return f"""
                {base_prompt.strip()}
                {dynamic_prompt.strip()}
                """.strip()

    def _ask_for_actions(self, prompt: str) -> str:
        return self._ollama_generate(prompt=prompt, temperature=0.2, json_format=True)

    def _score_strategy_alignment(
        self,
        *,
        base_prompt: str,
        dynamic_prompt: str,
        raw_response: str,
    ) -> float:
        judge_prompt = f"""
            You are a strict evaluator for a MicroRTS LLM agent response.

            Score ONLY strategy alignment (0–10). Do NOT consider JSON validity.

            Return JSON only:
            {{"score": number, "reason": "short reason"}}

            Scoring guide:
            - 0: Completely contradicts the strategy
            - 2: Mostly irrelevant or harmful actions
            - 4: Weak alignment, many generic or idle actions
            - 6: Moderate alignment but incomplete
            - 8: Strong alignment with minor issues
            - 10: Near-optimal decision for this state and strategy

            IMPORTANT RULES:
            - If no moves → score <= 2
            - If mostly idle → score <= 4
            - If actions are generic → score <= 5
            - If ignores available units → score <= 6
            - If not using state info → score <= 5
            - If missing obvious good action → score <= 8

            You MUST identify at least one weakness unless score = 10.
            Most responses should fall between 4–7, not 10.

            Strategy prompt:
            {base_prompt}

            Current game state:
            {dynamic_prompt}

            Action response:
            {raw_response}
            """.strip()
        raw_score = self._ollama_generate(prompt=judge_prompt, temperature=0.1, json_format=True)
        # print(f"Raw score response:\n{raw_score}\n")
        parsed = self._extract_first_json_object(raw_score)
        if isinstance(parsed, dict):
            try:
                return max(0.0, min(100.0, float(parsed.get("score", 0.0))))
            except (TypeError, ValueError):
                return 0.0

        matches = re.findall(r"-?\d+(?:\.\d+)?", raw_score)
        if not matches:
            return 0.0
        return max(0.0, min(100.0, float(matches[0])))

    def _score_legality(
        self,
        parsed_response: dict[str, Any] | None,
        dynamic_prompt: str,
    ) -> tuple[float, dict[str, Any]]:
        if not isinstance(parsed_response, dict):
            return 0.0, {
                "parseable": False,
                "max_actions": self._extract_max_actions(dynamic_prompt),
                "applicable_actions": 0,
                "action_type_score_sum": 0.0,
                "moves": [],
            }

        moves = parsed_response.get("moves")
        if not isinstance(moves, list):
            moves = []

        state = parse_dynamic_prompt_state(dynamic_prompt)
        max_actions = max(1, self._extract_max_actions(dynamic_prompt))
        seen_positions: set[tuple[int, int]] = set()
        valid_actions = 0
        action_type_score_sum = 0.0
        move_results: list[dict[str, Any]] = []

        for move in moves:
            duplicate = False
            unit_position = move.get("unit_position") if isinstance(move, dict) else None
            if (
                isinstance(unit_position, list)
                and len(unit_position) == 2
                and all(isinstance(value, int) for value in unit_position)
            ):
                pos = (unit_position[0], unit_position[1])
                duplicate = pos in seen_positions
                seen_positions.add(pos)

            ok, reason = validate_llm_move_against_state(move, state)
            applied = bool(ok and not duplicate)
            action_type = str(move.get("action_type", "")).strip().lower() if isinstance(move, dict) else ""
            action_type_score = self._score_successful_action_type(action_type, move, state) if applied else 0.0
            if applied:
                valid_actions += 1
                action_type_score_sum += action_type_score
            move_results.append(
                {
                    "move": move,
                    "applicable": applied,
                    "action_type": action_type,
                    "action_type_score": action_type_score,
                    "duplicate": duplicate,
                    "reason": "duplicate_unit" if duplicate else reason,
                }
            )
        # print(f"Dynamic prompt:\n{dynamic_prompt}\n")
        # print(f"Move results:\n{json.dumps(move_results, indent=2)}\n")

        return action_type_score_sum, {
            "parseable": True,
            "format_valid": True,
            "max_actions": max_actions,
            "applicable_actions": valid_actions,
            "action_type_score_sum": action_type_score_sum,
            "returned_actions": len(moves),
            "moves": move_results,
        }

    def _theoretical_legality_max(
        self,
        dynamic_prompt: str,
        legality_details: dict[str, Any] | None = None,
    ) -> float:
        """Return the best possible action-type score sum for the generated state.

        Legality normalization uses:

            normalized_legality = action_type_score_sum / theoretical_legality_max

        The numerator is the sum of the shaped scores for returned valid moves.
        The denominator is computed from the state itself: estimate each
        controllable ally unit's best legal immediate action score, sort those
        unit caps descending, and sum only the best `Max actions` units. This
        keeps the scale tied to what the current state could theoretically do,
        instead of dividing by returned action count or applying invalid/idle
        penalties.
        """
        state = parse_dynamic_prompt_state(dynamic_prompt)
        max_actions = max(1, self._extract_max_actions(dynamic_prompt))
        ally_units = list(dict(state.get("ally_units") or {}).values())
        if not ally_units:
            return 1.0

        # One unit can produce at most one move, so the total theoretical cap is
        # the sum of the best-scoring units up to the state's Max actions value.
        per_unit_caps = [
            self._best_theoretical_action_score_for_unit(state, unit_info)
            for unit_info in ally_units
        ]
        per_unit_caps.sort(reverse=True)
        top_k = per_unit_caps[:max_actions]
        total = sum(top_k)
        return max(1.0, float(total))

    def _theoretical_alignment_max(self) -> float:
        return float(self.THEORETICAL_ALIGNMENT_MAX)

    @staticmethod
    def _normalize_to_signed_unit_interval(raw_score: float, theoretical_max: float) -> float:
        safe_max = max(1e-9, float(theoretical_max))
        normalized = float(raw_score) / safe_max
        return max(-1.0, min(1.0, normalized))

    @staticmethod
    def _has_missing_or_empty_moves(parsed_response: dict[str, Any] | None) -> bool:
        """Return whether the response omitted actions entirely."""
        if not isinstance(parsed_response, dict):
            return True
        moves = parsed_response.get("moves")
        return not isinstance(moves, list) or len(moves) == 0

    def _best_theoretical_action_score_for_unit(
        self,
        state: dict[str, Any],
        unit_info: dict[str, Any],
    ) -> float:
        """Estimate one unit's best possible immediate action score for this state.

        This mirrors `_score_successful_action_type()` at the action-family level:
        workers consider move, harvest, build, and attack; buildings consider
        train; combat units consider move and attack. Resource/map legality is
        approximated from the parsed state so the denominator represents the
        best available weighted action score for that unit.
        """
        unit_type = self._normalize_unit_type(str(unit_info.get("type", "")))

        candidates = [0.0, 0.5]  # idle, move

        if unit_type == "worker":
            candidates.append(2.0)  # harvest
            ally_barracks_count = self._count_ally_units_by_type(state, "barracks")
            candidates.append(max(0.0, 50.0 - 10.0 * ally_barracks_count))  # build barracks
            candidates.append(max(0.0, 10.0 - 2.0 * self._count_ally_units_by_type(state, "base")))  # build base

        if unit_type in {"base", "barracks"}:
            # Best-case train score in current shaping function.
            candidates.append(3.0)

        if unit_type in {"worker", "light", "heavy", "ranged"}:
            candidates.append(self._best_theoretical_attack_score(state, unit_info))

        return max(candidates) if candidates else 0.0

    def _best_theoretical_attack_score(
        self,
        state: dict[str, Any],
        attacker_info: dict[str, Any],
    ) -> float:
        """Estimate the best attack score available to a unit in this state.

        Attack caps use the same distance and target-priority shaping as
        `_score_attack()`: closer targets score higher, buildings and killable
        combat units can receive multipliers, and the unit's best target becomes
        its theoretical attack cap.
        """
        attacker_position = self._unit_info_position_tuple(attacker_info)
        if attacker_position is None:
            return float(self.DEFAULT_ACTION_TYPE_SCORES.get("attack", 0.0))

        enemy_units = dict(state.get("enemy_units") or {})
        if not enemy_units:
            return float(self.DEFAULT_ACTION_TYPE_SCORES.get("attack", 0.0))

        attacker_type = self._normalize_unit_type(str(attacker_info.get("type", "")))
        attacker_damage = self._unit_type_damage(attacker_type)
        best_score = float(self.DEFAULT_ACTION_TYPE_SCORES.get("attack", 0.0))

        for position, enemy_info in enemy_units.items():
            if not isinstance(position, tuple) or len(position) != 2:
                continue
            if not isinstance(enemy_info, dict):
                continue

            target_x, target_y = position
            distance = abs(attacker_position[0] - int(target_x)) + abs(attacker_position[1] - int(target_y))
            base_score = max(0.5, 20.0 / (distance + 1))

            target_type = self._normalize_unit_type(str(enemy_info.get("type", "")))
            target_hp = self._unit_hp(enemy_info)
            can_kill = attacker_damage >= target_hp

            multiplier = 1.0
            if target_type in {"base", "barracks"}:
                multiplier = 1.5
            elif target_type in {"light", "heavy", "ranged"} and can_kill:
                multiplier = 2.0
            elif target_type == "worker" and can_kill:
                multiplier = 1.0

            best_score = max(best_score, base_score * multiplier)

        return best_score

    @staticmethod
    def _validate_action_response_format(parsed_response: dict[str, Any] | None) -> tuple[bool, str | None]:
        """Validate the required action-response JSON schema before scoring fitness."""
        if not isinstance(parsed_response, dict):
            return False, "response is not a JSON object"
        if not isinstance(parsed_response.get("thinking"), str):
            return False, "missing string field: thinking"

        moves = parsed_response.get("moves")
        if not isinstance(moves, list):
            return False, "missing list field: moves"

        required_string_fields = ("raw_move", "unit_type", "action_type")
        for index, move in enumerate(moves):
            if not isinstance(move, dict):
                return False, f"moves[{index}] is not an object"
            for field in required_string_fields:
                if not isinstance(move.get(field), str):
                    return False, f"moves[{index}] missing string field: {field}"
            unit_position = move.get("unit_position")
            if (
                not isinstance(unit_position, list)
                or len(unit_position) != 2
                or not all(isinstance(value, int) for value in unit_position)
            ):
                return False, f"moves[{index}] missing [int, int] field: unit_position"

        return True, None

    def _score_successful_action_type(
        self,
        action_type: str,
        move: dict[str, Any],
        state: dict[str, Any],
    ) -> float:
        """Score one already-valid action by action type."""
        if action_type == "harvest":
            return 2.0
        if action_type == "attack":
            return self._score_attack(move, state)
        if action_type == "move":
            return 0.5
        if action_type == "idle":
            return 0.0
        if action_type == "build":
            building_type = self._extract_building_type(move)
            if building_type == "barracks":
                ally_barracks_count = self._count_ally_units_by_type(state, "barracks")
                return max(0.0, 50.0 - 10.0 * ally_barracks_count)
            same_building_count = self._count_ally_units_by_type(state, building_type)
            return 10.0 - 2.0 * same_building_count
        if action_type == "train":
            unit_type = self._extract_train_unit_type(move)
            if not unit_type:
                return 3.0
            same_unit_count = self._count_ally_units_by_type(state, unit_type)
            if same_unit_count >= 13:
                return -1.0
            if same_unit_count >= 10:
                return 0.0
            if same_unit_count >= 7:
                return 1.0
            if same_unit_count >= 5:
                return 2.0
            return 3.0
        return float(self.DEFAULT_ACTION_TYPE_SCORES.get(action_type, 0.0))

    def _score_attack(self, move: dict[str, Any], state: dict[str, Any]) -> float:
        """Score one valid attack by range pressure and target priority."""
        attacker_position = self._move_unit_position_tuple(move)
        attack_target = self._extract_attack_target(move)
        if attacker_position is None or attack_target is None:
            return float(self.DEFAULT_ACTION_TYPE_SCORES.get("attack", 0.0))

        target_info = self._enemy_info_at_position(state, attack_target)
        if not target_info:
            return float(self.DEFAULT_ACTION_TYPE_SCORES.get("attack", 0.0))

        distance = abs(attacker_position[0] - attack_target[0]) + abs(attacker_position[1] - attack_target[1])
        base_score = max(0.5, 20.0 / (distance + 1))

        target_type = self._normalize_unit_type(str(target_info.get("type", "")))
        attacker_type = self._normalize_unit_type(str(move.get("unit_type", "")))
        attacker_damage = self._unit_type_damage(attacker_type)
        target_hp = self._unit_hp(target_info)
        can_kill = attacker_damage >= target_hp

        multiplier = 1.0
        if target_type in {"base", "barracks"}:
            multiplier = 1.5
        elif target_type in {"light", "heavy", "ranged"} and can_kill:
            multiplier = 2.0
        elif target_type == "worker" and can_kill:
            multiplier = 1.0

        return base_score * multiplier

    @staticmethod
    def _extract_building_type(move: dict[str, Any]) -> str | None:
        raw_move = str(move.get("raw_move", "")).lower()
        match = re.search(r"\bbuild\s*\(.*,\s*([a-z_]+)\s*\)", raw_move)
        if not match:
            return None
        return Evaluator._normalize_unit_type(match.group(1))

    @staticmethod
    def _extract_attack_target(move: dict[str, Any]) -> tuple[int, int] | None:
        """Parse the target coordinate from attack((x, y)) in raw_move."""
        raw_move = str(move.get("raw_move", ""))
        match = re.search(r"\battack\s*\(\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)\s*\)", raw_move)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _move_unit_position_tuple(move: dict[str, Any]) -> tuple[int, int] | None:
        """Return unit_position as a coordinate tuple when it is well formed."""
        unit_position = move.get("unit_position")
        if (
            isinstance(unit_position, list)
            and len(unit_position) == 2
            and all(isinstance(value, int) for value in unit_position)
        ):
            return unit_position[0], unit_position[1]
        return None

    @staticmethod
    def _enemy_info_at_position(state: dict[str, Any], position: tuple[int, int]) -> dict[str, Any] | None:
        """Find enemy unit or building info at the target coordinate."""
        enemy_units = state.get("enemy_units", {})
        if not isinstance(enemy_units, dict):
            return None
        target_info = enemy_units.get(position)
        return target_info if isinstance(target_info, dict) else None

    @staticmethod
    def _unit_info_position_tuple(unit_info: dict[str, Any]) -> tuple[int, int] | None:
        """Extract (x, y) from parsed unit info."""
        for key in ("position", "pos", "unit_position"):
            value = unit_info.get(key)
            if (
                isinstance(value, (list, tuple))
                and len(value) == 2
                and all(isinstance(v, int) for v in value)
            ):
                return int(value[0]), int(value[1])
        x = unit_info.get("x")
        y = unit_info.get("y")
        if isinstance(x, int) and isinstance(y, int):
            return int(x), int(y)
        return None

    @staticmethod
    def _unit_type_damage(unit_type: str) -> float:
        """Return the single-hit damage for one MicroRTS unit type."""
        damage_by_type = {
            "worker": 1.0,
            "light": 2.0,
            "heavy": 4.0,
            "ranged": 1.0,
        }
        return damage_by_type.get(Evaluator._normalize_unit_type(unit_type), 0.0)

    @staticmethod
    def _unit_hp(unit_info: dict[str, Any]) -> float:
        """Read HP from parsed unit info, falling back to known MicroRTS defaults."""
        raw_hp = unit_info.get("hp", unit_info.get("HP"))
        if raw_hp is None:
            hp_match = re.search(r"\bHP\s*=\s*(-?\d+(?:\.\d+)?)", str(unit_info.get("stats", "")))
            raw_hp = hp_match.group(1) if hp_match else None
        try:
            return float(raw_hp)
        except (TypeError, ValueError):
            unit_type = Evaluator._normalize_unit_type(str(unit_info.get("type", "")))
            return {
                "worker": 1.0,
                "light": 4.0,
                "heavy": 8.0,
                "ranged": 3.0,
                "base": 10.0,
                "barracks": 5.0,
            }.get(unit_type, 1.0)

    @staticmethod
    def _extract_train_unit_type(move: dict[str, Any]) -> str | None:
        raw_move = str(move.get("raw_move", "")).lower()
        match = re.search(r"\btrain\s*\(\s*([a-z_]+)\s*\)", raw_move)
        if not match:
            return None
        return Evaluator._normalize_unit_type(match.group(1))

    @staticmethod
    def _count_ally_units_by_type(state: dict[str, Any], unit_type: str) -> int:
        normalized_type = Evaluator._normalize_unit_type(unit_type)
        return sum(
            1
            for unit_info in dict(state.get("ally_units") or {}).values()
            if Evaluator._normalize_unit_type(str(unit_info.get("type", ""))) == normalized_type
        )

    @staticmethod
    def _normalize_unit_type(unit_type: str) -> str:
        normalized = str(unit_type or "").strip().lower().replace("ally_", "").replace("ally ", "")
        aliases = {
            "worker unit": "worker",
            "light unit": "light",
            "heavy unit": "heavy",
            "ranged unit": "ranged",
            "base unit": "base",
            "barracks unit": "barracks",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _extract_max_actions(dynamic_prompt: str) -> int:
        match = re.search(r"Max actions:\s*(\d+)", dynamic_prompt)
        if not match:
            return 1
        return max(1, int(match.group(1)))

    @staticmethod
    def _extract_first_json_object(raw_output: str) -> dict[str, Any] | None:
        if not raw_output:
            return None
        try:
            parsed = json.loads(raw_output)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    def _ollama_generate(self, *, prompt: str, temperature: float, json_format: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_format:
            payload["format"] = "json"

        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()
        except Exception:
            return ""
