"""Plot evolution fitness distributions and final-test resource outcomes."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from ..config import load_config_from_json
from ..project import EAGLE_LOGS_DIR, ensure_directory
from ..utils.checkpoint import deserialize_individual
from ..utils.ea_log_parse import parse_individuals_from_ea_log, parse_population_snapshot_from_ea_log


GENERATION_LOG_PATTERN = re.compile(r"generation_(\d+)_mo\.txt$")
FINAL_TEST_CANDIDATES = ("final_test_results.json", "final_test_result.json")
FINAL_TEST_MODES = ("interval_1", "interval_10", "java_agent_test")


def _require_matplotlib():
    """Import matplotlib lazily so CLI help still works without the package."""
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plotting. Install requirements.txt before running analysis."
        ) from exc
    return plt


def _require_pillow():
    """Import Pillow lazily for GIF generation."""
    try:
        from PIL import Image  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Pillow is required for GIF generation. Install requirements.txt before running analysis."
        ) from exc
    return Image


def _extract_generation_number(path: Path) -> int:
    """Return the one-based generation number encoded in a log filename."""
    match = GENERATION_LOG_PATTERN.match(path.name)
    if not match:
        return -1
    return int(match.group(1))


def _find_latest_run_dir() -> Path:
    """Return the newest EAGLE run directory that contains generation logs."""
    candidates = []
    for path in EAGLE_LOGS_DIR.iterdir():
        if not path.is_dir():
            continue
        if any(path.glob("generation_*_mo.txt")):
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"No EA run directories with generation logs found under {EAGLE_LOGS_DIR}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _resolve_run_dir(run_dir: str | Path | None, latest: bool) -> Path:
    """Resolve the analysis target run directory."""
    if run_dir is not None:
        return Path(run_dir).resolve()
    if latest:
        return _find_latest_run_dir()
    raise ValueError("Provide --run-dir or use --latest.")


def _resolve_final_test_path(run_dir: Path) -> Path | None:
    """Find the final-test JSON payload under one run directory."""
    for filename in FINAL_TEST_CANDIDATES:
        candidate = run_dir / filename
        if candidate.exists():
            return candidate
    return None


def _safe_float(value: object) -> float:
    """Convert numeric-looking values to float and fall back to NaN."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _clean_axis_label(label: str) -> str:
    """Shorten fully qualified Java class names for plot labels."""
    return label.split(".")[-1]


def _evolution_objective_labels(run_dir: Path, eval_mode: str = "match") -> tuple[str, str]:
    """Build axis labels from the run config's ordered real-eval opponents."""
    if eval_mode == "round":
        return ("Legal Action Ratio", "Strategy Alignment Score (0-100)")

    config = load_config_from_json(run_dir)
    opponents = list(getattr(config, "real_eval_opponents", []) or [])
    labels = [_clean_axis_label(opponent) for opponent in opponents[:2]]
    while len(labels) < 2:
        labels.append(f"Objective {len(labels) + 1}")
    return (f"{labels[0]} Combined Score", f"{labels[1]} Combined Score")


def _compose_plot_title(default_title: str, custom_title: str | None) -> str:
    """Compose a plot title with an optional custom prefix."""
    if not custom_title:
        return default_title
    return f"{default_title} - {custom_title}"


def _debug_print(debug: bool, *values: object) -> None:
    """Print only when debug mode is enabled."""
    if debug:
        print(*values)


def _dominates(left_fitness: list[float], right_fitness: list[float]) -> bool:
    """Return whether one fitness vector Pareto-dominates another."""
    better_in_any = False
    for left_value, right_value in zip(left_fitness, right_fitness):
        if left_value < right_value:
            return False
        if left_value > right_value:
            better_in_any = True
    return better_in_any


def _front_one_ids_from_population(individuals: list) -> set[str]:
    """Compute Front-1 ids directly from one population snapshot."""
    front_one: list = []
    for candidate in individuals:
        candidate_fitness = list(getattr(candidate, "fitness", []) or [])
        dominated = False
        for other in individuals:
            if other is candidate:
                continue
            other_fitness = list(getattr(other, "fitness", []) or [])
            if _dominates(other_fitness, candidate_fitness):
                dominated = True
                break
        if not dominated:
            front_one.append(candidate)
    return {getattr(individual, "id", "") for individual in front_one}


