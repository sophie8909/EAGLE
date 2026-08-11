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
    "candidate_summary.csv", "agent_game_performance.csv", "strategy_diversity.csv", "strategy_niches.csv",
    "objective_statistics.csv", "operator_statistics.csv",
    "timing_statistics.csv", "error_statistics.csv",
)


def generate_analysis(data: RunData, *, output_name: str = "analysis", force: bool = False) -> Path:
    output = data.run_dir / output_name
    output.mkdir(parents=True, exist_ok=True)
    plots = output / "plots"
    plots.mkdir(exist_ok=True)
    candidates = _candidate_rows(data)
    agent_game_rows = _agent_game_performance_rows(data)
    diversity_rows = _strategy_diversity_rows(data)
    niche_rows = _strategy_niche_rows(data)
    objective_rows = _objective_rows(data)
    generation_rows = _generation_rows(data)
    operator_rows = _operator_rows(candidates)
    timing_rows = _timing_rows(data.timing)
    error_rows = _error_rows(data.errors, candidates)
    _write_csv(output / "generation_metrics.csv", generation_rows)
    _write_csv(output / "candidate_summary.csv", candidates)
    _write_csv(output / "agent_game_performance.csv", agent_game_rows)
    _write_csv(output / "strategy_diversity.csv", diversity_rows)
    _write_csv(output / "strategy_niches.csv", niche_rows)
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
        "agent_game_performance_count": len(agent_game_rows),
        "strategy_diversity_count": len(diversity_rows),
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
        f"- Individual agent Game Performance rows: {summary['agent_game_performance_count']}\n"
        f"- Failures: {summary['failure_count']}\n",
        encoding="utf-8",
    )
    _plots(plots, generation_rows, objective_rows, operator_rows, timing_rows, error_rows, candidates, agent_game_rows, diversity_rows)
    return output


def _generation_rows(data: RunData) -> list[dict[str, Any]]:
    rows = []
    for item in data.generation_metrics:
        base = {
            "generation": item.get("generation"),
            "population_size": item.get("population_size"),
            "failure_count": item.get("failure_count"),
            "pareto_front_size": item.get("pareto_front_size"),
            "expected_match_count": item.get("expected_match_count"),
            "completed_match_count": item.get("completed_match_count"),
            "evaluation_maps": json.dumps(item.get("evaluation_maps") or [], ensure_ascii=False),
            "rounds_per_map": item.get("rounds_per_map"),
            "swap_player_sides": item.get("swap_player_sides"),
        }
        diversity = item.get("strategy_diversity") or {}
        if isinstance(diversity, dict):
            base.update({
                "unique_niches": diversity.get("unique_niches"),
                "dominant_niche": diversity.get("dominant_niche", "unknown"),
                "dominant_niche_ratio": diversity.get("dominant_niche_ratio"),
                "mean_strategy_distance": diversity.get("mean_strategy_distance"),
                "new_niches": diversity.get("new_niches"),
                "revisited_niches": diversity.get("revisited_niches"),
                "niche_change_rate": diversity.get("niche_change_rate"),
            })
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
            "strategy_niche": item.get("strategy_niche", "unknown"),
            "mutation_intent": item.get("mutation_intent"),
            "parent_strategy_niche": item.get("parent_strategy_niche"),
            "niche_changed": item.get("niche_changed"),
            "status": item.get("status"),
            "failed": bool(item.get("failure_reason")) or item.get("status") == "failed",
            **{str(key): value for key, value in item.get("fitness_objectives", {}).items()},
        }
        for item in population if isinstance(item, dict)
    ]


def _strategy_diversity_rows(data: RunData) -> list[dict[str, Any]]:
    """Flatten optional generation diversity metadata for legacy-safe CSV output."""

    rows: list[dict[str, Any]] = []
    for item in data.generation_metrics:
        diversity = item.get("strategy_diversity") or {}
        if not isinstance(diversity, dict):
            diversity = {}
        intent_rates = diversity.get("intent_niche_change_rates") or {}
        if not isinstance(intent_rates, dict):
            intent_rates = {}
        rows.append({
            "generation": item.get("generation"),
            "unique_niches": diversity.get("unique_niches", 0),
            "dominant_niche": diversity.get("dominant_niche", "unknown"),
            "dominant_niche_count": diversity.get("dominant_niche_count", 0),
            "dominant_niche_ratio": diversity.get("dominant_niche_ratio", 0.0),
            "mean_strategy_distance": diversity.get("mean_strategy_distance", 0.0),
            "new_niches": diversity.get("new_niches", 0),
            "revisited_niches": diversity.get("revisited_niches", 0),
            "niche_change_rate": diversity.get("niche_change_rate"),
            "known_signature_count": diversity.get("known_signature_count", 0),
            "unknown_signature_count": diversity.get("unknown_signature_count", 0),
            **{f"{intent.lower()}_niche_change_rate": intent_rates.get(intent) for intent in ("REFINE", "COUNTER", "STRUCTURAL", "ALTERNATIVE")},
        })
    return rows


