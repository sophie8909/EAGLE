"""Validate and score LLM-issued actions against sampled Dynamic Prompt state."""

from __future__ import annotations

import re
from typing import Any

from .log_parse import parse_dynamic_prompt_state


def is_in_bounds(x: int, y: int, state: dict[str, Any]) -> bool:
    """Return whether a coordinate lies inside the parsed map rectangle."""
    width = state.get("map_width")
    height = state.get("map_height")
    if width is None or height is None:
        return True
    return 0 <= x < width and 0 <= y < height


def validate_llm_move_against_state(
    move: dict[str, Any],
    state: dict[str, Any],
) -> tuple[bool, str]:
    """Check whether one proposed move is legal for the sampled game state."""
    if not isinstance(move, dict):
        return False, "invalid_move"

    unit_position = move.get("unit_position")
    action_type = str(move.get("action_type", "")).strip().lower()
    unit_type = str(move.get("unit_type", "")).strip().lower().replace("ally_", "")

    if not isinstance(unit_position, list) or len(unit_position) != 2:
        return False, "missing_unit_position"

    ux, uy = unit_position
    if not isinstance(ux, int) or not isinstance(uy, int):
        return False, "invalid_unit_position"

    ally_units = state.get("ally_units", {})
    enemy_units = state.get("enemy_units", {})
    unit_info = ally_units.get((ux, uy))
    if unit_info is None:
        return False, "non_owned_unit"

    actual_type = str(unit_info.get("type", "")).lower()
    if unit_type and unit_type not in {actual_type, f"ally {actual_type}", f"ally_{actual_type}"}:
        return False, "unit_type_mismatch"

    if action_type == "idle":
        return True, "idle"

    if not unit_info.get("available_for_new_command", True):
        return False, "unit_busy"

    if action_type == "train":
        if actual_type not in {"base", "barracks"}:
            return False, "train_on_non_structure"
        return True, "train"

    if action_type in {"move", "build", "harvest", "attack"} and actual_type not in {"worker", "light", "heavy", "ranged"}:
        return False, "invalid_mobile_action"

    if action_type == "harvest":
        if actual_type != "worker":
            return False, "non_worker_harvest"
        raw_move = str(move.get("raw_move", ""))
        coords = [tuple(map(int, match)) for match in re.findall(r"\((-?\d+),\s*(-?\d+)\)", raw_move)]
        if len(coords) < 3:
            return False, "harvest_targets_missing"
        resource_pos = coords[1]
        base_pos = coords[2]
        if resource_pos not in state.get("neutral_resources", {}):
            return False, "invalid_resource_target"
        if base_pos not in state.get("ally_bases", {}):
            return False, "invalid_base_target"
        return True, "harvest"

    if action_type == "build":
        if actual_type != "worker":
            return False, "non_worker_build"
        raw_move = str(move.get("raw_move", ""))
        coords = [tuple(map(int, match)) for match in re.findall(r"\((-?\d+),\s*(-?\d+)\)", raw_move)]
        if len(coords) < 2:
            return False, "build_target_missing"
        build_pos = coords[1]
        if not is_in_bounds(build_pos[0], build_pos[1], state):
            return False, "build_out_of_bounds"
        if build_pos in ally_units or build_pos in enemy_units or build_pos in state.get("neutral_resources", {}):
            return False, "build_occupied"
        return True, "build"

    if action_type == "attack":
        raw_move = str(move.get("raw_move", ""))
        coords = [tuple(map(int, match)) for match in re.findall(r"\((-?\d+),\s*(-?\d+)\)", raw_move)]
        if len(coords) < 2:
            return False, "attack_target_missing"
        target_pos = coords[1]
        if target_pos not in enemy_units:
            return False, "invalid_attack_target"
        return True, "attack"

    if action_type == "move":
        raw_move = str(move.get("raw_move", ""))
        coords = [tuple(map(int, match)) for match in re.findall(r"\((-?\d+),\s*(-?\d+)\)", raw_move)]
        if len(coords) < 2:
            return False, "move_target_missing"
        target_pos = coords[1]
        if not is_in_bounds(target_pos[0], target_pos[1], state):
            return False, "move_out_of_bounds"
        return True, "move"

    return False, "unsupported_action"


def score_game_round_response(
    llm_response: dict[str, Any] | None,
    dynamic_prompt_text: str,
) -> float:
    """Score a full move list by validating each move against the sampled state."""
    if not isinstance(llm_response, dict):
        return 0.0

    moves = llm_response.get("moves")
    if not isinstance(moves, list) or not moves:
        return 0.0

    state = parse_dynamic_prompt_state(dynamic_prompt_text)
    llm_moves = len(moves)
    direct_failure_count = 0
    duplicate_skipped_count = 0
    applied_failure_count = 0
    applied_success_count = 0
    seen_positions: set[tuple[int, int]] = set()

    for move in moves:
        unit_position = move.get("unit_position")
        if isinstance(unit_position, list) and len(unit_position) == 2 and all(isinstance(v, int) for v in unit_position):
            unit_position_tuple = (unit_position[0], unit_position[1])
            if unit_position_tuple in seen_positions:
                duplicate_skipped_count += 1
                continue
            seen_positions.add(unit_position_tuple)

        ok, reason = validate_llm_move_against_state(move, state)
        if ok:
            applied_success_count += 1
        else:
            if reason in {"non_owned_unit", "missing_unit_position", "invalid_unit_position", "unit_type_mismatch"}:
                direct_failure_count += 1
            else:
                applied_failure_count += 1

    return (
        applied_success_count
        + 0.5 * applied_failure_count
        - 0.1 * duplicate_skipped_count
        - 0.3 * direct_failure_count
    ) / llm_moves if llm_moves > 0 else 0.0
