"""Single-round prompt evaluator for generated MicroRTS states."""

from __future__ import annotations

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

    DEFAULT_ACTION_TYPE_SCORES = {
        "idle": 0.0,
        "move": 10.0,
        "harvest": 2.0,
        "build": 10.0,
        "train": 3.0,
        "attack": 3.0,
    }

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
                format_valid, format_reason = self._validate_action_response_format(parsed_response)

                if format_valid:
                    legality_score, legality_details = self._score_legality(parsed_response, dynamic_prompt)
                    alignment_score = self._score_strategy_alignment(
                        base_prompt=base_prompt,
                        dynamic_prompt=dynamic_prompt,
                        raw_response=raw_response,
                    )
                else:
                    legality_score = -100.0
                    alignment_score = -100.0
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
        invalid_actions = 0
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
            else:
                invalid_actions += 1
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

        idle_penalty = abs(len(moves) - max_actions)
        

        score = (action_type_score_sum - invalid_actions * 5 - idle_penalty * 2) / max_actions

        return score, {
            "parseable": True,
            "format_valid": True,
            "max_actions": max_actions,
            "applicable_actions": valid_actions,
            "action_type_score_sum": action_type_score_sum,
            "returned_actions": len(moves),
            "moves": move_results,
        }

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
            return 3.0
        if action_type == "move":
            return 0.5
        if action_type == "idle":
            return 0.0
        if action_type == "build":
            building_type = self._extract_building_type(move)
            if not building_type:
                return 10.0
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

    @staticmethod
    def _extract_building_type(move: dict[str, Any]) -> str | None:
        raw_move = str(move.get("raw_move", "")).lower()
        match = re.search(r"\bbuild\s*\(.*,\s*([a-z_]+)\s*\)", raw_move)
        if not match:
            return None
        return Evaluator._normalize_unit_type(match.group(1))

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
