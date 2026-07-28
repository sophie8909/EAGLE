"""Static CSV, JSON, Markdown, and Matplotlib analysis outputs."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .loader import RunData


OUTPUT_FILES = (
    "summary.md", "run_summary.json", "generation_metrics.csv",
    "candidate_summary.csv", "objective_statistics.csv", "operator_statistics.csv",
    "timing_statistics.csv", "error_statistics.csv",
)


def generate_analysis(data: RunData, *, output_name: str = "analysis", force: bool = False) -> Path:
    output = data.run_dir / output_name
    output.mkdir(parents=True, exist_ok=True)
    plots = output / "plots"
    plots.mkdir(exist_ok=True)
    candidates = _candidate_rows(data)
    objective_rows = _objective_rows(data)
    generation_rows = _generation_rows(data)
    operator_rows = _operator_rows(candidates)
    timing_rows = _timing_rows(data.timing)
    error_rows = _error_rows(data.errors, candidates)
    _write_csv(output / "generation_metrics.csv", generation_rows)
    _write_csv(output / "candidate_summary.csv", candidates)
    _write_csv(output / "objective_statistics.csv", objective_rows)
    _write_csv(output / "operator_statistics.csv", operator_rows)
    _write_csv(output / "timing_statistics.csv", timing_rows)
    _write_csv(output / "error_statistics.csv", error_rows)
    summary = {
        "schema_version": "eagle-analysis-v1",
        "run_dir": str(data.run_dir),
        "status": data.manifest.get("status"),
        "completed_generations": data.manifest.get("completed_generations", []),
        "candidate_count": len(candidates),
        "failure_count": sum(bool(row["failed"]) for row in candidates),
        "objectives": sorted({row["objective_id"] for row in objective_rows}),
    }
    (output / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(
        "# EAGLE Run Analysis\n\n"
        f"- Run: `{data.run_dir}`\n"
        f"- Status: {summary['status']}\n"
        f"- Completed generations: {len(summary['completed_generations'])}\n"
        f"- Final candidates: {summary['candidate_count']}\n"
        f"- Failures: {summary['failure_count']}\n",
        encoding="utf-8",
    )
    _plots(plots, generation_rows, objective_rows, operator_rows, timing_rows, error_rows, candidates)
    return output


def _generation_rows(data: RunData) -> list[dict[str, Any]]:
    rows = []
    for item in data.generation_metrics:
        base = {
            "generation": item.get("generation"),
            "population_size": item.get("population_size"),
            "failure_count": item.get("failure_count"),
            "pareto_front_size": item.get("pareto_front_size"),
        }
        for objective_id, values in item.get("objectives", {}).items():
            for metric in ("best", "mean", "median", "worst"):
                base[f"{objective_id}_{metric}"] = values.get(metric)
        rows.append(base)
    return rows


def _candidate_rows(data: RunData) -> list[dict[str, Any]]:
    population = (data.final_population or {}).get("population", [])
    return [
        {
            "candidate_id": item.get("candidate_id") or item.get("id"),
            "generation": item.get("generation"),
            "operator": item.get("operator"),
            "mutation_type": item.get("mutation_type"),
            "status": item.get("status"),
            "failed": bool(item.get("failure_reason")) or item.get("status") == "failed",
            **{str(key): value for key, value in item.get("fitness_objectives", {}).items()},
        }
        for item in population if isinstance(item, dict)
    ]


def _objective_rows(data: RunData) -> list[dict[str, Any]]:
    return [
        {"generation": item.get("generation"), **values}
        for item in data.generation_metrics
        for values in item.get("objectives", {}).values()
    ]


def _operator_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[str(item.get("operator") or "unknown")].append(item)
    return [
        {
            "operator": operator,
            "usage_count": len(items),
            "success_count": sum(not bool(item["failed"]) for item in items),
            "success_rate": sum(not bool(item["failed"]) for item in items) / len(items),
        }
        for operator, items in sorted(grouped.items())
    ]


def _timing_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[float]] = defaultdict(list)
    for item in records:
        duration = item.get("duration_seconds")
        if isinstance(duration, (int, float)):
            grouped[(item.get("generation"), item.get("operation") or item.get("stage") or item.get("event"))].append(float(duration))
    return [
        {"generation": generation, "operation": operation, "count": len(values), "total_seconds": sum(values), "mean_seconds": sum(values) / len(values)}
        for (generation, operation), values in sorted(grouped.items(), key=lambda value: str(value[0]))
    ]


def _error_rows(errors: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(
        (item.get("generation"), item.get("stage") or item.get("failure_stage") or "unknown")
        for item in errors
    )
    for item in candidates:
        if item["failed"]:
            counts[(item.get("generation"), "candidate")] += 1
    return [{"generation": generation, "stage": stage, "count": count} for (generation, stage), count in sorted(counts.items(), key=str)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["no_data"])
        writer.writeheader()
        writer.writerows(rows)


def _plots(path: Path, generation_rows, objective_rows, operator_rows, timing_rows, error_rows, candidates) -> None:
    for objective in sorted({row.get("objective_id") for row in objective_rows if row.get("objective_id")}):
        rows = [row for row in objective_rows if row.get("objective_id") == objective]
        _line_plot(path / f"{objective}_by_generation.png", rows, "generation", ("best", "mean", "median", "worst"), objective)
    _line_plot(path / "population_failures.png", generation_rows, "generation", ("population_size", "failure_count"), "Population and failures")
    _line_plot(path / "pareto_front_size.png", generation_rows, "generation", ("pareto_front_size",), "Pareto-front size")
    _bar_plot(path / "operator_usage.png", operator_rows, "operator", "usage_count", "Operator usage")
    _bar_plot(path / "operator_success_rate.png", operator_rows, "operator", "success_rate", "Operator success rate")
    _bar_plot(path / "errors_by_stage.png", error_rows, "stage", "count", "Errors by stage")
    _line_plot(path / "timing_by_generation.png", timing_rows, "generation", ("total_seconds",), "Timing by generation")
    _bar_plot(path / "timing_by_operation.png", timing_rows, "operation", "total_seconds", "Timing by operation")
    _line_plot(path / "errors_by_generation.png", error_rows, "generation", ("count",), "Errors by generation")

    if len(candidates) > 1 and {"game_performance", "code_quality"} <= set(candidates[0]):
        plt.figure()
        plt.scatter([row.get("game_performance") for row in candidates], [row.get("code_quality") for row in candidates])
        plt.xlabel("game_performance"); plt.ylabel("code_quality"); plt.tight_layout()
        plt.savefig(path / "final_pareto_front.png"); plt.close()
    elif candidates:
        objective = next((key for key in candidates[0] if key not in {"candidate_id", "generation", "operator", "mutation_type", "status", "failed"}), None)
        if objective:
            ranked = sorted(candidates, key=lambda row: row.get(objective, float("-inf")), reverse=True)
            _bar_plot(path / "final_ranking.png", ranked, "candidate_id", objective, "Final ranking")


def _line_plot(path: Path, rows, x, ys, title) -> None:
    if not rows:
        return
    plt.figure()
    for y in ys:
        points = [(row.get(x), row.get(y)) for row in rows if row.get(x) is not None and row.get(y) is not None]
        if points:
            plt.plot([item[0] for item in points], [item[1] for item in points], marker="o", label=y)
    plt.title(title); plt.legend(); plt.tight_layout(); plt.savefig(path); plt.close()


def _bar_plot(path: Path, rows, x, y, title) -> None:
    points = [(str(row.get(x)), row.get(y)) for row in rows if row.get(y) is not None]
    if not points:
        return
    plt.figure(); plt.bar([item[0] for item in points], [item[1] for item in points])
    plt.title(title); plt.xticks(rotation=30, ha="right"); plt.tight_layout(); plt.savefig(path); plt.close()
