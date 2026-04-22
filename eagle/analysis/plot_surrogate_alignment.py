"""Plot surrogate-validation alignment CSV files."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


NUMERIC_FIELDS = {
    "eagle_win_score",
    "surrogate_win_score",
    "eagle_resource_advantage_score",
    "surrogate_resource_advantage_score",
    "win_score_abs_gap",
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


def _sanitize_filename(name: str) -> str:
    """Convert a plot title or key into a filesystem-safe stem."""
    safe = []
    for ch in name:
        if ch.isalnum() or ch in {"-", "_"}:
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "plot"


def plot_mean_gap_by_opponent(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot average mean absolute gap for each opponent."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        opponent = str(row.get("opponent") or "")
        mean_abs_gap = row.get("mean_abs_gap")
        if opponent and isinstance(mean_abs_gap, float):
            grouped[opponent].append(mean_abs_gap)

    opponents = sorted(grouped)
    values = [sum(grouped[opponent]) / len(grouped[opponent]) for opponent in opponents]

    plt.figure(figsize=(10, 5))
    plt.bar(opponents, values, color="#3A6EA5")
    plt.ylabel("Average Mean Absolute Gap")
    plt.xlabel("Opponent")
    plt.title("Surrogate Alignment by Opponent")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    output_path = output_dir / "mean_gap_by_opponent.png"
    plt.savefig(output_path, dpi=180)
    plt.close()
    return output_path


def plot_same_result_rate_by_opponent(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot result-label agreement rate for each opponent."""
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        opponent = str(row.get("opponent") or "")
        same_result = row.get("same_result_label")
        if opponent and isinstance(same_result, bool):
            grouped[opponent].append(1.0 if same_result else 0.0)

    opponents = sorted(grouped)
    values = [sum(grouped[opponent]) / len(grouped[opponent]) for opponent in opponents]

    plt.figure(figsize=(10, 5))
    plt.bar(opponents, values, color="#6BA368")
    plt.ylabel("Same Result Rate")
    plt.xlabel("Opponent")
    plt.ylim(0.0, 1.0)
    plt.title("Java vs Surrogate Result Agreement")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    output_path = output_dir / "same_result_rate_by_opponent.png"
    plt.savefig(output_path, dpi=180)
    plt.close()
    return output_path


def plot_per_individual_gap_heatmap(rows: list[dict[str, object]], output_dir: Path) -> Path:
    """Plot a heatmap of mean absolute gap for each individual/opponent pair."""
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

    plt.figure(figsize=(max(8, len(opponents) * 1.2), max(5, len(individual_ids) * 0.45)))
    image = plt.imshow(matrix, aspect="auto", cmap="viridis")
    plt.colorbar(image, label="Mean Absolute Gap")
    plt.xticks(range(len(opponents)), opponents, rotation=30, ha="right")
    plt.yticks(range(len(individual_ids)), individual_ids)
    plt.xlabel("Opponent")
    plt.ylabel("Individual")
    plt.title("Per-Individual Alignment Heatmap")
    plt.tight_layout()

    output_path = output_dir / "alignment_heatmap.png"
    plt.savefig(output_path, dpi=180)
    plt.close()
    return output_path


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for plotting surrogate validation CSV files."""
    parser = argparse.ArgumentParser(description="Plot surrogate-validation alignment CSV files.")
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to surrogate_validation_alignment.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated figures. Defaults to the CSV parent / plots.",
    )
    return parser


def main() -> None:
    """CLI entry point for surrogate-validation plotting."""
    parser = build_argument_parser()
    args = parser.parse_args()

    csv_path = args.csv_path.resolve()
    output_dir = (args.output_dir or (csv_path.parent / "plots")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_alignment_rows(csv_path)
    if not rows:
        raise ValueError(f"No rows found in alignment CSV: {csv_path}")

    generated = [
        plot_mean_gap_by_opponent(rows, output_dir),
        plot_same_result_rate_by_opponent(rows, output_dir),
        plot_per_individual_gap_heatmap(rows, output_dir),
    ]

    print("Generated plots:")
    for path in generated:
        print(path)


if __name__ == "__main__":
    main()
