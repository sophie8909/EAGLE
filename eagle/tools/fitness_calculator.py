"""Calculate normalized fitness signals from parsed or raw MicroRTS logs."""

from __future__ import annotations

from typing import Any

from .fitness_utils import normalize_fitness
from .log_parse import parse_log


def parse_winner_info(log_content: str) -> dict[str, Any]:
    """Parse one game log and expose the winner-related summary fields."""
    parsed_log = parse_log(log_content)
    summary = parsed_log.get("summary", {})
    return {
        "parsed_log": parsed_log,
        "winner": summary.get("winner"),
        "target_side": summary.get("target_side"),
        "termination_reason": summary.get("termination_reason"),
    }


def game_round_execution_score(log_content: str) -> float:
    """Score move execution quality from counters extracted out of the log summary."""
    parsed_log = parse_log(log_content)
    summary = parsed_log["summary"]
    llm_moves = summary["llm_move_count"]
    direct_failure_count = summary["direct_failure_count"]
    duplicate_skipped_count = summary["duplicate_skipped_count"]
    applied_failure_count = summary["applied_failure_count"]
    applied_success_count = summary["applied_success_count"]

    if llm_moves == 0:
        return 0.0

    return (
        applied_success_count
        + 0.5 * applied_failure_count
        - 0.1 * duplicate_skipped_count
        - 0.3 * direct_failure_count
    ) / llm_moves


def win_loss_evaluation(log_content: str, parsed_log: dict[str, Any] | None = None) -> float:
    """Convert winner information into the primary win/loss objective."""
    winning_score = 0.5
    winner_info = parsed_log or parse_winner_info(log_content)["parsed_log"]
    summary = winner_info.get("summary", {})
    winner = summary.get("winner")
    target_side = summary.get("target_side")
    if winner is not None and target_side is not None:
        winning_score = 1.0 if str(winner) == str(target_side) else 0.0
    return winning_score


def turn_count_score(log_content: str) -> float:
    """Normalize the last observed game turn into a small auxiliary score."""
    number_of_turns = 0
    for line in log_content.splitlines():
        if "current time" in line:
            parts = line.split()
            try:
                number_of_turns = int(parts[2])
            except ValueError:
                pass

    return number_of_turns / 1000.0


def material_total(snapshot: dict[str, Any], resource_advantage_weights: dict[str, float]) -> float:
    """Collapse one ally/enemy snapshot into a weighted scalar total."""
    return sum(
        float(resource_advantage_weights.get(key, 0.0)) * float(snapshot.get(key, 0.0))
        for key in resource_advantage_weights
    )


def resource_advantage_evaluation(
    parsed_log: dict[str, Any],
    resource_advantage_alpha: float,
    resource_advantage_weights: dict[str, float],
    eps: float = 1e-9,
) -> float:
    """Compute a late-game-weighted material advantage score in [-1, 1]."""
    feature_history = parsed_log.get("feature_history", [])
    if not feature_history:
        return 0.0

    n = len(feature_history)
    numerator = 0.0
    denominator = 0.0

    for i, row in enumerate(feature_history):
        ally_total = material_total(row.get("ally", {}), resource_advantage_weights)
        enemy_total = material_total(row.get("enemy", {}), resource_advantage_weights)
        weight = ((i + 1) / n) ** float(resource_advantage_alpha)
        numerator += weight * (ally_total - enemy_total)
        denominator += weight * (ally_total + enemy_total + eps)

    return numerator / denominator if denominator > 0 else 0.0


def calculate_fitness_score(
    log_content: str,
    resource_advantage_alpha: float,
    resource_advantage_weights: dict[str, float],
    parsed_log: dict[str, Any] | None = None,
) -> list[float]:
    """Assemble the three-objective fitness vector for a real game result."""
    winner_info = parsed_log or parse_winner_info(log_content)["parsed_log"]
    winning_score = win_loss_evaluation(log_content, parsed_log=winner_info)
    round_score = game_round_execution_score(log_content)
    resource_score = resource_advantage_evaluation(
        winner_info,
        resource_advantage_alpha=resource_advantage_alpha,
        resource_advantage_weights=resource_advantage_weights,
    )
    return normalize_fitness([winning_score, round_score, resource_score])
