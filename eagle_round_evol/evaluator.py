"""Single-round prompt evaluator for generated MicroRTS states."""

from __future__ import annotations

from ctypes import alignment
import json
import re
from pathlib import Path
from typing import Any

import requests

from eagle.config import EAConfig
from eagle.utils.component_pool import ComponentPool
from eagle.utils.log_parse import parse_dynamic_prompt_state
from eagle.utils.move_validator import validate_llm_move_against_state

from .individual import Individual
from .prompt_history import PromptHistory
from .state_generator import StateGenerator

class Evaluator:
    """Evaluate prompts by asking an LLM for one generated game-state response."""

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
        self.history = PromptHistory(getattr(self.config, "prompt_history_path", "../eagle_round_evol/history.jsonl"))

    
    def evaluate(
        self,
        individual: Individual,
        *,
        generation: int | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Generate one state, ask for actions, and assign two-objective fitness."""
        base_prompt = self._construct_prompt(individual)
        

        cached = self.history.get(base_prompt)

        if cached is not None:
            print(f"Found cached fitness for prompt (hash={self.history._hash_prompt(base_prompt)}), skipping LLM evaluation.")
            individual.fitness = cached
            individual.evaluation_mode = "cached"
        else:
            legality_score_sum = 0.0
            alignment_score_sum = 0.0
            n = self.config.one_eval_rounds
            for i in range(n):
                dynamic_prompt = self.state_generator.generate_text()
                full_prompt = self._build_round_prompt(base_prompt, dynamic_prompt)
                raw_response = self._ask_for_actions(full_prompt)
                parsed_response = self._extract_first_json_object(raw_response)

                legality_score, legality_details = self._score_legality(parsed_response, dynamic_prompt)
                alignment_score = self._score_strategy_alignment(
                    base_prompt=base_prompt,
                    dynamic_prompt=dynamic_prompt,
                    raw_response=raw_response,
                )
                legality_score_sum += legality_score
                alignment_score_sum += alignment_score

            fitness = [ legality_score_sum / n, alignment_score_sum / n ]
            individual.fitness = fitness
            individual.evaluation_mode = "round_llm"
            individual.last_round_evaluation = {
                "generation": generation,
                "base_prompt": base_prompt,
                "dynamic_prompt": dynamic_prompt,
                "full_prompt": full_prompt,
                "raw_response": raw_response,
                "parsed_response": parsed_response,
                "legality": legality_details,
                "strategy_alignment_score": alignment_score_sum / n,
                "fitness": fitness,
            }

            self.history.save(
                prompt=base_prompt,
                fitness=fitness,
                metadata={
                    "evaluation_mode": individual.evaluation_mode,
                    "round": individual.last_round_evaluation,
                }
            )
        return {
            "prompt": base_prompt,
            "fitness": individual.fitness,
            "evaluation_mode": individual.evaluation_mode,
            "round": individual.last_round_evaluation,
        }

    def _construct_prompt(self, individual: Individual) -> str:
        static_prompt_lines: list[str] = []
        if self.component_pool.has_category("game_rule"):
            static_prompt_lines = self.component_pool.render_selected_static_prompt_lines(
                individual.static_components,
                game_rule_index=individual.game_rule,
            )
        strategy_prompt_lines = self.component_pool.render_strategy_prompt_lines(
            individual.strategy,
            include_strategy_identity=getattr(self.config, "include_strategy_identity_in_prompt", True),
        )
        prompt_lines = static_prompt_lines.copy()
        if prompt_lines and strategy_prompt_lines:
            prompt_lines.append("")
        prompt_lines.extend(strategy_prompt_lines)
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
                "moves": [],
            }

        moves = parsed_response.get("moves")
        if not isinstance(moves, list):
            moves = []

        state = parse_dynamic_prompt_state(dynamic_prompt)
        max_actions = max(1, self._extract_max_actions(dynamic_prompt))
        seen_positions: set[tuple[int, int]] = set()
        valid_actions = 0
        invalid_actions = 0
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
            if applied:
                valid_actions += 1
            else:
                invalid_actions += 1
            move_results.append(
                {
                    "move": move,
                    "applicable": applied,
                    "duplicate": duplicate,
                    "reason": "duplicate_unit" if duplicate else reason,
                }
            )
        # print(f"Dynamic prompt:\n{dynamic_prompt}\n")
        # print(f"Move results:\n{json.dumps(move_results, indent=2)}\n")

        idle_penalty = abs(len(moves) - max_actions)
        
        score = (valid_actions * 10 - invalid_actions * 5 - idle_penalty * 2) / max_actions

        return score, {
            "parseable": True,
            "max_actions": max_actions,
            "applicable_actions": valid_actions,
            "returned_actions": len(moves),
            "moves": move_results,
        }

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
