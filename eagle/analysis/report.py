"""Static CSV, JSON, Markdown, and Matplotlib analysis outputs."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from .loader import RunData


OUTPUT_FILES = (
    "summary.md", "run_summary.json", "generation_metrics.csv",
    "candidate_summary.csv", "agent_game_performance.csv", "agent_win_rate.csv",
    "match_game_performance.csv", "opponent_game_performance.csv",
    "aos_operator_statistics.csv",
    "strategy_diversity.csv", "strategy_niches.csv",
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
    agent_win_rate_rows = _agent_win_rate_rows(data)
    match_game_rows = _match_game_performance_rows(data)
    diversity_rows = _strategy_diversity_rows(data)
    niche_rows = _strategy_niche_rows(data)
    objective_rows = _objective_rows(data)
    generation_rows = _generation_rows(data)
    operator_rows = _operator_rows(candidates)
    timing_rows = _timing_rows(data.timing)
    error_rows = _error_rows(data.errors, candidates)
    opponent_game_rows = _opponent_game_performance_rows(data)
    aos_rows = _aos_rows(data)
    _write_csv(output / "generation_metrics.csv", generation_rows)
    _write_csv(output / "candidate_summary.csv", candidates)
    _write_csv(output / "agent_game_performance.csv", agent_game_rows)
    _write_csv(output / "agent_win_rate.csv", agent_win_rate_rows)
    _write_csv(output / "match_game_performance.csv", match_game_rows)
    _write_csv(output / "opponent_game_performance.csv", opponent_game_rows)
    _write_csv(output / "aos_operator_statistics.csv", aos_rows)
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
        "agent_win_rate_count": len(agent_win_rate_rows),
        "match_game_performance_count": len(match_game_rows),
        "opponent_game_performance_count": len(opponent_game_rows),
        "aos_operator_statistics_count": len(aos_rows),
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
        f"- Individual agent win-rate rows: {summary['agent_win_rate_count']}\n"
        f"- Single-match Game Performance rows: {summary['match_game_performance_count']}\n"
        f"- Per-opponent Game Performance rows: {summary['opponent_game_performance_count']}\n"
        f"- AOS operator statistics rows: {summary['aos_operator_statistics_count']}\n"
        f"- Failures: {summary['failure_count']}\n",
        encoding="utf-8",
    )
    _plots(plots, generation_rows, candidates, agent_game_rows, opponent_game_rows, match_game_rows, agent_win_rate_rows, aos_rows)
    return output


def _generation_rows(data: RunData) -> list[dict[str, Any]]:
    rows = []
    for item in data.generation_metrics:
        base = {
            "generation": item.get("generation"),
            "population_size": item.get("population_size"),
            "light_rush_win_rate": item.get("light_rush_win_rate"),
            "heavy_rush_win_rate": item.get("heavy_rush_win_rate"),
            "failure_count": item.get("failure_count"),
            "expected_match_count": item.get("expected_match_count"),
            "completed_match_count": item.get("completed_match_count"),
            "evaluation_maps": json.dumps(item.get("evaluation_maps") or [], ensure_ascii=False),
            "rounds_per_map": item.get("rounds_per_map"),
            "swap_player_sides": item.get("swap_player_sides"),
        }
        aggregate = item.get("game_performance") or {}
        quality = item.get("code_quality_diagnostic") or {}
        base.update({
            "game_performance_best": aggregate.get("best"),
            "game_performance_mean": aggregate.get("mean"),
            "game_performance_median": aggregate.get("median"),
            "game_performance_worst": aggregate.get("worst"),
            "code_quality_best": quality.get("best"),
            "code_quality_mean": quality.get("mean"),
            "code_quality_median": quality.get("median"),
            "code_quality_worst": quality.get("worst"),
        })
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
            "game_performance": (item.get("game_eval_result") or {}).get("game_performance"),
            "code_quality": (item.get("code_quality_result") or {}).get("code_quality"),
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
            game = item.get("game_eval_result") or {}
            diagnostics = item.get("code_quality_result") or {}
            if not isinstance(objectives, dict):
                objectives = {}
            rows.append({
                "generation": item.get("generation", snapshot_generation),
                "candidate_id": item.get("candidate_id") or item.get("id"),
                "status": item.get("status"),
                "operator": item.get("operator"),
                "mutation_type": item.get("mutation_type"),
                "game_performance": game.get("game_performance", objectives.get("game_performance")),
                "win_rate": game.get("win_rate"),
                "code_quality": diagnostics.get("code_quality", objectives.get("code_quality")),
                "failed": bool(item.get("failure_reason")) or item.get("status") == "failed",
            })
    return sorted(rows, key=lambda item: (item.get("generation", -1), str(item.get("candidate_id") or "")))


def _agent_win_rate_rows(data: RunData) -> list[dict[str, Any]]:
    """Return one win-rate row per agent, generation, and opponent."""

    snapshots = data.generations
    if not snapshots and data.final_population:
        snapshots = [data.final_population]
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        snapshot_generation = snapshot.get("generation")
        population = snapshot.get("population", [])
        if not isinstance(population, list):
            continue
        for candidate in population:
            if not isinstance(candidate, dict):
                continue
            game = candidate.get("game_eval_result") or {}
            for opponent in game.get("opponent_results") or []:
                if not isinstance(opponent, dict):
                    continue
                expected = opponent.get("expected_match_count")
                if expected is None:
                    expected = opponent.get("match_count")
                if expected is None:
                    expected = len(opponent.get("match_scores") or [])
                completed = opponent.get("completed_match_count")
                missing = opponent.get("missing_match_count", 0)
                complete = bool(expected) and (completed is None or completed >= expected) and not missing
                wins = int(opponent.get("wins") or 0)
                rows.append({
                    "generation": candidate.get("generation", snapshot_generation),
                    "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
                    "opponent_id": str(opponent.get("opponent_id") or "unknown"),
                    "status": candidate.get("status"),
                    "wins": wins,
                    "draws": int(opponent.get("draws") or 0),
                    "losses": int(opponent.get("losses") or 0),
                    "match_count": int(expected or 0),
                    "win_rate": round(wins / expected, 6) if complete else 0.0,
                    "failed": bool(candidate.get("failure_reason"))
                    or candidate.get("status") == "failed"
                    or opponent.get("status") == "failed"
                    or bool(opponent.get("failure")),
                })
    return sorted(rows, key=lambda item: (
        item.get("generation", -1), str(item.get("opponent_id") or ""),
        str(item.get("candidate_id") or ""),
    ))


def _match_game_performance_rows(data: RunData) -> list[dict[str, Any]]:
    """Flatten canonical per-match scores retained in opponent summaries."""

    rows: list[dict[str, Any]] = []
    snapshots = data.generations
    if not snapshots and data.final_population:
        snapshots = [data.final_population]
    for snapshot in snapshots:
        snapshot_generation = snapshot.get("generation")
        population = snapshot.get("population", [])
        if not isinstance(population, list):
            continue
        for candidate in population:
            if not isinstance(candidate, dict):
                continue
            game = candidate.get("game_eval_result") or {}
            for opponent in game.get("opponent_results") or []:
                if not isinstance(opponent, dict):
                    continue
                for match_index, score in enumerate(opponent.get("match_scores") or []):
                    if isinstance(score, (int, float)) and not isinstance(score, bool):
                        rows.append({
                            "generation": candidate.get("generation", snapshot_generation),
                            "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
                            "opponent_id": opponent.get("opponent_id"),
                            "match_index": match_index,
                            "game_performance": float(score),
                        })
    return sorted(rows, key=lambda item: (
        item.get("generation", -1), str(item.get("candidate_id") or ""),
        str(item.get("opponent_id") or ""), item.get("match_index", -1),
    ))


def _opponent_game_performance_rows(data: RunData) -> list[dict[str, Any]]:
    """Flatten generation-level mean Game Performance for each opponent."""

    rows: list[dict[str, Any]] = []
    for item in data.generation_metrics:
        generation = item.get("generation")
        opponent_scores = item.get("opponent_scores") or {}
        by_opponent = opponent_scores.get("by_opponent") if isinstance(opponent_scores, dict) else {}
        if not isinstance(by_opponent, dict):
            continue
        for opponent_id, summary in by_opponent.items():
            if not isinstance(summary, dict):
                continue
            game_performance = summary.get("game_performance", summary.get("mean_score"))
            if game_performance is None:
                continue
            rows.append({
                "generation": generation,
                "opponent_id": str(opponent_id),
                "game_performance": game_performance,
            })
    return sorted(rows, key=lambda item: (item.get("generation", -1), item["opponent_id"]))


def _aos_rows(data: RunData) -> list[dict[str, Any]]:
    """Flatten generation-level AOS usage, reward, credit, and probability."""

    rows: list[dict[str, Any]] = []
    for item in data.generation_metrics:
        aos = item.get("aos") or {}
        operators = aos.get("operators") if isinstance(aos, dict) else {}
        transition_counts = aos.get("transition_counts") if isinstance(aos, dict) else {}
        if not isinstance(operators, dict):
            continue
        if not isinstance(transition_counts, dict):
            transition_counts = {}
        for operator, stats in sorted(operators.items()):
            if not isinstance(stats, dict):
                continue
            rows.append({
                "generation": item.get("generation"),
                "operator": operator,
                "usage_count": stats.get("usage_count", 0),
                "reward_count": stats.get("reward_count", 0),
                "mean_reward": stats.get("mean_reward"),
                "recent_credit": stats.get("recent_credit"),
                "selection_probability_before": stats.get("selection_probability_before"),
                "selection_probability": stats.get("selection_probability"),
                "cumulative_usage_count": stats.get("cumulative_usage_count", 0),
                "cumulative_reward_count": stats.get("cumulative_reward_count", 0),
                "cumulative_mean_reward": stats.get("cumulative_mean_reward"),
                **{
                    transition: transition_counts.get(transition, 0)
                    for transition in (
                        "failed_parent_to_runnable_child",
                        "runnable_parent_to_failed_child",
                        "failed_parent_to_failed_child",
                        "runnable_parent_to_runnable_child",
                    )
                },
            })
    return sorted(rows, key=lambda item: (item.get("generation", -1), item["operator"]))


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


def _plots(path: Path, generation_rows, candidates, agent_game_rows, opponent_game_rows, match_game_rows, agent_win_rate_rows, aos_rows) -> None:
    """Write only the compact plot set used for current run comparison."""

    for old_plot in path.glob("*.png"):
        old_plot.unlink()
    _line_plot(path / "code_quality_by_generation.png", generation_rows, "generation", ("code_quality_best", "code_quality_mean", "code_quality_median", "code_quality_worst"), "Code Quality diagnostic by generation")
    _line_plot(
        path / "game_performance_by_generation.png", generation_rows, "generation",
        ("game_performance_best", "game_performance_mean", "game_performance_median", "game_performance_worst"),
        "Aggregate Game Performance by generation", scatter_rows=match_game_rows,
        scatter_y="game_performance", neutral_line=True,
    )
    _agent_game_performance_plot(path / "agent_game_performance.png", agent_game_rows)
    _agent_win_rate_plots(path, agent_win_rate_rows)
    _aos_plot(path / "aos_operator_probabilities.png", aos_rows)
    for opponent_id in sorted({row["opponent_id"] for row in opponent_game_rows}):
        rows = [row for row in opponent_game_rows if row["opponent_id"] == opponent_id]
        match_rows = [row for row in match_game_rows if row.get("opponent_id") == opponent_id]
        filename_id = re.sub(r"[^A-Za-z0-9_-]+", "_", opponent_id).strip("_") or "unknown"
        _line_plot(
            path / f"game_performance_by_generation_{filename_id}.png",
            rows,
            "generation",
            ("game_performance",),
            f"Game Performance vs {opponent_id}", scatter_rows=match_rows,
            scatter_y="game_performance", neutral_line=True,
        )


def _line_plot(path: Path, rows, x, ys, title, *, scatter_rows=None, scatter_y: str | None = None, neutral_line: bool = False) -> None:
    if not rows:
        return
    plotted = []
    for y in ys:
        points = [(row.get(x), row.get(y)) for row in rows if row.get(x) is not None and row.get(y) is not None]
        if points:
            plotted.append((y, points))
    if not plotted:
        return
    plt.figure()
    if scatter_rows and scatter_y:
        points = [
            (row.get(x), row.get(scatter_y)) for row in scatter_rows
            if row.get(x) is not None and row.get(scatter_y) is not None
        ]
        if points:
            plt.scatter(
                [item[0] for item in points], [item[1] for item in points],
                color="#9ecae1", alpha=0.28, s=12, linewidths=0,
                label="Single-match scores",
            )
    for y, points in plotted:
        plt.plot([item[0] for item in points], [item[1] for item in points], marker="o", label=y)
    if neutral_line:
        _add_aggregate_neutral_line()
    plt.title(title)
    if plt.gca().get_legend_handles_labels()[0]:
        plt.legend()
    plt.tight_layout(); plt.savefig(path); plt.close()


def _add_aggregate_neutral_line() -> None:
    """Mark zero as the neutral reference for aggregate scores."""

    plt.axhline(0.0, color="#666666", linestyle="--", linewidth=1.0, alpha=0.75, label="Aggregate neutral (0)")


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
    _add_aggregate_neutral_line()
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _agent_win_rate_plots(path: Path, rows: list[dict[str, Any]]) -> None:
    for opponent_id in sorted({row["opponent_id"] for row in rows}):
        opponent_rows = [row for row in rows if row["opponent_id"] == opponent_id]
        filename_id = re.sub(r"[^A-Za-z0-9_-]+", "_", opponent_id).strip("_") or "unknown"
        _win_rate_plot(
            path / f"win_rate_by_generation_{filename_id}.png",
            opponent_rows,
            opponent_id,
        )


def _aos_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    plt.figure(figsize=(10, 5))
    for operator in sorted({row["operator"] for row in rows}):
        points = [row for row in rows if row["operator"] == operator and row.get("selection_probability") is not None]
        if points:
            plt.plot(
                [row["generation"] for row in points],
                [row["selection_probability"] for row in points],
                marker="o", label=operator,
            )
    plt.xlabel("Generation")
    plt.ylabel("Selection probability")
    plt.ylim(0.0, 1.0)
    plt.title("AOS operator probabilities by generation")
    plt.grid(True, alpha=0.2)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def _win_rate_plot(path: Path, rows: list[dict[str, Any]], opponent_id: str) -> None:
    points = [
        item for item in rows
        if item.get("generation") is not None
        and item.get("win_rate") is not None
        and not item.get("failed")
    ]
    if not points:
        return
    plt.figure(figsize=(10, 5))
    plt.scatter(
        [item["generation"] for item in points],
        [item["win_rate"] for item in points],
        s=18, alpha=0.65,
    )
    plt.xlabel("Generation")
    plt.ylabel("Win rate")
    plt.gca().yaxis.set_major_formatter(PercentFormatter(1.0))
    plt.ylim(0.0, 1.0)
    plt.title(f"Individual agent win rate vs {opponent_id}")
    plt.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
