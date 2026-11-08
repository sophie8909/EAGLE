#!/usr/bin/env python3
"""Compare all-GPT initialization with the 1-GPT+9-local baseline."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    8: {
        "10 GPT initial": ROOT / "runs/20261105_153135_880565",
        "1 GPT + 9 local": ROOT / "runs/20261101_211038_286628",
    },
    9: {
        "10 GPT initial": ROOT / "runs/20261106_072846_805117",
        "1 GPT + 9 local": ROOT / "runs/20261102_131719_965893",
    },
    10: {
        "10 GPT initial": ROOT / "runs/20261107_135945_086651",
        "1 GPT + 9 local": ROOT / "runs/20261103_043534_423377",
    },
}
OUT = ROOT / "reports/all_gpt_vs_one_gpt_convergence"


def load_fixed(run_dir: Path) -> list[dict[str, float | int]]:
    payload = json.loads(
        (run_dir / "fixed_evaluation/fixed_evaluation_summary.json").read_text(
            encoding="utf-8"
        )
    )
    return [
        {
            "generation": int(row["generation"]),
            "mean_match_score": float(row["mean_match_score"]),
            "win_rate": float(row["win_rate"]),
        }
        for row in payload["rows"]
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for seed, treatments in RUNS.items():
        for treatment, run_dir in treatments.items():
            for row in load_fixed(run_dir):
                records.append({"seed": seed, "treatment": treatment, **row})

    with (OUT / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    colors = {"10 GPT initial": "#2563eb", "1 GPT + 9 local": "#dc2626"}
    fig, axes = plt.subplots(1, 3, figsize=(19, 5.5), sharey=True, constrained_layout=True)
    for axis, (seed, treatments) in zip(axes, RUNS.items()):
        for treatment, run_dir in treatments.items():
            rows = load_fixed(run_dir)
            x = [int(row["generation"]) for row in rows]
            y = [float(row["mean_match_score"]) for row in rows]
            axis.plot(x, y, marker="o", linewidth=2, markersize=4, color=colors[treatment], label=treatment)
        axis.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
        axis.set_title(f"Seed {seed}")
        axis.set_xlabel("Generation")
        axis.grid(alpha=0.2)
    axes[0].set_ylabel("Frozen mean match score")
    axes[0].legend(fontsize=9)
    fig.suptitle("Cross-generation convergence: 10 GPT initial vs 1 GPT + 9 local")
    fig.savefig(OUT / "all_gpt_vs_one_gpt_convergence.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
