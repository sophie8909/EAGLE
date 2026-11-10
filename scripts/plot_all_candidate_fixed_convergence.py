#!/usr/bin/env python3
"""Aggregate all-candidate fixed evaluations into a five-statistic comparison plot."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = {
    "10 GPT initial": {
        8: ROOT / "runs/20261108_144319_755348",
        9: ROOT / "runs/20261109_000650_966551",
    },
    "1 GPT + 9 local": {
        8: ROOT / "runs/20261109_072720_479146",
        9: ROOT / "runs/20261109_150205_472817",
    },
}
COLORS = {"10 GPT initial": "#2563eb", "1 GPT + 9 local": "#dc2626"}


def load_rows(run_dir: Path, evaluation_dir_name: str) -> list[dict[str, object]]:
    path = run_dir / evaluation_dir_name / "fixed_evaluation_results.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing all-candidate results: {path}. Run fixed_evaluation with --all-candidates first."
        )
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or any(row.get("selection_mode") != "all_runnable_candidates" for row in rows):
        raise ValueError(f"{path} is not an all-candidate fixed-evaluation result.")
    return [
        {
            "generation": int(row["generation"]),
            "candidate_id": row["candidate_id"],
            "mean_match_score": float(row["mean_match_score"]),
        }
        for row in rows
        if row.get("status") == "complete" and row.get("mean_match_score") not in (None, "")
    ]


def aggregate(records: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int, int], list[float]] = defaultdict(list)
    for record in records:
        grouped[
            (str(record["treatment"]), int(record["seed"]), int(record["generation"]))
        ].append(float(record["mean_match_score"]))
    treatments = sorted({str(record["treatment"]) for record in records})
    generations = sorted({int(record["generation"]) for record in records})
    output: list[dict[str, object]] = []
    for treatment in treatments:
        seeds = sorted({int(record["seed"]) for record in records if record["treatment"] == treatment})
        for generation in generations:
            per_seed = {
                seed: grouped[(treatment, seed, generation)]
                for seed in seeds
                if grouped[(treatment, seed, generation)]
            }
            if len(per_seed) != len(seeds):
                continue
            seed_means = {seed: statistics.fmean(values) for seed, values in per_seed.items()}
            seed_best = {seed: max(values) for seed, values in per_seed.items()}
            seed_worst = {seed: min(values) for seed, values in per_seed.items()}
            output.append({
                "treatment": treatment,
                "generation": generation,
                "all_individuals_mean": statistics.fmean(value for values in per_seed.values() for value in values),
                "mean_of_seed_best": statistics.fmean(seed_best.values()),
                "mean_of_seed_worst": statistics.fmean(seed_worst.values()),
                "best_seed_mean": max(seed_means.values()),
                "worst_seed_mean": min(seed_means.values()),
            })
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/all_candidate_fixed_convergence")
    parser.add_argument("--evaluation-dir-name", default="fixed_evaluation_all")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    records: list[dict[str, object]] = []
    for treatment, runs in DEFAULT_RUNS.items():
        for seed, run_dir in runs.items():
            records.extend(
                {"treatment": treatment, "seed": seed, **row}
                for row in load_rows(run_dir, args.evaluation_dir_name)
            )
    aggregate_rows = aggregate(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "all_candidate_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    with (args.output_dir / "five_statistic_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=aggregate_rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(aggregate_rows)

    fig, axis = plt.subplots(figsize=(12, 6.5), constrained_layout=True)
    for treatment in DEFAULT_RUNS:
        rows = [row for row in aggregate_rows if row["treatment"] == treatment]
        color = COLORS[treatment]
        x = [int(row["generation"]) for row in rows]
        all_mean = [float(row["all_individuals_mean"]) for row in rows]
        seed_best = [float(row["mean_of_seed_best"]) for row in rows]
        seed_worst = [float(row["mean_of_seed_worst"]) for row in rows]
        best_seed = [float(row["best_seed_mean"]) for row in rows]
        worst_seed = [float(row["worst_seed_mean"]) for row in rows]
        axis.fill_between(x, worst_seed, best_seed, color=color, alpha=0.16,
                          label=f"{treatment}: best–worst seed mean")
        axis.plot(x, best_seed, color=color, linewidth=1.4, alpha=0.65)
        axis.plot(x, worst_seed, color=color, linewidth=1.4, alpha=0.65)
        axis.plot(x, all_mean, color=color, linewidth=2.8,
                  label=f"{treatment}: all individuals mean")
        axis.plot(x, seed_best, color=color, linestyle="--", linewidth=1.8,
                  label=f"{treatment}: mean of seed-best")
        axis.plot(x, seed_worst, color=color, linestyle=":", linewidth=1.8,
                  label=f"{treatment}: mean of seed-worst")
    axis.axhline(0, color="#6b7280", linewidth=0.8, linestyle="--")
    axis.set_title("All-individual fixed-opponent convergence every five generations")
    axis.set_xlabel("Generation")
    axis.set_ylabel("Frozen mean match score")
    axis.grid(alpha=0.2)
    axis.legend(ncol=2, fontsize=8)
    fig.savefig(args.output_dir / "five_statistic_convergence.png", dpi=180)
    plt.close(fig)
    if args.report_path is not None:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(
            "# 1113 全體個體固定對手收斂比較\n\n"
            "每 5 代評估每個 seed 的全部 runnable individuals；兩種初始化方法使用固定 opponents、maps、tick limits 與 paired seed stream。\n\n"
            "![五統計收斂圖](all_candidate_fixed_convergence/five_statistic_convergence.png)\n\n"
            "原始個體結果：[all_candidate_results.csv](all_candidate_fixed_convergence/all_candidate_results.csv)\n\n"
            "彙總統計：[five_statistic_summary.csv](all_candidate_fixed_convergence/five_statistic_summary.csv)\n\n"
            "圖中實線是所有個體平均；虛線是各 seed 最佳／最差個體的平均；色塊範圍是最佳 seed 平均到最差 seed 平均。\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
