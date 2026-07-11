"""Plot EAGLE candidate game performance by generation.

Usage example:
    python scripts/analysis/plot_game_performance_by_generation.py --run-dir runs/20260707_015207_331307
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from matplotlib import pyplot as plt

from scripts.analyze_run import read_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot EAGLE game performance by generation.")
    parser.add_argument("--run-dir", required=True, help="Path to an EAGLE run directory.")
    parser.add_argument(
        "--output",
        default=None,
        help="Output image path. Default: <run-dir>/analysis/game_performance_by_generation.png",
    )
    parser.add_argument("--show", action="store_true", help="Show the plot window after saving.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory does not exist: {run_dir}", file=sys.stderr)
        return 2

    output_path = Path(args.output) if args.output else run_dir / "analysis" / "game_performance_by_generation.png"
    records = read_candidate_records(run_dir)
    mean_records = generation_means(records)
    write_csv(csv_path_for(output_path), records)
    write_mean_csv(mean_csv_path_for(output_path), mean_records)
    write_plot(output_path, run_dir, records, mean_records, show=args.show)

    print(f"records={len(records)}")
    print(f"csv={csv_path_for(output_path)}")
    print(f"mean_csv={mean_csv_path_for(output_path)}")
    print(f"plot={output_path}")
    return 0


def read_candidate_records(run_dir: Path) -> list[dict[str, Any]]:
    records = read_results_jsonl_records(run_dir)
    if records:
        return records
    return read_individual_records(run_dir)


def read_results_jsonl_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            candidate = payload.get("candidate") or {}
            records.append(record_from_candidate(candidate))
    return sorted_records(records)


def read_individual_records(run_dir: Path) -> list[dict[str, Any]]:
    records = [
        record_from_candidate(read_json(path))
        for path in sorted((run_dir / "candidates").glob("*/individual.json"))
    ]
    return sorted_records(records)


def record_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    objectives = candidate.get("fitness_objectives") or {}
    return {
        "generation": int(candidate.get("generation", 0)),
        "candidate_id": str(candidate.get("id", "")),
        "game_performance": float_or_nan(objectives.get("game_performance")),
    }


def sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: (record["generation"], record["candidate_id"]))


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["generation", "candidate_id", "game_performance"])
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "generation": record["generation"],
                    "candidate_id": record["candidate_id"],
                    "game_performance": csv_float(record["game_performance"]),
                }
            )


def generation_means(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values_by_generation: dict[int, list[float]] = {}
    for record in records:
        score = record["game_performance"]
        if math.isnan(score):
            continue
        values_by_generation.setdefault(record["generation"], []).append(score)

    return [
        {
            "generation": generation,
            "mean_game_performance": sum(values) / len(values),
            "count": len(values),
        }
        for generation, values in sorted(values_by_generation.items())
    ]


def write_mean_csv(path: Path, mean_records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["generation", "mean_game_performance", "count"])
        writer.writeheader()
        for record in mean_records:
            writer.writerow(record)


def write_plot(
    output_path: Path,
    run_dir: Path,
    records: list[dict[str, Any]],
    mean_records: list[dict[str, Any]],
    *,
    show: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    valid = [record for record in records if not math.isnan(record["game_performance"])]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.scatter(
        [record["generation"] + jitter(record["candidate_id"], scale=0.16) for record in valid],
        [record["game_performance"] + jitter(f"{record['candidate_id']}:y", scale=0.8) for record in valid],
        alpha=0.5,
        s=14,
        label="Candidates",
    )
    if mean_records:
        ax.plot(
            [record["generation"] for record in mean_records],
            [record["mean_game_performance"] for record in mean_records],
            marker="o",
            linewidth=2.5,
            markersize=5,
            label="Generation mean",
        )
    ax.axhline(0, color="black", linewidth=1, alpha=0.6)
    ax.set_title(f"Candidate game performance and generation mean: {run_dir.name}")
    ax.set_xlabel("Generation")
    ax.set_ylabel("Game performance")
    ax.legend()
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    if show:
        plt.show()
    plt.close(fig)


def csv_path_for(output_path: Path) -> Path:
    return output_path.with_suffix(".csv")


def mean_csv_path_for(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}_mean.csv")


def jitter(value: str, *, scale: float) -> float:
    # Stable jitter keeps overlapping points visible without affecting mean calculations.
    bucket = sum(ord(char) for char in value) % 1000
    return ((bucket / 999.0) - 0.5) * scale


def float_or_nan(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def csv_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
