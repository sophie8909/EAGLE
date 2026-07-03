"""Output and summary helpers for MicroRTS surrogate-validation experiments."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .replay_common import write_results_snapshot


def average(values: list[float]) -> float | None:
    """Return the arithmetic mean when at least one value is present."""
    if not values:
        return None
    return sum(values) / len(values)


def safe_float(value: Any) -> float | None:
    """Convert one optional numeric-ish value into float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _match_win_score(match_score: Any) -> float | None:
    if isinstance(match_score, dict):
        return safe_float(match_score.get("win_score"))
    if isinstance(match_score, list) and match_score:
        return safe_float(match_score[0])
    return None


def _match_resource_score(match_score: Any) -> float | None:
    if isinstance(match_score, dict):
        return safe_float(match_score.get("raw_resource_advantage_score"))
    if isinstance(match_score, list) and len(match_score) > 1:
        return safe_float(match_score[1])
    return None


def build_mode_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one benchmark mode into compact summary statistics."""
    if not records:
        return {
            "match_count": 0,
            "cached_match_count": 0,
            "avg_win_score": None,
            "avg_resource_advantage_score": None,
            "avg_game_time_sec": None,
            "avg_final_tick": None,
            "win_count": 0,
            "draw_count": 0,
            "loss_count": 0,
        }

    return {
        "match_count": len(records),
        "cached_match_count": sum(1 for record in records if record.get("cached")),
        "avg_win_score": average([float(record.get("win_score", 0.0)) for record in records]),
        "avg_resource_advantage_score": average(
            [float(record.get("resource_advantage_score", 0.0)) for record in records]
        ),
        "avg_game_time_sec": average(
            [float(record.get("game_time_sec", 0.0)) for record in records if record.get("game_time_sec") is not None]
        ),
        "avg_final_tick": average(
            [float(record.get("final_tick", 0.0)) for record in records if record.get("final_tick") is not None]
        ),
        "win_count": sum(1 for record in records if record.get("result") == "Win"),
        "draw_count": sum(1 for record in records if record.get("result") == "Draw"),
        "loss_count": sum(1 for record in records if record.get("result") == "Loss"),
    }


def collect_match_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all individual/mode match results into one table."""
    rows: list[dict[str, Any]] = []
    for individual_result in list(results.get("individual_results") or []):
        individual_info = dict(individual_result.get("individual") or {})
        for mode_name, records in dict(individual_result.get("modes") or {}).items():
            for record in records:
                rows.append(
                    {
                        "experiment_type": results.get("experiment_type"),
                        "timestamp": results.get("timestamp"),
                        "prompt_digest": individual_result.get("prompt_digest"),
                        "individual_id": individual_info.get("id"),
                        "mode": mode_name,
                        "benchmark_mode": record.get("benchmark_mode"),
                        "opponent": record.get("opponent"),
                        "result": record.get("result"),
                        "win_score": record.get("win_score"),
                        "resource_advantage_score": record.get("resource_advantage_score"),
                        "game_time_sec": record.get("game_time_sec"),
                        "final_tick": record.get("final_tick"),
                        "max_cycles": record.get("max_cycles"),
                        "winner": record.get("winner"),
                        "timeout": record.get("timeout"),
                        "llm_calls": record.get("llm_calls"),
                        "llm_interval": record.get("llm_interval"),
                        "tick_limit": record.get("tick_limit"),
                        "llm_call_limit": record.get("llm_call_limit"),
                        "runner_script": record.get("runner_script"),
                        "ai1": record.get("ai1"),
                        "ai2": record.get("ai2"),
                        "java_match_win_score": record.get("java_match_win_score"),
                        "java_match_resource_advantage_score": record.get("java_match_resource_advantage_score"),
                        "cached": record.get("cached"),
                        "log_path": record.get("log_path"),
                    }
                )
    return rows


def write_match_results_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write one flat per-match CSV for downstream plotting and spreadsheet analysis."""
    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "mode",
        "benchmark_mode",
        "opponent",
        "result",
        "win_score",
        "resource_advantage_score",
        "game_time_sec",
        "final_tick",
        "max_cycles",
        "winner",
        "timeout",
        "llm_calls",
        "llm_interval",
        "tick_limit",
        "llm_call_limit",
        "runner_script",
        "ai1",
        "ai2",
        "java_match_win_score",
        "java_match_resource_advantage_score",
        "cached",
        "log_path",
    ]
    output_path = log_dir / "surrogate_validation_matches.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(collect_match_rows(results))


def write_mode_summary_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write one compact per-mode summary CSV for quick experiment comparison."""
    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "mode",
        "match_count",
        "cached_match_count",
        "runner_script",
        "avg_win_score",
        "avg_resource_advantage_score",
        "avg_game_time_sec",
        "avg_final_tick",
        "win_count",
        "draw_count",
        "loss_count",
    ]
    output_path = log_dir / "surrogate_validation_mode_summary.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for individual_result in list(results.get("individual_results") or []):
            summaries = dict(individual_result.get("mode_summaries") or {})
            individual_info = dict(individual_result.get("individual") or {})
            for mode_name, summary in summaries.items():
                writer.writerow(
                    {
                        "experiment_type": results.get("experiment_type"),
                        "timestamp": results.get("timestamp"),
                        "prompt_digest": individual_result.get("prompt_digest"),
                        "individual_id": individual_info.get("id"),
                        "mode": mode_name,
                        "runner_script": "RunLoop_5000.sh",
                        **summary,
                    }
                )


