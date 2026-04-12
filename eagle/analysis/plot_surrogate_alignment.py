"""Plot surrogate-validation alignment CSV files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from . import analysis_config as cfg


NUMERIC_FIELDS = {
    "eagle_win_score",
    "surrogate_win_score",
    "eagle_game_round_score",
    "surrogate_game_round_score",
    "eagle_resource_advantage_score",
    "surrogate_resource_advantage_score",
    "win_score_abs_gap",
    "game_round_score_abs_gap",
    "resource_advantage_score_abs_gap",
    "mean_abs_gap",
}


def _parse_optional_float(value: str | None) -> float | None:
    """Parse one CSV numeric cell into float when possible."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_alignment_rows(csv_path: Path) -> list[dict[str, object]]:
    """Load surrogate-validation alignment rows from CSV."""
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row: dict[str, object] = dict(raw_row)
            for field_name in NUMERIC_FIELDS:
                row[field_name] = _parse_optional_float(raw_row.get(field_name))
            same_result_label = str(raw_row.get("same_result_label") or "").strip().lower()
            if same_result_label == "true":
                row["same_result_label"] = True
            elif same_result_label == "false":
                row["same_result_label"] = False
            else:
                row["same_result_label"] = None
            rows.append(row)
    return rows


def _resolve_csv_path(cli_csv_path: Path | None) -> Path:
    """Resolve input CSV from CLI or config defaults."""
    if cli_csv_path is not None:
        return cli_csv_path.resolve()
    if cfg.DEFAULT_ALIGNMENT_CSV:
        return Path(cfg.DEFAULT_ALIGNMENT_CSV).resolve()
    raise ValueError("No alignment CSV path provided. Pass one on the CLI or set DEFAULT_ALIGNMENT_CSV in analysis_config.py")