def _load_generation_entries_from_checkpoints(run_dir: Path, debug: bool = False) -> list[tuple[int, list, set[str]]]:
    """Load complete generation populations from checkpoints when available."""
    checkpoints_path = run_dir / "checkpoints.jsonl"
    if not checkpoints_path.exists():
        return []

    latest_by_generation: dict[int, dict] = {}
    for raw_line in checkpoints_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("phase") != "generation_complete":
            continue
        generation = int(payload.get("generation", -999))
        latest_by_generation[generation] = payload

    loaded: list[tuple[int, list, set[str]]] = []
    for generation in sorted(latest_by_generation):
        payload = latest_by_generation[generation]
        individuals = [
            deserialize_individual(individual_payload)
            for individual_payload in list(payload.get("population") or [])
        ]
        if not individuals:
            continue
        _debug_print(debug, f"Loaded {len(individuals)} individuals from checkpoint for generation {generation+1}")
        front_one_ids = _front_one_ids_from_population(individuals)
        display_generation = generation + 1
        loaded.append((display_generation, individuals, front_one_ids))
    return loaded


def _load_generation_entries_from_logs(run_dir: Path) -> list[tuple[int, list, set[str]]]:
    """Load population snapshots plus Front-1 ids from generation logs."""
    generation_logs = sorted(run_dir.glob("generation_*_mo.txt"), key=_extract_generation_number)
    loaded = []
    for generation_log in generation_logs:
        generation_number = _extract_generation_number(generation_log)
        fronts = parse_individuals_from_ea_log(str(generation_log))
        front_one_ids = {
            getattr(individual, "id", "")
            for individual in (fronts[0] if fronts else [])
        }
        population = parse_population_snapshot_from_ea_log(str(generation_log))
        if population:
            loaded.append((generation_number, population, _front_one_ids_from_population(population)))
            continue
        flattened = [individual for front in fronts for individual in front]
        loaded.append((generation_number, flattened, front_one_ids))
    return loaded


def _load_generation_entries(run_dir: Path, debug: bool = False) -> list[tuple[int, list, set[str]]]:
    """Load complete populations for every generation, preferring generation logs."""
    from_logs = _load_generation_entries_from_logs(run_dir)
    if from_logs:
        _debug_print(debug, f"Loaded {len(from_logs)} generations from generation_*_mo.txt logs")
        return from_logs

    from_checkpoints = _load_generation_entries_from_checkpoints(run_dir, debug=debug)
    if from_checkpoints:
        _debug_print(debug, f"Loaded {len(from_checkpoints)} generations from checkpoints fallback")
        return from_checkpoints

    return []