def build_alignment_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Build per-individual/per-opponent Java-vs-surrogate alignment rows."""
    rows: list[dict[str, Any]] = []
    for individual_result in list(results.get("individual_results") or []):
        individual_info = dict(individual_result.get("individual") or {})
        eagle_by_opponent = {
            row.get("opponent"): row
            for row in list(dict(individual_result.get("modes") or {}).get("eagle_final_test") or [])
            if row.get("opponent")
        }
        surrogate_by_opponent = {
            row.get("opponent"): row
            for row in list(dict(individual_result.get("modes") or {}).get("eagle_policy_final_test") or [])
            if row.get("opponent")
        }
        for opponent in sorted(set(eagle_by_opponent) | set(surrogate_by_opponent)):
            eagle_record = eagle_by_opponent.get(opponent, {})
            surrogate_record = surrogate_by_opponent.get(opponent, {})
            eagle_match_score = eagle_record.get("match_score") or eagle_record.get("fitness") or {}
            surrogate_match_score = surrogate_record.get("match_score") or surrogate_record.get("fitness") or {}
            eagle_win_score = _match_win_score(eagle_match_score)
            surrogate_win_score = _match_win_score(surrogate_match_score)
            eagle_resource_score = _match_resource_score(eagle_match_score)
            surrogate_resource_score = _match_resource_score(surrogate_match_score)
            win_gap = (
                abs(float(eagle_win_score) - float(surrogate_win_score))
                if eagle_win_score is not None and surrogate_win_score is not None
                else None
            )
            resource_gap = (
                abs(float(eagle_resource_score) - float(surrogate_resource_score))
                if eagle_resource_score is not None and surrogate_resource_score is not None
                else None
            )
            gap_values = [value for value in [win_gap, resource_gap] if value is not None]
            rows.append(
                {
                    "experiment_type": results.get("experiment_type"),
                    "timestamp": results.get("timestamp"),
                    "prompt_digest": individual_result.get("prompt_digest"),
                    "individual_id": individual_info.get("id"),
                    "opponent": opponent,
                    "eagle_result": eagle_record.get("result"),
                    "surrogate_result": surrogate_record.get("result"),
                    "eagle_win_score": eagle_record.get("win_score"),
                    "surrogate_win_score": surrogate_record.get("win_score"),
                    "eagle_resource_advantage_score": eagle_record.get("resource_advantage_score"),
                    "surrogate_resource_advantage_score": surrogate_record.get("resource_advantage_score"),
                    "win_score_abs_gap": win_gap,
                    "resource_advantage_score_abs_gap": resource_gap,
                    "mean_abs_gap": average(gap_values),
                    "same_result_label": eagle_record.get("result") == surrogate_record.get("result")
                    if eagle_record and surrogate_record
                    else None,
                }
            )
    return rows


def write_alignment_csv(log_dir: Path, results: dict[str, Any]) -> None:
    """Write per-individual/per-opponent Java-vs-surrogate alignment rows."""
    fieldnames = [
        "experiment_type",
        "timestamp",
        "prompt_digest",
        "individual_id",
        "opponent",
        "eagle_result",
        "surrogate_result",
        "eagle_win_score",
        "surrogate_win_score",
        "eagle_resource_advantage_score",
        "surrogate_resource_advantage_score",
        "win_score_abs_gap",
        "resource_advantage_score_abs_gap",
        "mean_abs_gap",
        "same_result_label",
    ]
    output_path = log_dir / "surrogate_validation_alignment.csv"
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(build_alignment_rows(results))


def build_alignment_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate alignment quality across all individuals and opponents."""
    if not rows:
        return {
            "pair_count": 0,
            "same_result_rate": None,
            "avg_win_score_abs_gap": None,
            "avg_resource_advantage_score_abs_gap": None,
            "avg_mean_abs_gap": None,
        }
    same_result_flags = [bool(row.get("same_result_label")) for row in rows if row.get("same_result_label") is not None]
    return {
        "pair_count": len(rows),
        "same_result_rate": average([1.0 if flag else 0.0 for flag in same_result_flags]) if same_result_flags else None,
        "avg_win_score_abs_gap": average(
            [value for value in [safe_float(row.get("win_score_abs_gap")) for row in rows] if value is not None]
        ),
        "avg_resource_advantage_score_abs_gap": average(
            [value for value in [safe_float(row.get("resource_advantage_score_abs_gap")) for row in rows] if value is not None]
        ),
        "avg_mean_abs_gap": average(
            [value for value in [safe_float(row.get("mean_abs_gap")) for row in rows] if value is not None]
        ),
    }


def write_experiment_outputs(log_dir: Path, results: dict[str, Any]) -> None:
    """Write the main surrogate-validation JSON and CSV outputs."""
    write_results_snapshot(results, log_dir / "surrogate_validation_results.json")
    write_match_results_csv(log_dir, results)
    write_mode_summary_csv(log_dir, results)
    write_alignment_csv(log_dir, results)


def refresh_experiment_outputs(
    log_dir: Path,
    results: dict[str, Any],
    individual_result: dict[str, Any],
) -> None:
    """Recompute summaries and persist the current experiment snapshot."""
    individual_result["mode_summaries"] = {
        mode_name: build_mode_summary(mode_records)
        for mode_name, mode_records in dict(individual_result.get("modes") or {}).items()
    }
    alignment_rows = build_alignment_rows(results)
    results["alignment_summary"] = build_alignment_summary(alignment_rows)
    write_experiment_outputs(log_dir, results)

