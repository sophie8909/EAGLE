"""Code-based validation for MicroRTS LLM action responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from eagle.utils.log_parse import parse_dynamic_prompt_state


VALID_UNIT_TYPES = {"worker", "light", "heavy", "ranged", "base", "barracks"}
VALID_ACTION_TYPES = {"move", "train", "build", "harvest", "attack"}


@dataclass(frozen=True)
class ValidationResult:
    """Validation outcome for one raw LLM response."""

    is_valid: bool
    valid_moves: list[dict[str, Any]]
    errors: list[str]
    legality_level: str = "schema_only"
    parsed_response: dict[str, Any] | None = None


def validate_llm_response(response_text: str, game_state: Any) -> ValidationResult:
    """Validate an LLM response before converting it into runtime examples."""
    errors: list[str] = []
    parsed_response = _extract_first_json_object(str(response_text or ""))
    if not isinstance(parsed_response, dict):
        return ValidationResult(
            is_valid=False,
            valid_moves=[],
            errors=["response is not a JSON object"],
        )

    if not isinstance(parsed_response.get("thinking"), str):
        errors.append("missing string field: thinking")

    moves = parsed_response.get("moves")
    if not isinstance(moves, list):
        errors.append("missing list field: moves")
        moves = []

    state = _coerce_game_state(game_state)
    legality_level = "state_checked" if state is not None else "schema_only"
    valid_moves: list[dict[str, Any]] = []

    for index, move in enumerate(moves):
        normalized = _validate_move_schema(move, index, errors)
        if normalized is None:
            continue
        _validate_move_consistency(normalized, index, errors_for_move := [])
        if state is not None:
            _validate_move_against_state(normalized, index, state, errors_for_move)
        if errors_for_move:
            errors.extend(errors_for_move)
            continue
        valid_moves.append(normalized)

    return ValidationResult(
        is_valid=not errors,
        valid_moves=valid_moves,
        errors=errors,
        legality_level=legality_level,
        parsed_response=parsed_response,
    )


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        return value if isinstance(value, dict) else None
    return None


def _coerce_game_state(game_state: Any) -> dict[str, Any] | None:
    if isinstance(game_state, dict):
        return game_state
    if isinstance(game_state, str) and game_state.strip():
        parsed = parse_dynamic_prompt_state(game_state)
        ally_units = parsed.get("ally_units")
        return parsed if isinstance(ally_units, dict) and ally_units else None
    return None


def _validate_move_schema(move: Any, index: int, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(move, dict):
        errors.append(f"moves[{index}] is not an object")
        return None

    raw_move = move.get("raw_move")
    unit_type = move.get("unit_type")
    action_type = move.get("action_type")
    unit_position = move.get("unit_position")

    move_errors: list[str] = []
    if not isinstance(raw_move, str):
        move_errors.append(f"moves[{index}] missing string field: raw_move")
    if not isinstance(unit_type, str):
        move_errors.append(f"moves[{index}] missing string field: unit_type")
    if not isinstance(action_type, str):
        move_errors.append(f"moves[{index}] missing string field: action_type")
    if (
        not isinstance(unit_position, list)
        or len(unit_position) != 2
        or not all(isinstance(value, int) for value in unit_position)
    ):
        move_errors.append(f"moves[{index}] missing [int, int] field: unit_position")

    normalized_unit_type = _normalize_unit_type(unit_type) if isinstance(unit_type, str) else ""
    normalized_action_type = _normalize_action_type(action_type) if isinstance(action_type, str) else ""
    if normalized_unit_type and normalized_unit_type not in VALID_UNIT_TYPES:
        move_errors.append(f"moves[{index}] invalid unit_type: {unit_type}")
    if normalized_action_type and normalized_action_type not in VALID_ACTION_TYPES:
        move_errors.append(f"moves[{index}] invalid action_type: {action_type}")

    if move_errors:
        errors.extend(move_errors)
        return None

    return {
        "raw_move": raw_move.strip(),
        "unit_position": [int(unit_position[0]), int(unit_position[1])],
        "unit_type": normalized_unit_type,
        "action_type": normalized_action_type,
    }


def _validate_move_consistency(move: dict[str, Any], index: int, errors: list[str]) -> None:
    x, y = move["unit_position"]
    unit_type = move["unit_type"]
    raw_move = move["raw_move"].strip()
    prefix_pattern = rf"^\(\s*{x}\s*,\s*{y}\s*\):\s+{re.escape(unit_type)}\s+"
    if re.search(prefix_pattern, raw_move, re.IGNORECASE) is None:
        errors.append(f"moves[{index}] raw_move prefix does not match unit_position and unit_type")

    raw_action = _raw_move_action_type(raw_move)
    if raw_action is None:
        errors.append(f"moves[{index}] raw_move action is missing")
    elif raw_action != move["action_type"]:
        errors.append(f"moves[{index}] action_type does not match raw_move action")


def _validate_move_against_state(
    move: dict[str, Any],
    index: int,
    state: dict[str, Any],
    errors: list[str],
) -> None:
    x, y = move["unit_position"]
    ally_units = state.get("ally_units")
    if not isinstance(ally_units, dict):
        return
    unit_info = ally_units.get((x, y))
    if not isinstance(unit_info, dict):
        errors.append(f"moves[{index}] unit_position is not an ally unit")
        return
    if not bool(unit_info.get("available_for_new_command", True)):
        errors.append(f"moves[{index}] unit_position is not idle/actionable")
    actual_type = _normalize_unit_type(str(unit_info.get("type", "")))
    if actual_type != move["unit_type"]:
        errors.append(f"moves[{index}] unit_type mismatch: expected {actual_type}")


def _raw_move_action_type(raw_move: str) -> str | None:
    match = re.search(
        r"^\(\s*-?\d+\s*,\s*-?\d+\s*\):\s+[a-z_]+\s+([a-z_]+)\s*(?:\(|$)",
        raw_move.strip(),
        re.IGNORECASE,
    )
    return _normalize_action_type(match.group(1)) if match else None


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


def _normalize_action_type(action_type: str) -> str:
    return str(action_type or "").strip().lower()

