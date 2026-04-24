"""Summarize win/loss statistics from one final-test results JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _normalize_result(record: dict[str, Any]) -> str:
    """Map one replay record onto Win/Loss/Draw."""

    result = str(record.get("result", "")).strip().lower()
    if result in {"win", "loss", "draw"}:
        return result.capitalize()

    match_score = record.get("match_score", record.get("fitness"))
    if isinstance(match_score, list) and match_score:
        try:
            win_score = float(match_score[0])
        except (TypeError, ValueError):
            return "Unknown"
        if win_score == 1.0:
            return "Win"
        if win_score == 0.0:
            return "Loss"
        return "Draw"

    return "Unknown"


def summarize_final_test_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Build aggregate win/loss statistics from final-test replay output."""

    raw_results = payload.get("results", {})
    summary = {
        "individual_count": len(raw_results),
        "total_matches": 0,
        "overall": {"Win": 0, "Loss": 0, "Draw": 0, "Unknown": 0},
        "by_opponent": {},
        "by_individual": {},
    }

    for individual_id, records in raw_results.items():
        individual_summary = {"Win": 0, "Loss": 0, "Draw": 0, "Unknown": 0, "total": 0}
        for record in records or []:
            result = _normalize_result(record)
            opponent = str(record.get("opponent", "Unknown"))

            summary["total_matches"] += 1
            summary["overall"][result] = summary["overall"].get(result, 0) + 1

            opponent_summary = summary["by_opponent"].setdefault(
                opponent,
                {"Win": 0, "Loss": 0, "Draw": 0, "Unknown": 0, "total": 0},
            )
            opponent_summary[result] = opponent_summary.get(result, 0) + 1
            opponent_summary["total"] += 1

            individual_summary[result] = individual_summary.get(result, 0) + 1
            individual_summary["total"] += 1

        summary["by_individual"][individual_id] = individual_summary

    return summary


def format_final_test_summary(summary: dict[str, Any]) -> str:
    """Render the aggregated final-test statistics into readable text."""

    lines = [
        "Final Test Summary",
        f"Individuals: {summary['individual_count']}",
        f"Matches: {summary['total_matches']}",
        (
            "Overall: "
            f"W={summary['overall']['Win']} "
            f"L={summary['overall']['Loss']} "
            f"D={summary['overall']['Draw']} "
            f"U={summary['overall']['Unknown']}"
        ),
        "",
        "By Opponent",
    ]

    for opponent in sorted(summary["by_opponent"]):
        stats = summary["by_opponent"][opponent]
        lines.append(
            f"- {opponent}: W={stats['Win']} L={stats['Loss']} D={stats['Draw']} U={stats['Unknown']} Total={stats['total']}"
        )

    lines.append("")
    lines.append("By Individual")
    for individual_id in sorted(summary["by_individual"]):
        stats = summary["by_individual"][individual_id]
        lines.append(
            f"- {individual_id}: W={stats['Win']} L={stats['Loss']} D={stats['Draw']} U={stats['Unknown']} Total={stats['total']}"
        )

    return "\n".join(lines)


def load_results_file(results_path: str | Path) -> dict[str, Any]:
    """Load one final-test results JSON file from disk."""

    path = Path(results_path)
    return json.loads(path.read_text(encoding="utf-8"))


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI for final-test result summarization."""

    parser = argparse.ArgumentParser(description="Summarize win/loss counts from final_test_results.json.")
    parser.add_argument("results_path", help="Path to final_test_results.json.")
    return parser


def main() -> None:
    """Parse arguments, summarize the target file, and print the report."""

    parser = build_argument_parser()
    args = parser.parse_args()
    payload = load_results_file(args.results_path)
    summary = summarize_final_test_results(payload)
    print(format_final_test_summary(summary))


if __name__ == "__main__":
    main()
