#!/usr/bin/env python3
"""Plot cross-generation search convergence for the 50-generation comparison."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import statistics


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs/experiments/1108_gpt_vs_local_50x10_seed8_9"
RUNS = {
    "10 GPT initial": {
        8: ROOT / "runs/20261108_144319_755348",
        9: ROOT / "runs/20261109_000650_966551",
    },
    "1 GPT + 9 local": {
        8: ROOT / "runs/20261109_072720_479146",
        9: ROOT / "runs/20261109_150205_472817",
    },
}


def load_run(run_dir: Path, seed: int, treatment: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((run_dir / "generations").glob("generation_*.json")):
        if not re.fullmatch(r"generation_\d{4}\.json", path.name):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        metrics = payload["metrics"]["game_performance"]
        rows.append(
            {
                "treatment": treatment,
                "seed": seed,
                "generation": int(payload["generation"]),
                "best": float(metrics["best"]),
                "population_mean": float(metrics["mean"]),
            }
        )
    return rows


def main() -> None:
    records = [
        record
        for treatment, runs in RUNS.items()
        for seed, run_dir in runs.items()
        for record in load_run(run_dir, seed, treatment)
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "cross_generation_convergence.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    aggregate: list[dict[str, object]] = []
    generations = sorted({int(row["generation"]) for row in records})
    for treatment in RUNS:
        for generation in generations:
            values = [
                float(row["best"])
                for row in records
                if row["treatment"] == treatment and int(row["generation"]) == generation
            ]
            aggregate.append(
                {
                    "treatment": treatment,
                    "generation": generation,
                    "mean_best": statistics.mean(values),
                    "minimum_best": min(values),
                    "maximum_best": max(values),
                }
            )

    colors = {"10 GPT initial": "#2563eb", "1 GPT + 9 local": "#dc2626"}
    fig, axis = plt.subplots(figsize=(11, 6), constrained_layout=True)
    for treatment in RUNS:
        rows = [row for row in aggregate if row["treatment"] == treatment]
        x = [int(row["generation"]) for row in rows]
        mean = [float(row["mean_best"]) for row in rows]
        minimum = [float(row["minimum_best"]) for row in rows]
        maximum = [float(row["maximum_best"]) for row in rows]
        color = colors[treatment]
        axis.plot(x, mean, linewidth=2.5, color=color, label=f"{treatment} mean")
        axis.fill_between(x, minimum, maximum, color=color, alpha=0.16, label=f"{treatment} min–max")

    axis.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
    axis.set_title("50-generation cross-generation convergence")
    axis.set_xlabel("Generation")
    axis.set_ylabel("Search game performance (best candidate)")
    axis.grid(alpha=0.2)
    axis.legend(ncol=2, fontsize=9)
    fig.savefig(OUT / "cross_generation_convergence.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
