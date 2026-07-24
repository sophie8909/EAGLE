"""Summarize EAGLE run failures from saved artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eagle.analysis.final_tests import load_final_test_summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze an EAGLE run directory.")
    parser.add_argument("run_dir", help="Path to runs/<run_id>")
    parser.add_argument(
        "--plot-dir",
        default=None,
        help="Directory for objective scatter plots. Default: <run-dir>/analysis",
    )
    parser.add_argument(
        "--gif-duration-ms",
        type=int,
        default=700,
        help="Frame duration for the per-generation objective GIF.",
    )
    parser.add_argument("--show", action="store_true", help="Show the all-generations plot after saving.")
    parser.add_argument("--no-plots", action="store_true", help="Only print the text summary.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    print(format_report(analyze_run(run_dir)))
    if args.no_plots:
        return

    try:
        plot_summary = write_objective_scatter_outputs(
            run_dir,
            output_dir=Path(args.plot_dir) if args.plot_dir else None,
            gif_duration_ms=args.gif_duration_ms,
            show=args.show,
        )
    except RuntimeError as error:
        print("")
        print(f"Objective scatter plots: skipped ({error})")
        return
    print(format_plot_report(plot_summary))


def analyze_run(run_dir: Path) -> dict[str, Any]:
    records = read_candidate_results(run_dir)
    failure_records = [record for record in records if record.get("failure_category")]
    success_count = len(records) - len(failure_records)

    category_counts = Counter(record["failure_category"] for record in failure_records)
    reason_counts = Counter(record.get("failure_reason") or "" for record in failure_records)
    validation_counts = Counter(
        validation_error(record)
        for record in failure_records
        if validation_error(record)
    )
    compile_counts = Counter(
        compile_root_cause(record)
        for record in failure_records
        if compile_root_cause(record)
    )
    representatives: dict[str, str] = {}
    for record in failure_records:
        category = record["failure_category"]
        representatives.setdefault(category, record.get("candidate_path", ""))

    return {
        "run_dir": str(run_dir),
        "total_candidates": len(records),
        "failed_candidates": len(failure_records),
        "success_count": success_count,
        "failure_category_counts": category_counts,
        "top_failure_reasons": reason_counts,
        "compile_root_cause_counts": compile_counts,
        "validation_failure_counts": validation_counts,
        "representatives": representatives,
        "final_tests": load_final_test_summaries(run_dir),
    }


def read_candidate_results(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/candidate_result.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["candidate_path"] = str(path.parent)
        records.append(payload)
    return records


def write_objective_scatter_outputs(
    run_dir: Path,
    *,
    output_dir: Path | None = None,
    gif_duration_ms: int = 700,
    show: bool = False,
) -> dict[str, Any]:
    """Write 2D code-quality/game-performance dot plots for a run."""
    records = read_objective_scatter_records(run_dir)
    target_dir = output_dir or run_dir / "analysis"
    target_dir.mkdir(parents=True, exist_ok=True)

    csv_path = target_dir / "objective_scatter_points.csv"
    write_objective_scatter_csv(csv_path, records)

    valid_records = [
        record
        for record in records
        if not math.isnan(record["code_quality"]) and not math.isnan(record["game_performance"])
    ]
    if not valid_records:
        return {
            "records": len(records),
            "valid_records": 0,
            "csv": csv_path,
            "all_generations_plot": None,
            "gif": None,
            "generation_plots": [],
        }

    axis_limits = objective_axis_limits(valid_records)
    all_path = target_dir / "objective_scatter_all_generations.png"
    write_objective_scatter_plot(
        all_path,
        run_dir=run_dir,
        records=valid_records,
        all_records=valid_records,
        axis_limits=axis_limits,
        title=f"Code quality vs game performance: {run_dir.name}",
        all_generations=True,
        show=show,
    )

    generation_plots: list[Path] = []
    for generation in sorted({record["generation"] for record in valid_records}):
        generation_records = [
            record for record in valid_records if record["generation"] == generation
        ]
        generation_path = target_dir / f"objective_scatter_generation_{generation:03d}.png"
        write_objective_scatter_plot(
            generation_path,
            run_dir=run_dir,
            records=generation_records,
            all_records=valid_records,
            axis_limits=axis_limits,
            title=f"Generation {generation}: code quality vs game performance",
            all_generations=False,
            show=False,
        )
        generation_plots.append(generation_path)

    gif_path = target_dir / "objective_scatter_by_generation.gif"
    write_generation_gif(generation_plots, gif_path, duration_ms=gif_duration_ms)

    return {
        "records": len(records),
        "valid_records": len(valid_records),
        "csv": csv_path,
        "all_generations_plot": all_path,
        "gif": gif_path,
        "generation_plots": generation_plots,
    }

def read_objective_scatter_records(run_dir: Path) -> list[dict[str, Any]]:
    """Read objective values only from canonical per-candidate artifacts."""
    return sorted_objective_records(dedupe_objective_records(read_candidate_result_objective_records(run_dir)))


def read_candidate_result_objective_records(run_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((run_dir / "candidates").glob("*/candidate_result.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        objectives = payload.get("final_score")
        if not isinstance(objectives, dict):
            continue
        individual = json.loads((path.parent / "individual.json").read_text(encoding="utf-8"))
        records.append({
            "generation": int_or_zero(individual.get("generation")),
            "candidate_id": str(payload.get("candidate_id") or path.parent.name),
            "code_quality": float_or_nan(objectives.get("code_quality")),
            "game_performance": float_or_nan(objectives.get("game_performance")),
            "source": "candidate_result",
        })
    return records


def dedupe_objective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        candidate_id = record.get("candidate_id") or ""
        if candidate_id and (candidate_id not in by_id or objective_record_completeness(record) > objective_record_completeness(by_id[candidate_id])):
            by_id[candidate_id] = record
    return list(by_id.values())


def objective_record_completeness(record: dict[str, Any]) -> int:
    return sum(not math.isnan(record[key]) for key in ("code_quality", "game_performance"))


def sorted_objective_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: (record["generation"], record["candidate_id"]))


def write_objective_scatter_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["generation", "candidate_id", "code_quality", "game_performance"],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "generation": record["generation"],
                    "candidate_id": record["candidate_id"],
                    "code_quality": csv_float(record["code_quality"]),
                    "game_performance": csv_float(record["game_performance"]),
                }
            )


def write_objective_scatter_plot(
    output_path: Path,
    *,
    run_dir: Path,
    records: list[dict[str, Any]],
    all_records: list[dict[str, Any]],
    axis_limits: tuple[tuple[float, float], tuple[float, float]],
    title: str,
    all_generations: bool,
    show: bool,
) -> None:
    plt = import_pyplot()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 6))
    if all_generations:
        scatter = ax.scatter(
            [plot_x(record, axis_limits) for record in records],
            [plot_y(record, axis_limits) for record in records],
            c=[record["generation"] for record in records],
            cmap="viridis",
            alpha=0.78,
            s=38,
            edgecolors="white",
            linewidths=0.45,
        )
        generations = sorted({record["generation"] for record in records})
        if len(generations) > 1:
            colorbar = fig.colorbar(scatter, ax=ax)
            colorbar.set_label("Generation")
    else:
        ax.scatter(
            [plot_x(record, axis_limits) for record in records],
            [plot_y(record, axis_limits) for record in records],
            color="#2563eb",
            alpha=0.82,
            s=48,
            edgecolors="white",
            linewidths=0.55,
            label=f"Generation {records[0]['generation']}" if records else "Generation",
        )
        ax.legend(loc="best")

    ax.axhline(0, color="black", linewidth=1, alpha=0.45)
    ax.axvline(0, color="black", linewidth=1, alpha=0.25)
    ax.set_xlim(*axis_limits[0])
    ax.set_ylim(*axis_limits[1])
    ax.set_title(title)
    ax.set_xlabel("Code quality")
    ax.set_ylabel("Game performance")
    ax.grid(True, alpha=0.22)
    ax.text(
        0.01,
        0.01,
        f"{len(records)} points / {len(all_records)} total valid",
        transform=ax.transAxes,
        fontsize=8,
        alpha=0.7,
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    if show:
        plt.show()
    plt.close(fig)


def write_generation_gif(frame_paths: list[Path], output_path: Path, *, duration_ms: int) -> None:
    if not frame_paths:
        return
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required to write GIF output") from error

    frames = [Image.open(path).convert("RGB") for path in frame_paths]
    try:
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=max(1, duration_ms),
            loop=0,
        )
    finally:
        for frame in frames:
            frame.close()


def objective_axis_limits(records: list[dict[str, Any]]) -> tuple[tuple[float, float], tuple[float, float]]:
    return (
        padded_limits([record["code_quality"] for record in records]),
        padded_limits([record["game_performance"] for record in records]),
    )


def padded_limits(values: list[float]) -> tuple[float, float]:
    low = min(values)
    high = max(values)
    if low == high:
        padding = max(abs(low) * 0.05, 1.0)
    else:
        padding = (high - low) * 0.08
    return low - padding, high + padding


def import_pyplot():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    try:
        from matplotlib import pyplot as plt
    except ImportError as error:
        raise RuntimeError("matplotlib is required to write objective scatter plots") from error
    return plt


def plot_x(record: dict[str, Any], axis_limits: tuple[tuple[float, float], tuple[float, float]]) -> float:
    return record["code_quality"] + stable_jitter(record["candidate_id"], scale=axis_span(axis_limits[0]) * 0.004)


def plot_y(record: dict[str, Any], axis_limits: tuple[tuple[float, float], tuple[float, float]]) -> float:
    return record["game_performance"] + stable_jitter(f"{record['candidate_id']}:y", scale=axis_span(axis_limits[1]) * 0.004)


def axis_span(axis_limit: tuple[float, float]) -> float:
    return axis_limit[1] - axis_limit[0]


def stable_jitter(value: str, *, scale: float) -> float:
    # Stable jitter makes identical-score candidates visible while CSV keeps exact values.
    bucket = sum(ord(char) for char in value) % 1000
    return ((bucket / 999.0) - 0.5) * scale


def validation_error(record: dict[str, Any]) -> str:
    validation = record.get("validation_result") or {}
    return str(validation.get("error") or "")


def compile_root_cause(record: dict[str, Any]) -> str:
    compile_result = record.get("compile_result") or {}
    stderr = str(compile_result.get("stderr") or "")
    if not stderr:
        return ""
    from eagle.analysis.errors import compile_root_cause as shared_compile_root_cause
    return shared_compile_root_cause(stderr)


def first_javac_error(stderr: str) -> str:
    return shared_first_javac_error(stderr)


def format_report(summary: dict[str, Any]) -> str:
    lines = [
        f"Run: {summary['run_dir']}",
        f"Total candidates found: {summary['total_candidates']}",
        f"Failed candidates: {summary['failed_candidates']}",
    ]
    if summary["success_count"] is None:
        lines.append("Success count: unknown")
    else:
        lines.append(f"Success count: {summary['success_count']}")

    append_counter(lines, "Failure category counts", summary["failure_category_counts"])
    append_counter(lines, "Top failure reasons", summary["top_failure_reasons"], limit=10)
    append_counter(lines, "Compile root cause counts", summary["compile_root_cause_counts"])
    append_counter(lines, "Validation failure counts", summary["validation_failure_counts"])

    lines.append("")
    lines.append("Representative candidate paths:")
    if summary["representatives"]:
        for category, path in sorted(summary["representatives"].items()):
            lines.append(f"- {category}: {path}")
    else:
        lines.append("- none")
    lines.extend(("", "Final tests:"))
    if not summary["final_tests"]:
        lines.append("- none")
    for item in summary["final_tests"]:
        lines.append(f"- {item.final_test_id}: {item.status} {item.completed_matches}/{item.expected_matches} path={item.path}")
    return "\n".join(lines)


def format_plot_report(summary: dict[str, Any]) -> str:
    lines = [
        "",
        "Objective scatter plots:",
        f"- records: {summary['records']} ({summary['valid_records']} plottable)",
        f"- csv: {summary['csv']}",
    ]
    if summary["valid_records"] == 0:
        lines.append("- plots: none (no candidates with both code_quality and game_performance)")
        return "\n".join(lines)

    lines.extend(
        [
            f"- all generations: {summary['all_generations_plot']}",
            f"- gif by generation: {summary['gif']}",
            f"- individual generation plots: {len(summary['generation_plots'])} files",
        ]
    )
    return "\n".join(lines)


def append_counter(lines: list[str], title: str, counter: Counter, *, limit: int | None = None) -> None:
    lines.append("")
    lines.append(f"{title}:")
    items = counter.most_common(limit)
    if not items:
        lines.append("- none")
        return
    for key, count in items:
        display = key if key else "(blank)"
        lines.append(f"- {display}: {count}")


def int_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_or_nan(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def csv_float(value: float) -> str:
    return "NaN" if math.isnan(value) else str(value)


if __name__ == "__main__":
    main()