def _strategy_niche_rows(data: RunData) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in data.generation_metrics:
        generation = item.get("generation")
        diversity = item.get("strategy_diversity") or {}
        distribution = diversity.get("niche_distribution") if isinstance(diversity, dict) else {}
        if not isinstance(distribution, dict):
            continue
        total = sum(int(value) for value in distribution.values() if isinstance(value, (int, float)))
        for niche, count in sorted(distribution.items()):
            numeric_count = int(count)
            rows.append({
                "generation": generation,
                "strategy_niche": niche,
                "candidate_count": numeric_count,
                "population_ratio": numeric_count / total if total else 0.0,
            })
    return rows


def _agent_game_performance_rows(data: RunData) -> list[dict[str, Any]]:
    """Return one Game Performance row for every agent in each population snapshot."""

    snapshots = data.generations
    if not snapshots and data.final_population:
        snapshots = [data.final_population]
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_generation = snapshot.get("generation")
        population = snapshot.get("population", [])
        if not isinstance(population, list):
            continue
        for item in population:
            if not isinstance(item, dict):
                continue
            objectives = item.get("fitness_objectives") or item.get("objectives") or {}
            if not isinstance(objectives, dict):
                objectives = {}
            rows.append({
                "generation": item.get("generation", snapshot_generation),
                "candidate_id": item.get("candidate_id") or item.get("id"),
                "status": item.get("status"),
                "operator": item.get("operator"),
                "mutation_type": item.get("mutation_type"),
                "game_performance": objectives.get("game_performance"),
                "code_quality": objectives.get("code_quality"),
                "failed": bool(item.get("failure_reason")) or item.get("status") == "failed",
            })
    return sorted(rows, key=lambda item: (item.get("generation", -1), str(item.get("candidate_id") or "")))


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


def _plots(path: Path, generation_rows, objective_rows, operator_rows, timing_rows, error_rows, candidates, agent_game_rows, diversity_rows) -> None:
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
    _agent_game_performance_plot(path / "agent_game_performance.png", agent_game_rows)
    _line_plot(path / "unique_strategy_niches.png", diversity_rows, "generation", ("unique_niches",), "Unique strategy niches")
    _line_plot(path / "dominant_niche_ratio.png", diversity_rows, "generation", ("dominant_niche_ratio",), "Dominant niche ratio")
    _line_plot(path / "mean_strategy_distance.png", diversity_rows, "generation", ("mean_strategy_distance",), "Mean strategy distance")
    _line_plot(
        path / "niche_change_by_mutation_intent.png",
        diversity_rows,
        "generation",
        ("refine_niche_change_rate", "counter_niche_change_rate", "structural_niche_change_rate", "alternative_niche_change_rate"),
        "Niche change by mutation intent",
    )

    if len(candidates) > 1 and {"game_performance", "code_quality"} <= set(candidates[0]):
        plt.figure()
        plt.scatter([row.get("game_performance") for row in candidates], [row.get("code_quality") for row in candidates])
        plt.xlabel("Code Quality / Simplicity (higher is better)")
        plt.ylabel("Game Performance (higher is better)")
        plt.tight_layout()
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
    plt.title(title)
    if plt.gca().get_legend_handles_labels()[0]:
        plt.legend()
    plt.tight_layout(); plt.savefig(path); plt.close()


def _bar_plot(path: Path, rows, x, y, title) -> None:
    points = [(str(row.get(x)), row.get(y)) for row in rows if row.get(y) is not None]
    if not points:
        return
    plt.figure(); plt.bar([item[0] for item in points], [item[1] for item in points])
    plt.title(title); plt.xticks(rotation=30, ha="right"); plt.tight_layout(); plt.savefig(path); plt.close()


def _agent_game_performance_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    points = [
        item for item in rows
        if item.get("generation") is not None
        and item.get("game_performance") is not None
        and not item.get("failed")
    ]
    if not points:
        return
    plt.figure(figsize=(10, 5))
    plt.scatter(
        [item["generation"] for item in points],
        [item["game_performance"] for item in points],
        s=18,
        alpha=0.65,
    )
    plt.xlabel("Generation")
    plt.ylabel("Game Performance")
    plt.title("Individual agent Game Performance")
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
