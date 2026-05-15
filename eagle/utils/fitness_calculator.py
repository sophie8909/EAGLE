"""Calculate fitness signals from parsed or raw MicroRTS logs."""

from __future__ import annotations

from typing import Any

from .log_parse import parse_log


def parse_winner_info(log_content: str, target_agent: str = "EAGLE") -> dict[str, Any]:
    """Parse one game log and expose the winner-related summary fields."""
    parsed_log = parse_log(log_content, target_agent=target_agent)
    summary = parsed_log.get("summary", {})
    return {
        "parsed_log": parsed_log,
        "winner": summary.get("winner"),
        "target_side": summary.get("target_side"),
        "termination_reason": summary.get("termination_reason"),
    }


def win_loss_evaluation(log_content: str, parsed_log: dict[str, Any] | None = None) -> float:
    """Convert winner information into the primary win/loss objective."""
    winning_score = 0.0
    winner_info = parsed_log or parse_winner_info(log_content)["parsed_log"]
    summary = winner_info.get("summary", {})
    winner = summary.get("winner")
    target_side = summary.get("target_side")
    if winner is not None and target_side is not None:
        winning_score = 1.0 if str(winner) == str(target_side) else -1.0
    return winning_score


def material_total(snapshot: dict[str, Any], resource_advantage_weights: dict[str, float]) -> float:
    """Collapse one ally/enemy snapshot into a weighted scalar total."""
    return sum(
        float(resource_advantage_weights.get(key, 0.0)) * float(snapshot.get(key, 0.0))
        for key in resource_advantage_weights
    )


def raw_resource_advantage_score(
    parsed_log: dict[str, Any],
    resource_advantage_weights: dict[str, float],
) -> float:
    """Compute the final weighted ally-minus-enemy material/resource difference."""
    summary = parsed_log.get("summary", {})
    target_side = summary.get("target_side")
    final_tick = summary.get("final_tick")
    final_scoreboard = summary.get("final_scoreboard")
    feature_history = parsed_log.get("feature_history", [])
    resource_history = parsed_log.get("resource_history", [])

    if _should_use_terminal_scoreboard(summary, feature_history):
        return _scoreboard_advantage(final_scoreboard, target_side)

    ally_total = 0.0
    enemy_total = 0.0

    if feature_history:
        final_row = feature_history[-1]
        ally_total += material_total(final_row.get("ally", {}), resource_advantage_weights)
        enemy_total += material_total(final_row.get("enemy", {}), resource_advantage_weights)

    if resource_history:
        final_row = resource_history[-1]
        p0_resources = float(final_row.get("p0_resources", 0.0))
        p1_resources = float(final_row.get("p1_resources", 0.0))
        resource_weight = float(resource_advantage_weights.get("resource", 1.0))
        if str(target_side) == "1":
            ally_resources = p1_resources * resource_weight
            enemy_resources = p0_resources * resource_weight
        else:
            ally_resources = p0_resources * resource_weight
            enemy_resources = p1_resources * resource_weight
        
        ally_total += ally_resources
        enemy_total += enemy_resources

    return ally_total - enemy_total


def _should_use_terminal_scoreboard(summary: dict[str, Any], feature_history: list[dict[str, Any]]) -> bool:
    """Return whether the completed game scoreboard is the best terminal state source."""
    final_scoreboard = summary.get("final_scoreboard")
    if not isinstance(final_scoreboard, dict):
        return False
    if summary.get("wall_clock_timeout") or summary.get("tick_timeout"):
        return False
    if summary.get("winner") is None:
        return False
    return not _has_snapshot_at_tick(feature_history, summary.get("final_tick"))


def _has_snapshot_at_tick(history: list[dict[str, Any]], tick: Any) -> bool:
    """Return whether a parsed history includes the exact terminal tick."""
    try:
        target_tick = int(tick)
    except (TypeError, ValueError):
        return False
    return any(int(row.get("time", -1)) == target_tick for row in history if isinstance(row, dict))


def _scoreboard_advantage(scoreboard: dict[str, Any], target_side: Any) -> float:
    """Return target-side advantage from the terminal MicroRTS scoreboard."""
    try:
        p0_eval = float(scoreboard.get("p0_eval", 0.0))
        p1_eval = float(scoreboard.get("p1_eval", 0.0))
    except (TypeError, ValueError):
        return 0.0
    if str(target_side) == "1":
        return p1_eval - p0_eval
    return p0_eval - p1_eval


def combined_match_score(
    match_score: dict[str, Any] | None,
    *,
    win_bonus: float,
) -> float:
    """
    Collapse one raw match score into one scalar score for one opponent slot.

    Raw match score stays as:
    - `win_score`
    - `raw_resource_advantage_score`

    EA-level fitness for NSGA-II/GA uses one scalar per configured opponent:
    `raw_resource_advantage_score + win_bonus * win_score`
    """
    if not match_score:
        return 0.0

    try:
        win_score = float(match_score.get("win_score", 0.0))
    except (TypeError, ValueError):
        win_score = 0.0
    try:
        resource_score = float(match_score.get("raw_resource_advantage_score", 0.0))
    except (TypeError, ValueError):
        resource_score = 0.0

    return resource_score + float(win_bonus) * win_score


def calculate_match_score(
    log_content: str,
    resource_advantage_weights: dict[str, float],
    parsed_log: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Assemble one raw per-match score dict with stable named fields."""
    winner_info = parsed_log or parse_winner_info(log_content)["parsed_log"]
    winning_score = win_loss_evaluation(log_content, parsed_log=winner_info)
    resource_score = raw_resource_advantage_score(winner_info, resource_advantage_weights)
    return {
        "win_score": winning_score,
        "raw_resource_advantage_score": resource_score,
    }
