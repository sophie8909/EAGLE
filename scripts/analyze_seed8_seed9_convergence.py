#!/usr/bin/env python3
"""Create a comparable seed-8/seed-9 convergence report and plot."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    "seed 8": ROOT / "runs/20261105_153135_880565",
    "seed 9": ROOT / "runs/20261106_072846_805117",
}
OUT = ROOT / "reports/seed8_seed9_convergence"


def load_search(run_dir: Path) -> dict[int, dict[str, float]]:
    with (run_dir / "analysis/generation_metrics.csv").open(newline="") as handle:
        return {
            int(row["generation"]): {
                "best": float(row["game_performance_best"]),
                "mean": float(row["game_performance_mean"]),
                "worst": float(row["game_performance_worst"]),
                "semantic_distance": float(row["semantic_distance_mean"]),
            }
            for row in csv.DictReader(handle)
        }


def load_fixed(run_dir: Path) -> dict[int, float]:
    path = run_dir / "fixed_evaluation/fixed_evaluation_summary.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[int, float] = {}
    for row in payload.get("rows", []):
        score = row.get("mean_match_score")
        if score is not None:
            result[int(row["generation"])] = float(score)
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    combined: list[dict[str, object]] = []
    for label, run_dir in RUNS.items():
        search = load_search(run_dir)
        fixed = load_fixed(run_dir)
        for generation, values in sorted(search.items()):
            combined.append(
                {
                    "seed": label,
                    "generation": generation,
                    **values,
                    "fixed_mean_match_score": fixed.get(generation),
                }
            )

    with (OUT / "convergence.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=combined[0].keys())
        writer.writeheader()
        writer.writerows(combined)

    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True, constrained_layout=True)
    colors = {"seed 8": "#2563eb", "seed 9": "#dc2626"}
    for label in RUNS:
        rows = [row for row in combined if row["seed"] == label]
        x = [int(row["generation"]) for row in rows]
        color = colors[label]
        axes[0].plot(x, [row["best"] for row in rows], color=color, alpha=0.35, linewidth=1)
        axes[0].plot(x, [row["mean"] for row in rows], color=color, linewidth=2, label=f"{label} search mean")
        axes[0].fill_between(
            x,
            [row["worst"] for row in rows],
            [row["best"] for row in rows],
            color=color,
            alpha=0.08,
            label=f"{label} population range",
        )
        fixed = [(int(row["generation"]), row["fixed_mean_match_score"]) for row in rows if row["fixed_mean_match_score"] is not None]
        if fixed:
            axes[1].plot(*zip(*fixed), marker="o", color=color, linewidth=2, label=label)

    axes[0].axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
    axes[0].set_title("Seed 8/9 search-time trajectory (self-play context changes every 5 generations)")
    axes[0].set_ylabel("Game Performance")
    axes[0].legend(ncol=2, fontsize=8)
    axes[0].grid(alpha=0.2)
    axes[1].axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
    axes[1].set_title("Frozen cross-generation evaluation (comparable benchmark)")
    axes[1].set_xlabel("Generation")
    axes[1].set_ylabel("Mean match score")
    axes[1].legend()
    axes[1].grid(alpha=0.2)
    fig.savefig(OUT / "seed8_seed9_convergence.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
