"""
This module defines the evaluation framework for the evolutionary algorithm. It includes the Evaluator class, which evaluates the fitness of candidate prompts by simulating games in MicroRTS and measuring performance against a baseline strategy. The Evaluator uses the ComponentPool to construct prompts based on selected components and runs multiple simulations to obtain an average fitness score. This evaluation process guides the evolution of prompts towards more effective strategies in MicroRTS.z
"""

from __future__ import annotations

import glob
import os
import subprocess
from pathlib import Path
from typing import Any
import random

from .llm import LLM
from .component_pool import ComponentPool
from .config import EAConfig
from .individual import Individual
from .log_parse import parse_log
from .profiler import build_base_record, summarize_total_eval_time, timer, write_jsonl
from .fitness_recorder import FitnessRecorder
from .fitness_utils import normalize_fitness



class Evaluator:
    def __init__(self, component_pool: ComponentPool, config: EAConfig | None = None):
        self.component_pool = component_pool
        self.config = config or EAConfig()
        self.repo_root = Path(__file__).resolve().parents[2]

    def _parse_winner_info(self, log_content: str) -> dict[str, Any]:
        parsed_log = parse_log(log_content)
        summary = parsed_log.get("summary", {})
        return {
            "parsed_log": parsed_log,
            "winner": summary.get("winner"),
            "target_side": summary.get("target_side"),
            "termination_reason": summary.get("termination_reason"),
        }

    def evaluate(
        self,
        individual: Individual,
        real_eva: bool,
        opponent: str | None,
        profile_output_path: str | Path | None = None,
        generation: int | None = None,
        fitness_recorder: FitnessRecorder | None = None,
    ):
        stats: dict[str, float] = {}
        prompt = ""
        parsed_log: dict[str, Any] | None = None
        winner: str | None = None
        timeout = False
        log_path: str | None = None
        llm_calls = 0
        surrogate_score: float | None = None

        with timer("prompt_render_time", stats):
            prompt = self.construct_prompt(individual)

        with timer("bookkeeping_time", stats):
            self.save_prompt(prompt)

        if fitness_recorder is not None:
            similar_records = fitness_recorder.find_history(prompt, opponent)
            if similar_records:
                print(f"Found {len(similar_records)} similar records in history for the current prompt.")
                for rec in similar_records:
                    print(f"Similar record fitness score: {rec.get('fitness_score')}")
                real_eva = False  # Skip real evaluation if we found similar prompts in history to save time.
                fitness = similar_records[random.randint(0, len(similar_records) - 1)].get("fitness_score", [0.0, 0.0, 0.0])  # Use the fitness score from a random similar record as a reference.
            else:
                print("No similar records found in history for the current prompt.")
        if real_eva:
            fitness, simulation_meta = self.simulate_games(opponent, stats)
            parsed_log = simulation_meta.get("parsed_log")
            winner = simulation_meta.get("winner")
            timeout = simulation_meta.get("timeout", False)
            log_path = simulation_meta.get("log_path")
            llm_calls = simulation_meta.get("llm_calls", 0)
        else:
            with timer("EA_operator_time", stats):
                with timer("surrogate_time", stats):
                    surrogate_score = self.surrogate_evaluation(prompt, 
                                                                fitness_recorder=fitness_recorder)
                    power, uncertainty, simplicity, clarity = surrogate_score
                    fitness = [power] + individual.fitness[1:] if individual.fitness else [surrogate_score, 0.0, 0.0]
            
            llm_calls = 1

        fitness = normalize_fitness(fitness)
        print(fitness)

        fitness_recorder.record_fitness(
            {
                "individual_id": getattr(individual, "id", None),
                "generation": generation,
                "prompt": prompt,          # add for surrogate examples
                "fitness": fitness,        # compatibility key
                "fitness_score": fitness,  # current key
                "opponent": opponent,
                "evaluation_time": stats.get("total_eval_time", 0.0),
                "components": {
                    "game_rule": individual.game_rule,
                    "strategy": individual.strategy,
                }
            }
        )
        individual.fitness = fitness
        summarize_total_eval_time(stats)

        operator_profile = getattr(individual, "operator_profile", None)
        if isinstance(operator_profile, dict):
            for key in ("crossover_time", "mutation_time", "EA_operator_time"):
                stats[key] = stats.get(key, 0.0) + operator_profile.get(key, 0.0)
            summarize_total_eval_time(stats)

        #  only record real evaluation results to avoid contamination from surrogate evaluation.
        if profile_output_path is not None and real_eva:
            record = build_base_record(
                generation=generation,
                individual_id=getattr(individual, "id", None),
                record_type="evaluation",
            )
            record.update(
                {
                    "evaluation_mode": "real" if real_eva else "surrogate",
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
                    "surrogate_score": surrogate_score if not real_eva else None,
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
        prompt_path = self.repo_root / "prompt.txt"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt) 

    def construct_prompt(self, individual: Individual) -> str:
        # Use the individual's component indices to retrieve the corresponding components from the component pool and construct a prompt string
        prompt_lines: list[str] = []

        if self.component_pool.has_category("game_rule"):
            prompt_lines.extend(
                self.component_pool.get_component("game_rule", individual.game_rule)
            )

        strategy_order = [
            strategy
            for strategy in self.component_pool.strategy_keys
            if strategy in individual.strategy
        ]
        random.Random(repr(sorted((individual.strategy or {}).items()))).shuffle(strategy_order)
        strategy_components = [
            line
            for strategy in strategy_order
            for line in self.component_pool.get_strategy_component(strategy, individual.strategy[strategy])
        ]
        # Combine the components into a single prompt string (this is a simplified example, the actual construction may be more complex)
        prompt = "\n".join(prompt_lines + strategy_components)
        return prompt

    def game_round_available_evaluation(self, log_content: str) -> float:
        # An alternative evaluation method that analyzes the log content from a MicroRTS game to compute a fitness score based on the game rounds and available actions. This can provide a more granular assessment of the agent's performance throughout the game, rather than just the final outcome.

        # Parse the log content to extract move results and compute fitness based on the number of successful moves, available actions, and game rounds.
        parsed_log = parse_log(log_content)
        # print(f"Parsed log: {parsed_log}")
        summary = parsed_log["summary"]
        # print(f"Parsed log summary: {summary}")
        llm_moves = summary["llm_move_count"]
        direct_failure_count = summary["direct_failure_count"]
        duplicate_skipped_count = summary["duplicate_skipped_count"]
        applied_failure_count = summary["applied_failure_count"]
        applied_success_count = summary["applied_success_count"]

        # fitness for game_round_available_evaluation
        # fitness: [0, 1]
        if llm_moves == 0:
            return 0.0
        fitness = (applied_success_count + 0.5 * applied_failure_count - 0.1 * duplicate_skipped_count - 0.3 * direct_failure_count) / llm_moves

        return fitness

    def win_loss_evaluation(self, log_content: str, parsed_log: dict[str, Any] | None = None) -> float:
        # win = 1, loss = 0, draw = 0.5
        winning_score = 0.5  # Default to draw if no winner is found
        winner_info = parsed_log or self._parse_winner_info(log_content)["parsed_log"]
        summary = winner_info.get("summary", {})
        winner = summary.get("winner")
        target_side = summary.get("target_side")
        if winner is not None and target_side is not None:
            winning_score = 1.0 if str(winner) == str(target_side) else 0.0
        return winning_score

    def number_of_turns_evaluation(self, log_content: str) -> int:
        # parse the log content to get the number of turns in the game
        number_of_turns = 0
        for line in log_content.splitlines():
            if "current time" in line:
                parts = line.split()
                try:
                    number_of_turns = int(parts[2])  # Assuming the format is consistent
                except ValueError:
                    pass  # If parsing fails, keep number_of_turns as 0

        score = number_of_turns / 1000.0  # Normalize the score (assuming 1000 turns is a reasonable upper bound)
        return score

    def _material_total(self, snapshot: dict[str, Any]) -> float:
        return sum(
            float(self.config.resource_advantage_weights.get(key, 0.0)) * float(snapshot.get(key, 0.0))
            for key in self.config.resource_advantage_weights
        )

    def resource_advantage_evaluation(
        self,
        parsed_log: dict[str, Any],
        eps: float = 1e-9,
    ) -> float:
        feature_history = parsed_log.get("feature_history", [])
        if not feature_history:
            return 0.0

        n = len(feature_history)
        numerator = 0.0
        denominator = 0.0

        for i, row in enumerate(feature_history):
            ally_total = self._material_total(row.get("ally", {}))
            enemy_total = self._material_total(row.get("enemy", {}))
            weight = ((i + 1) / n) ** float(self.config.resource_advantage_alpha)

            numerator += weight * (ally_total - enemy_total)
            denominator += weight * (ally_total + enemy_total + eps)

        return numerator / denominator if denominator > 0 else 0.0

    def calculate_fitness_score(self, log_content: str, parsed_log: dict[str, Any] | None = None) -> list[float]:
        winner_info = parsed_log or self._parse_winner_info(log_content)["parsed_log"]
        winning_score = self.win_loss_evaluation(log_content, parsed_log=winner_info)
        resource_advantage_score = self.resource_advantage_evaluation(winner_info)
        game_round_score = self.game_round_available_evaluation(log_content)  # This can be used as an additional metric if desired

        print(
            "Parsed fitness: "
            f"winning_score={winning_score}, "
            f"resource_advantage={resource_advantage_score}, "
            f"game_round_fitness={game_round_score}"
        )

        # fitness
        # v1: winning_score
        # v2: winning_score + weighted resource advantage
        # v3: winning_score + weighted resource advantage + game_round_fitness
        # fitness = winning_score * 0.6 + game_round_score * 0.4

        return normalize_fitness([winning_score, resource_advantage_score, game_round_score])

    def set_opponent(self, opponent: str):
        # Set the opponent strategy for the next simulation runs (this can be used to evaluate the evolved prompts against different baseline strategies in MicroRTS)
        # This function can modify a configuration file or set an environment variable that the MicroRTS simulation reads to determine the opponent strategy.
        config_path = self.repo_root / "resources" / "config.properties"
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        with open(config_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.startswith("AI2="):
                    f.write(f"AI2={opponent}\n")
                else:
                    f.write(line)

    def launch_simulation(self, test: bool=False) -> subprocess.Popen[str]:
        # call MicroRTS/RunLoop.sh to run
        if test:
            run_loop = self.repo_root / "RunLoop_5000.sh"
        else:
            run_loop = self.repo_root / "RunLoop.sh"
        env = os.environ.copy()
        env["RUN_TIME_PER_GAME_SEC"] = str(self.config.run_time_per_game_sec)
        return subprocess.Popen(
            [str(run_loop)],
            cwd=str(self.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )


    def wait_for_simulation(self, process: subprocess.Popen[str]) -> tuple[str, str]:
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(f"Simulation process exited with code {process.returncode}")
            if stderr:
                print(f"Simulation error output:\n{stderr}")
        return stdout, stderr


    def get_latest_log_file(self) -> Path | None:
        # when the game end, read the result in MicroRTS/logs/run_2026-MM-DD_HH-MM-SS.log (the latest log file) to get the fitness score
        log_files = glob.glob(str(self.repo_root / "logs" / "run_*.log"))
        if not log_files:
            return None
        latest_log_file = sorted(log_files)[-1]
        return Path(latest_log_file)

    def extract_winner(self, log_content: str) -> str | None:
        return self._parse_winner_info(log_content)["winner"]

    def detect_timeout(self, log_content: str) -> bool:
        lower_content = log_content.lower()
        return "timeout" in lower_content or "timed out" in lower_content

    def simulate_games(self, opponent: str | None, stats: dict[str, float]) -> tuple[list[float], dict[str, Any]]:
        # Simulate multiple games in MicroRTS using the provided prompt and return an average fitness score based on performance against a baseline strategy

        with timer("bookkeeping_time", stats):
            if opponent is not None:
                self.set_opponent(opponent)

        with timer("game_launch_time", stats):
            process = self.launch_simulation()

        # This includes waiting for the game to complete and loading the produced log.
        with timer("game_play_time", stats):
            _, stderr = self.wait_for_simulation(process)
            if process.returncode != 0:
                if stderr:
                    print(stderr)
                return [0.0, 0.0, 0.0], {
                    "parsed_log": None,
                    "winner": None,
                    "timeout": True,
                    "log_path": None,
                    "llm_calls": 0,
                }

        latest_log_file = self.get_latest_log_file()
        if latest_log_file is None:
            return [0.0, 0.0, 0.0], {
                "parsed_log": None,
                "winner": None,
                "timeout": True,
                "log_path": None,
                "llm_calls": 0,
            }

        print(f"Testing parse_fitness with log file: {latest_log_file}")
        with open(latest_log_file, "r", encoding="utf-8") as f:
            log_content = f.read()

        with timer("log_parse_time", stats):
            parsed_log = parse_log(log_content)

        # parse the log content to get the fitness score
        fitness = self.calculate_fitness_score(log_content, parsed_log=parsed_log)
        metadata = {
            "parsed_log": parsed_log,
            "winner": parsed_log.get("summary", {}).get("winner"),
            "timeout": self.detect_timeout(log_content),
            "log_path": str(latest_log_file),
            "llm_calls": parsed_log.get("summary", {}).get("segment_count", 0),
        }
        return fitness, metadata

    def surrogate_evaluation(self, prompt: str, fitness_recorder: FitnessRecorder | None = None) -> list[float]:
        examples: list[list[str]] = []

        if fitness_recorder is not None and getattr(fitness_recorder, "records", None):
            sampled = random.sample(
                fitness_recorder.records,
                min(len(fitness_recorder.records), 3),
            )
            for record in sampled:
                p = record.get("prompt")
                f = record.get("fitness", record.get("fitness_score"))
                if p is None or f is None:
                    continue
                examples.append([p, str(f)])
        surrogate_scores = LLM.ollama_evaluate_fitness(prompt, example=examples)

        estimated_power, uncertainty, simplicity, clarity = surrogate_scores

        print(f"Surrogate evaluation - Estimated Power: {estimated_power}, Uncertainty: {uncertainty}, Simplicity: {simplicity}, Clarity: {clarity}")

        adjusted_power = max(0.0, estimated_power * 0.8 - 0.3 * uncertainty)
        
        print(f"Adjusted Power after uncertainty penalty: {adjusted_power}")

        surrogate_scores = [adjusted_power, uncertainty, simplicity, clarity]


        return surrogate_scores
