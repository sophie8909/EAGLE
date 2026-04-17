"""
This module defines the evaluation framework for the evolutionary algorithm. It includes the Evaluator class, which evaluates the fitness of candidate prompts by simulating games in MicroRTS and measuring performance against a baseline strategy. The Evaluator uses the ComponentPool to construct prompts based on selected components and runs multiple simulations to obtain an average fitness score. This evaluation process guides the evolution of prompts towards more effective strategies in MicroRTS.z
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from ..envs.microrts.adapter import (
    detect_timeout,
    get_latest_log_file,
    save_prompt,
    set_llm_interval,
    set_opponent,
)
from ..envs.microrts.runner import run_prompt_based_game
from ..utils.component_pool import ComponentPool
from ..config import EAConfig
from ..utils.individual import Individual
from ..utils.move_validator import (
    combine_prompt_with_dynamic,
    is_in_bounds,
    score_game_round_response,
    validate_llm_move_against_state,
)
from ..utils.fitness_calculator import (
    calculate_fitness_score,
    game_round_execution_score,
    material_total,
    parse_winner_info,
    resource_advantage_evaluation,
    turn_count_score,
    win_loss_evaluation,
)
from ..surrogate.eval.evaluator import (
    surrogate_evaluation_game_round,
    surrogate_evaluation_policy,
)
from ..evolution.operators.reflection import Reflection, read_max_turn_hint
from ..utils.simulation_runner import simulate_policy_surrogate_games, simulate_surrogate_games
from ..utils.profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl
from ..utils.fitness_recorder import FitnessRecorder
from ..utils.fitness_utils import normalize_fitness
from ..project import PROJECT_ROOT



class Evaluator:
    def __init__(self, component_pool: ComponentPool, config: EAConfig | None = None):
        """Store shared dependencies used by both real and surrogate evaluation."""
        self.component_pool = component_pool
        self.config = config or EAConfig()
        self.repo_root = PROJECT_ROOT

    def _parse_winner_info(self, log_content: str) -> dict[str, Any]:
        """Delegate winner extraction to the shared fitness calculator helper."""
        return parse_winner_info(log_content)

    def _build_surrogate_examples(
        self,
        fitness_recorder: FitnessRecorder | None = None,
    ) -> list[list[str]]:
        """The prompt-only LLM surrogate path is disabled."""
        return []

    def _adjust_surrogate_scores(self, surrogate_scores: list[float]) -> list[float]:
        """The prompt-only LLM surrogate path is disabled."""
        return surrogate_scores

    def _combine_prompt_with_dynamic(self, prompt: str, dynamic_prompt_text: str) -> str:
        """Merge a strategy prompt with one sampled Dynamic Prompt block."""
        return combine_prompt_with_dynamic(prompt, dynamic_prompt_text)

    def _is_in_bounds(self, x: int, y: int, state: dict[str, Any]) -> bool:
        """Check whether a coordinate falls within the sampled map bounds."""
        return is_in_bounds(x, y, state)

    def _validate_llm_move_against_state(
        self,
        move: dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[bool, str]:
        """Validate one LLM move against the lightweight parsed game state."""
        return validate_llm_move_against_state(move, state)

    def _score_game_round_response(
        self,
        llm_response: dict[str, Any] | None,
        dynamic_prompt_text: str,
    ) -> float:
        """Score one raw LLM round response using legality and execution heuristics."""
        return score_game_round_response(llm_response, dynamic_prompt_text)

    def evaluate(
        self,
        individual: Individual,
        use_real_evaluation: bool,
        opponent: str | None,
        allow_history_reuse_for_real: bool = False,
        profile_output_path: str | Path | None = None,
        generation: int | None = None,
        fitness_recorder: FitnessRecorder | None = None,
    ):
        """Evaluate one individual with either a full game or the configured surrogate."""
        stats: dict[str, float] = {}
        prompt = ""
        parsed_log: dict[str, Any] | None = None
        winner: str | None = None
        timeout = False
        log_path: str | None = None
        llm_calls = 0
        surrogate_score: float | None = None
        similar_records: list[dict[str, Any]] = []
        history_reuse_mode: str | None = None

        with timer("prompt_render_time", stats):
            prompt = self.construct_prompt(individual)

        with timer("bookkeeping_time", stats):
            self.save_prompt(prompt)

        should_check_history = fitness_recorder is not None and (
            not use_real_evaluation or allow_history_reuse_for_real
        )
        if should_check_history:
            similar_records = fitness_recorder.find_matching_history(prompt, opponent)
            if similar_records:
                print(f"Found {len(similar_records)} similar records in history for the current prompt.")
                for rec in similar_records:
                    print(f"Similar record fitness score: {rec.get('fitness_score')}")
                use_real_evaluation = False  # Skip evaluation if we found equivalent prior evidence.
                history_reuse_mode = "real_history_reuse_initial" if allow_history_reuse_for_real else "history_reuse"
                fitness = similar_records[random.randint(0, len(similar_records) - 1)].get("fitness_score", [0.0, 0.0])  # Use the fitness score from a random similar record as a reference.
            else:
                print("No similar records found in history for the current prompt.")
        if use_real_evaluation:
            fitness, simulation_meta = self.simulate_games(opponent, stats)
            parsed_log = simulation_meta.get("parsed_log")
            winner = simulation_meta.get("winner")
            timeout = simulation_meta.get("timeout", False)
            log_path = simulation_meta.get("log_path")
            llm_calls = simulation_meta.get("llm_calls", 0)
        elif history_reuse_mode is not None:
            llm_calls = 0
        else:
            with timer("EA_operator_time", stats):
                with timer("surrogate_time", stats):
                    surrogate_score = self.surrogate_evaluation(
                        prompt,
                        opponent=opponent,
                        fitness_recorder=fitness_recorder,
                    )
                    fitness = surrogate_score if surrogate_score else [0.0, 0.0]
            
            llm_calls = 1

        fitness = normalize_fitness(fitness)
        print(fitness)

        if fitness_recorder is not None:
            evaluation_mode = "real" if use_real_evaluation else (history_reuse_mode or "surrogate")
            fitness_recorder.record_fitness(
                {
                    "individual_id": getattr(individual, "id", None),
                    "generation": generation,
                    "prompt": prompt,          # add for surrogate examples
                    "fitness": fitness,        # compatibility key
                    "fitness_score": fitness,  # current key
                    "opponent": opponent,
                    "evaluation_mode": evaluation_mode,
                    "evaluation_time": stats.get("total_eval_time", 0.0),
                    "components": {
                        "game_rule": individual.game_rule,
                        "strategy": individual.strategy,
                    }
                }
            )
        else:
            evaluation_mode = "real" if use_real_evaluation else (history_reuse_mode or "surrogate")
        individual.fitness = fitness
        individual.evaluation_mode = evaluation_mode
        if use_real_evaluation:
            summary = parsed_log.get("summary", {}) if isinstance(parsed_log, dict) else {}
            reflection_context = Reflection.build_compact_reflection_context(
                parsed_log=parsed_log,
                fitness=fitness,
                timeout=timeout,
                max_turn_hint=read_max_turn_hint(self.repo_root),
            )
            individual.last_real_evaluation = {
                "winner": winner,
                "timeout": timeout,
                "log_path": log_path,
                "parsed_summary": summary,
                "reflection_context": reflection_context,
            }
        summarize_total_eval_time(stats)

        operator_profile = getattr(individual, "operator_profile", None)
        if isinstance(operator_profile, dict):
            for key in ("crossover_time", "mutation_time", "EA_operator_time"):
                stats[key] = stats.get(key, 0.0) + operator_profile.get(key, 0.0)
            summarize_total_eval_time(stats)

        #  only record real evaluation results to avoid contamination from surrogate evaluation.
        if profile_output_path is not None and use_real_evaluation:
            record = build_base_record(
                generation=generation,
                individual_id=getattr(individual, "id", None),
                record_type="evaluation",
            )
            record.update(
                {
                    "evaluation_mode": "real" if use_real_evaluation else "surrogate",
                    "opponent": opponent,
                    "prompt_length": len(prompt),
                    "winner": winner,
                    "timeout": timeout,
                    "llm_calls": llm_calls,
                    "avg_llm_call_time": None,
                    "max_llm_call_time": None,
                    "game_llm_call_time": None,
                    "ea_llm_call_time": stats.get("surrogate_time", 0.0) + (operator_profile.get("ea_llm_call_time", 0.0) if isinstance(operator_profile, dict) else 0.0),
                    "fitness": fitness,
                    "surrogate_score": surrogate_score if not use_real_evaluation else None,
                    "log_path": log_path,
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

            if parsed_log is not None:
                summary = parsed_log.get("summary", {})
                record["parsed_summary"] = summary
                record["llm_calls"] = summary.get("segment_count", llm_calls)

            write_jsonl(record, profile_output_path)

    def save_prompt(self, prompt: str):
        """Write the active prompt to the prompt file consumed by MicroRTS."""
        save_prompt(self.repo_root, prompt)

    def construct_prompt(self, individual: Individual) -> str:
        """Render one individual's selected components into the final strategy prompt."""
        static_prompt_lines = []
        if self.component_pool.has_category("game_rule"):
            static_prompt_lines = self.component_pool.render_static_prompt_lines(
                individual.game_rule
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

    def game_round_execution_score(self, log_content: str) -> float:
        """Compute the round-execution score directly from a full game log."""
        return game_round_execution_score(log_content)

    def win_loss_evaluation(self, log_content: str, parsed_log: dict[str, Any] | None = None) -> float:
        """Return the normalized win/loss objective for one parsed game."""
        return win_loss_evaluation(log_content, parsed_log=parsed_log)

    def turn_count_score(self, log_content: str) -> int:
        """Return the normalized turn-count objective extracted from a game log."""
        return turn_count_score(log_content)

    def _material_total(self, snapshot: dict[str, Any]) -> float:
        """Collapse one force snapshot into a weighted material total."""
        return material_total(snapshot, self.config.resource_advantage_weights)

    def resource_advantage_evaluation(
        self,
        parsed_log: dict[str, Any],
        eps: float = 1e-9,
    ) -> float:
        """Compute the late-game-weighted material/resource advantage score."""
        return resource_advantage_evaluation(
            parsed_log,
            resource_advantage_alpha=self.config.resource_advantage_alpha,
            resource_advantage_weights=self.config.resource_advantage_weights,
            eps=eps,
        )

    def calculate_fitness_score(self, log_content: str, parsed_log: dict[str, Any] | None = None) -> list[float]:
        """Compute the three-objective real-game fitness vector from one log."""
        fitness = calculate_fitness_score(
            log_content,
            resource_advantage_alpha=self.config.resource_advantage_alpha,
            resource_advantage_weights=self.config.resource_advantage_weights,
            parsed_log=parsed_log,
        )
        print(
            "Parsed fitness: "
            f"winning_score={fitness[0]}, "
            f"game_round_fitness={fitness[1]}, "
            f"resource_advantage_score={fitness[2]}"
        )
        return fitness

    def set_opponent(self, opponent: str):
        """Update the MicroRTS config so the next run uses the requested opponent."""
        set_opponent(self.repo_root, opponent)

    def set_llm_interval(self, llm_interval: int) -> None:
        """Update the MicroRTS config so the next run uses the requested LLM interval."""
        set_llm_interval(self.repo_root, llm_interval)

    def launch_simulation(self, test: bool=False):
        """Launch the game loop script used for either training or final testing."""
        raise RuntimeError(
            "launch_simulation is deprecated in the EAGLE-root layout. Use run_prompt_based_game instead."
        )


    def wait_for_simulation(self, process):
        """Block until the launched MicroRTS process finishes and collect outputs."""
        raise RuntimeError(
            "wait_for_simulation is deprecated in the EAGLE-root layout. Use run_prompt_based_game instead."
        )


    def get_latest_log_file(self) -> Path | None:
        """Return the newest generated `run_*.log` file, if any."""
        return get_latest_log_file(self.repo_root)

    def extract_winner_from_log(self, log_content: str) -> str | None:
        """Read only the winner field from a complete MicroRTS log."""
        return self._parse_winner_info(log_content)["winner"]

    def detect_timeout(self, log_content: str) -> bool:
        """Detect whether the game appears to have terminated by timeout."""
        return detect_timeout(log_content)

    def simulate_games(self, opponent: str | None, stats: dict[str, float]) -> tuple[list[float], dict[str, Any]]:
        """Run one real simulation and return its fitness plus parsed metadata."""
        return run_prompt_based_game(
            project_root=self.repo_root,
            config=self.config,
            prompt=(self.repo_root / "third_party" / "microrts" / "prompt.txt").read_text(encoding="utf-8")
            if (self.repo_root / "third_party" / "microrts" / "prompt.txt").exists()
            else "",
            opponent=opponent,
        )

    def surrogate_evaluation(
        self,
        prompt: str,
        opponent: str | None = None,
        fitness_recorder: FitnessRecorder | None = None,
    ) -> list[float]:
        """Dispatch to the configured surrogate implementation."""
        if self.config.normalized_surrogate_version == "game_round":
            return self.surrogate_evaluation_game_round(
                prompt,
                opponent=opponent,
            )
        return self.surrogate_evaluation_policy(
            prompt,
            opponent=opponent,
        )

    # The original prompt-only LLM surrogate function is intentionally kept as
    # commented reference after removal from runtime dispatch.
    #
    # def surrogate_evaluation_llm(self, prompt: str, fitness_recorder: FitnessRecorder | None = None) -> list[float]:
    #     """Evaluate a prompt with the prompt-only LLM surrogate."""
    #     return surrogate_evaluation_llm(prompt, fitness_recorder=fitness_recorder)

    def surrogate_evaluation_game_round(
        self,
        prompt: str,
        opponent: str | None = None,
    ) -> list[float]:
        """Evaluate a prompt by generating and running the surrogate Java agent."""
        return surrogate_evaluation_game_round(
            prompt,
            repo_root=self.repo_root,
            config=self.config,
            opponent=opponent,
            simulate_surrogate_games_fn=simulate_surrogate_games,
        )

    def surrogate_evaluation_policy(
        self,
        prompt: str,
        opponent: str | None = None,
    ) -> list[float]:
        """Evaluate a prompt by compiling it into a fixed-policy surrogate agent."""
        return surrogate_evaluation_policy(
            prompt,
            repo_root=self.repo_root,
            config=self.config,
            opponent=opponent,
            simulate_policy_surrogate_games_fn=simulate_policy_surrogate_games,
        )