def _plot_generation_scatter(
    run_dir: Path,
    output_dir: Path,
    custom_title: str | None = None,
    debug: bool = False,
    eval_mode: str = "match",
) -> list[Path]:
    """Render one combined plot plus one per-generation plot."""
    plt = _require_matplotlib()
    generation_entries = _load_generation_entries(run_dir, debug=debug)
    evolution_objective_labels = _evolution_objective_labels(run_dir, eval_mode=eval_mode)
    if not generation_entries:
        return []

    all_x_values: list[float] = []
    all_y_values: list[float] = []
    for _, individuals, _ in generation_entries:
        for individual in individuals:
            x_value = _safe_float(individual.fitness[0]) if len(individual.fitness) > 0 else float("nan")
            y_value = _safe_float(individual.fitness[1]) if len(individual.fitness) > 1 else float("nan")
            if math.isnan(x_value) or math.isnan(y_value):
                continue
            all_x_values.append(x_value)
            all_y_values.append(y_value)

    if not all_x_values or not all_y_values:
        return []

    x_min = min(all_x_values)
    x_max = max(all_x_values)
    y_min = min(all_y_values)
    y_max = max(all_y_values)

    x_padding = max((x_max - x_min) * 0.08, 1.0)
    y_padding = max((y_max - y_min) * 0.08, 1.0)
    x_limits = (x_min - x_padding, x_max + x_padding)
    y_limits = (y_min - y_padding, y_max + y_padding)

    figure_paths: list[Path] = []
    plt.figure(figsize=(10, 8))
    cmap = plt.get_cmap("viridis", max(1, len(generation_entries)))

    max_gen = max(g[0] for g in generation_entries)

    for color_index, (generation_number, individuals, front_one_ids) in enumerate(generation_entries):
        if not individuals:
            continue

        color = cmap(color_index)
        non_front_pairs = []
        front_one_pairs = []

        for individual in individuals:
            x_value = _safe_float(individual.fitness[0]) if len(individual.fitness) > 0 else float("nan")
            y_value = _safe_float(individual.fitness[1]) if len(individual.fitness) > 1 else float("nan")
            print(f"Gen {generation_number} - Individual {getattr(individual, 'id', '')}: Fitness = ({x_value}, {y_value}), Front 1 = {getattr(individual, 'id', '') in front_one_ids}")
            if math.isnan(x_value) or math.isnan(y_value):
                continue

            if getattr(individual, "id", "") in front_one_ids:
                front_one_pairs.append((x_value, y_value))
            else:
                non_front_pairs.append((x_value, y_value))

        if not non_front_pairs and not front_one_pairs:
            continue

        # 10 generation intervals with labels in the combined plot
        label = f"Gen {generation_number}" if generation_number % 10 == 0 else None

        if non_front_pairs:
            plt.scatter(
                [p[0] for p in non_front_pairs],
                [p[1] for p in non_front_pairs],
                color=color,
                edgecolors="none",
                alpha=0.8,
                label=label,
            )

        #  Front 1（
        if front_one_pairs:
            front_label = "Front 1" if generation_number == max_gen else None
            plt.scatter(
                [p[0] for p in front_one_pairs],
                [p[1] for p in front_one_pairs],
                color=color,
                edgecolors="black",
                linewidths=1.0,
                alpha=0.95,
                label=front_label,
            )

        # ===== per-generation plot =====
        plt.figure(figsize=(8, 6))

        if non_front_pairs:
            plt.scatter(
                [p[0] for p in non_front_pairs],
                [p[1] for p in non_front_pairs],
                color=color,
                edgecolors="none",
                alpha=0.8,
            )

        if front_one_pairs:
            plt.scatter(
                [p[0] for p in front_one_pairs],
                [p[1] for p in front_one_pairs],
                color=color,
                edgecolors="black",
                linewidths=1.0,
                alpha=0.95,
                label="Front 1",
            )

        plt.xlabel(evolution_objective_labels[0])
        plt.ylabel(evolution_objective_labels[1])
        plt.title(_compose_plot_title(f"Generation {generation_number} Fitness Distribution", custom_title))
        plt.xlim(*x_limits)
        plt.ylim(*y_limits)
        plt.grid(alpha=0.25)

        plt.legend(loc="best", fontsize=8)

        per_generation_path = output_dir / f"generation_{generation_number:03d}_fitness_scatter.png"
        plt.tight_layout()
        plt.savefig(per_generation_path, dpi=200)
        plt.close()
        figure_paths.append(per_generation_path)

    # ===== combined plot =====
    plt.xlabel(evolution_objective_labels[0])
    plt.ylabel(evolution_objective_labels[1])
    plt.title(_compose_plot_title("Generation Fitness Distribution", custom_title))
    plt.xlim(*x_limits)
    plt.ylim(*y_limits)
    plt.grid(alpha=0.25)

    plt.legend(loc="best", fontsize=8, ncols=2)

    figure_path = output_dir / "generation_fitness_scatter_all.png"
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()

    figure_paths.insert(0, figure_path)
    return figure_paths


def _build_generation_gif(image_paths: list[Path], output_path: Path) -> Path | None:
    """Build one animated GIF from the per-generation scatter plots."""
    per_generation_images = [
        path for path in image_paths
        if path.name.startswith("generation_") and path.name != "generation_fitness_scatter_all.png"
    ]
    if not per_generation_images:
        return None

    Image = _require_pillow()
    frames = [Image.open(path).convert("RGBA") for path in per_generation_images]
    try:
        first_frame, *remaining_frames = frames
        first_frame.save(
            output_path,
            save_all=True,
            append_images=remaining_frames,
            duration=100,
            loop=0,
            disposal=2,
        )
    finally:
        for frame in frames:
            frame.close()
    return output_path


def _collect_final_test_mode_rows(results_payload: dict, interval_mode: str) -> tuple[list[str], list[str], list[list[float]]]:
    """Collect one heatmap matrix for one final-test mode."""
    results = dict(results_payload.get("results") or {})
    individual_ids = sorted(results.keys())
    opponent_names: list[str] = []
    matrix: list[list[float]] = []

    for individual_id in individual_ids:
        rows = [
            row for row in list(results.get(individual_id) or [])
            if str(row.get("interval_mode")) == interval_mode
        ]
        if not opponent_names:
            opponent_names = sorted({str(row.get("opponent")) for row in rows})

        row_values: list[float] = []
        for opponent in opponent_names:
            matched_row = next((row for row in rows if str(row.get("opponent")) == opponent), None)
            row_values.append(
                _safe_float(matched_row.get("resource_advantage_score")) if matched_row is not None else float("nan")
            )
        matrix.append(row_values)

    return individual_ids, opponent_names, matrix


