"""Competition-style aggregation that excludes incomplete matches from rates."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any, Callable, Iterable


def aggregate_final_test_results(
    records: Iterable[dict[str, Any]],
    *,
    expected_by_candidate: dict[str, int],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["candidate_id"])].append(record)
    candidates: dict[str, Any] = {}
    for candidate_id, expected in expected_by_candidate.items():
        candidate_records = grouped.get(candidate_id, [])
        aggregate = _metrics(candidate_records, expected=expected)
        candidates[candidate_id] = {
            "evolution_game_performance": _first_number(
                candidate_records, "evolution_game_performance"
            ),
            "evolution_code_quality": _first_number(candidate_records, "evolution_code_quality"),
            "aggregate": aggregate,
            "by_opponent": _breakdown(candidate_records, lambda item: str(item["opponent_id"])),
            "by_map": _breakdown(candidate_records, lambda item: str(item["map_id"])),
            "by_player_side": _breakdown(
                candidate_records, lambda item: f"player_{int(item['candidate_player'])}"
            ),
            "by_opponent_map": _breakdown(
                candidate_records,
                lambda item: f"{item['opponent_id']}|{item['map_id']}",
            ),
        }
    completed = sum(item["aggregate"]["completed_matches"] for item in candidates.values())
    expected_total = sum(expected_by_candidate.values())
    return {
        "aggregation_schema_version": "eagle-final-test-aggregation-v1",
        "competition_scoring": {"win": 1.0, "draw": 0.5, "loss": 0.0},
        "incomplete_match_denominator_policy": "excluded_from_rates_and_scores",
        "expected_total_matches": expected_total,
        "completed_total_matches": completed,
        "incomplete_total_matches": expected_total - completed,
        "formal_test_complete": completed == expected_total,
        "candidates": candidates,
    }


def _breakdown(
    records: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[key(record)].append(record)
    return {name: _metrics(items, expected=len(items)) for name, items in sorted(grouped.items())}


def _metrics(records: list[dict[str, Any]], *, expected: int) -> dict[str, Any]:
    completed = [item for item in records if item.get("status") == "success"]
    wins = draws = losses = 0
    points = 0.0
    lengths: list[float] = []
    for item in completed:
        winner = _integer(item.get("winner"))
        side = _integer(item.get("candidate_player"))
        if winner == -1:
            draws += 1
            points += 0.5
        elif winner == side:
            wins += 1
            points += 1.0
        else:
            losses += 1
        final_tick = item.get("final_tick")
        if isinstance(final_tick, (int, float)) and not isinstance(final_tick, bool):
            lengths.append(float(final_tick))
    denominator = len(completed)
    incomplete = expected - denominator
    return {
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "total_matches": expected,
        "completed_matches": denominator,
        "incomplete_matches": incomplete,
        "win_rate": None if denominator == 0 else wins / denominator,
        "non_loss_rate": None if denominator == 0 else (wins + draws) / denominator,
        "competition_points": points,
        "final_test_competition_score": None if denominator == 0 else points / denominator,
        "final_test_win_rate": None if denominator == 0 else wins / denominator,
        "mean_game_length": None if not lengths else statistics.fmean(lengths),
        "runtime_failures": sum(item.get("status") != "success" for item in records),
    }


def _first_number(records: list[dict[str, Any]], name: str) -> float | None:
    for record in records:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _integer(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