def _resolve_output_dir(csv_path: Path, run_name: str | None) -> Path:
    """Resolve output folder under eagle/analysis/result/<run>."""
    resolved_run_name = run_name or csv_path.parent.name
    output_dir = cfg.RESULT_ROOT / resolved_run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def _write_config_snapshot(csv_path: Path, output_dir: Path, run_name: str) -> Path:
    """Persist the effective analysis configuration next to generated plots."""
    snapshot = {
        "run_name": run_name,
        "csv_path": str(csv_path),
        "output_dir": str(output_dir),
        "figure_dpi": cfg.FIGURE_DPI,
        "bar_figsize": list(cfg.BAR_FIGSIZE),
        "heatmap_min_width": cfg.HEATMAP_MIN_WIDTH,
        "heatmap_min_height": cfg.HEATMAP_MIN_HEIGHT,
        "heatmap_width_per_opponent": cfg.HEATMAP_WIDTH_PER_OPPONENT,
        "heatmap_height_per_individual": cfg.HEATMAP_HEIGHT_PER_INDIVIDUAL,
        "mean_gap_bar_color": cfg.MEAN_GAP_BAR_COLOR,
        "same_result_bar_color": cfg.SAME_RESULT_BAR_COLOR,
        "heatmap_cmap": cfg.HEATMAP_CMAP,
    }
    output_path = output_dir / cfg.CONFIG_SNAPSHOT_FILENAME
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def plot_mean_gap_by_opponent(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot average mean absolute gap for each opponent."""
    import matplotlib.pyplot as plt

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        opponent = str(row.get("opponent") or "")
        mean_abs_gap = row.get("mean_abs_gap")
        if opponent and isinstance(mean_abs_gap, float):
            grouped[opponent].append(mean_abs_gap)

    opponents = sorted(grouped)
    values = [sum(grouped[opponent]) / len(grouped[opponent]) for opponent in opponents]

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.bar(opponents, values, color=cfg.MEAN_GAP_BAR_COLOR)
    plt.ylabel("Average Mean Absolute Gap")
    plt.xlabel("Opponent")
    plt.title("Surrogate Alignment by Opponent")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    output_path = output_dir / cfg.MEAN_GAP_FILENAME
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_same_result_rate_by_opponent(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot result-label agreement rate for each opponent."""
    import matplotlib.pyplot as plt

    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        opponent = str(row.get("opponent") or "")
        same_result = row.get("same_result_label")
        if opponent and isinstance(same_result, bool):
            grouped[opponent].append(1.0 if same_result else 0.0)

    opponents = sorted(grouped)
    values = [sum(grouped[opponent]) / len(grouped[opponent]) for opponent in opponents]

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.bar(opponents, values, color=cfg.SAME_RESULT_BAR_COLOR)
    plt.ylabel("Same Result Rate")
    plt.xlabel("Opponent")
    plt.ylim(0.0, 1.0)
    plt.title("Java vs Surrogate Result Agreement")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    output_path = output_dir / cfg.SAME_RESULT_FILENAME
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_per_individual_gap_heatmap(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot a heatmap of mean absolute gap for each individual/opponent pair."""
    import matplotlib.pyplot as plt

    opponents = sorted({str(row.get("opponent") or "") for row in rows if row.get("opponent")})
    individual_ids = sorted({str(row.get("individual_id") or "") for row in rows if row.get("individual_id")})

    matrix: list[list[float]] = []
    for individual_id in individual_ids:
        row_values: list[float] = []
        for opponent in opponents:
            matched = [
                row.get("mean_abs_gap")
                for row in rows
                if row.get("individual_id") == individual_id and row.get("opponent") == opponent
            ]
            numeric_values = [value for value in matched if isinstance(value, float)]
            row_values.append(sum(numeric_values) / len(numeric_values) if numeric_values else float("nan"))
        matrix.append(row_values)

    width = max(cfg.HEATMAP_MIN_WIDTH, len(opponents) * cfg.HEATMAP_WIDTH_PER_OPPONENT)
    height = max(cfg.HEATMAP_MIN_HEIGHT, len(individual_ids) * cfg.HEATMAP_HEIGHT_PER_INDIVIDUAL)
    plt.figure(figsize=(width, height))
    image = plt.imshow(matrix, aspect="auto", cmap=cfg.HEATMAP_CMAP)
    plt.colorbar(image, label="Mean Absolute Gap")
    plt.xticks(range(len(opponents)), opponents, rotation=30, ha="right")
    plt.yticks(range(len(individual_ids)), individual_ids)
    plt.xlabel("Opponent")
    plt.ylabel("Individual")
    plt.title("Per-Individual Alignment Heatmap")
    plt.tight_layout()

    output_path = output_dir / cfg.HEATMAP_FILENAME
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for plotting surrogate validation CSV files."""
    parser = argparse.ArgumentParser(description="Plot surrogate-validation alignment CSV files.")
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=None,
        help="Path to surrogate_validation_alignment.csv. Optional when set in analysis_config.py.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional output run name. Defaults to the input CSV parent folder name.",
    )
    return parser


def main() -> None:
    """CLI entry point for surrogate-validation plotting."""
    parser = build_argument_parser()
    args = parser.parse_args()

    csv_path = _resolve_csv_path(args.csv_path)
    run_name = args.run_name or csv_path.parent.name
    output_dir = _resolve_output_dir(csv_path, run_name)

    rows = load_alignment_rows(csv_path)
    if not rows:
        raise ValueError(f"No rows found in alignment CSV: {csv_path}")

    try:
        import matplotlib.pyplot  # noqa: F401
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plotting. Install it in this environment before running eagle.analysis.plot_surrogate_alignment."
        ) from exc

    generated = [
        plot_mean_gap_by_opponent(rows, output_dir),
        plot_same_result_rate_by_opponent(rows, output_dir),
        plot_per_individual_gap_heatmap(rows, output_dir),
        _write_config_snapshot(csv_path, output_dir, run_name),
    ]

    print("Generated analysis artifacts:")
    for path in generated:
        print(path)


if __name__ == "__main__":
    main()