def _plot_final_test_mode(
    run_dir: Path,
    output_dir: Path,
    final_test_path: Path,
    interval_mode: str,
    custom_title: str | None = None,
) -> Path | None:
    """Render one heatmap for one final-test mode."""
    plt = _require_matplotlib()
    payload = json.loads(final_test_path.read_text(encoding="utf-8"))
    individual_ids, opponent_names, matrix = _collect_final_test_mode_rows(payload, interval_mode)

    if not individual_ids or not opponent_names:
        return None

    plt.figure(figsize=(max(8, len(opponent_names) * 1.2), max(6, len(individual_ids) * 0.6)))
    image = plt.imshow(matrix, cmap="coolwarm", aspect="auto")
    plt.xticks(range(len(opponent_names)), [_clean_axis_label(name) for name in opponent_names], rotation=45, ha="right")
    plt.yticks(range(len(individual_ids)), individual_ids)
    plt.xlabel("Opponent")
    plt.ylabel("Individual")
    plt.title(_compose_plot_title(f"Final Test Resource Advantage: {interval_mode}", custom_title))
    colorbar = plt.colorbar(image)
    colorbar.set_label("Resource Advantage Score")

    for row_index, row_values in enumerate(matrix):
        for col_index, value in enumerate(row_values):
            if math.isnan(value):
                continue
            plt.text(col_index, row_index, f"{value:.1f}", ha="center", va="center", fontsize=8, color="black")

    figure_path = output_dir / f"final_test_resource_{interval_mode}.png"
    plt.tight_layout()
    plt.savefig(figure_path, dpi=200)
    plt.close()
    return figure_path


def analyze_evolution_run(
    run_dir: str | Path | None = None,
    *,
    latest: bool = False,
    title: str | None = None,
    debug: bool = False,
    eval_mode: str = "match",
) -> dict[str, object]:
    """Generate evolution scatter plots and final-test resource heatmaps."""
    if eval_mode not in {"match", "round"}:
        raise ValueError(f"Unsupported eval_mode: {eval_mode!r}")

    resolved_run_dir = _resolve_run_dir(run_dir, latest)
    output_dir = ensure_directory(resolved_run_dir / "analysis" / "evolution")

    generation_figures = _plot_generation_scatter(
        resolved_run_dir,
        ensure_directory(output_dir / "generation_fitness"),
        custom_title=title,
        debug=debug,
        eval_mode=eval_mode,
    )
    generation_gif_path = _build_generation_gif(
        generation_figures,
        output_dir / "generation_fitness" / "generation_fitness_animation.gif",
    )

    final_test_path = _resolve_final_test_path(resolved_run_dir)
    final_test_figures: dict[str, str] = {}
    if final_test_path is not None:
        final_test_output_dir = ensure_directory(output_dir / "final_test")
        for interval_mode in FINAL_TEST_MODES:
            figure_path = _plot_final_test_mode(
                resolved_run_dir,
                final_test_output_dir,
                final_test_path,
                interval_mode,
                custom_title=title,
            )
            if figure_path is not None:
                final_test_figures[interval_mode] = str(figure_path)

    summary = {
        "run_dir": str(resolved_run_dir),
        "generation_scatter_figures": [str(path) for path in generation_figures],
        "generation_animation_gif": str(generation_gif_path) if generation_gif_path is not None else None,
        "final_test_result_path": str(final_test_path) if final_test_path is not None else None,
        "final_test_figures": final_test_figures,
        "title": title,
        "debug": debug,
        "eval_mode": eval_mode,
    }
    summary_path = output_dir / "analysis_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the CLI for plotting one EAGLE evolution run."""
    parser = argparse.ArgumentParser(description="Plot EAGLE evolution fitness and final-test resource results.")
    parser.add_argument("--run-dir", default=None, help="Target EAGLE run directory under logs/eagle.")
    parser.add_argument("--latest", action="store_true", help="Analyze the latest run with generation logs.")
    parser.add_argument("--title", default=None, help="Custom title for the generated plots.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode and print debug output.")
    parser.add_argument(
        "--eval-mode",
        choices=["match", "round"],
        default="match",
        help="Use 'round' for eagle_round_evol legality/alignment objectives.",
    )
    return parser


def main() -> None:
    """CLI entry point for evolution-result analysis."""
    parser = build_argument_parser()
    args = parser.parse_args()
    summary = analyze_evolution_run(
        run_dir=args.run_dir,
        latest=args.latest,
        title=args.title,
        debug=args.debug,
        eval_mode=args.eval_mode,
    )
    _debug_print(args.debug, json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
