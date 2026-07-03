"""Matplotlib plots for Java-vs-prompt consistency analysis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import analysis_config as cfg


def _import_pyplot():
    """Import matplotlib lazily so the module remains importable without it."""
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plotting. Install it before running eagle.analysis.run_consistency_analysis."
        ) from exc
    return plt


def plot_scatter_consistency(rows: list[dict[str, Any]], output_path: Path) -> Path:
    """Plot prompt score vs Java score with a y=x reference line."""
    plt = _import_pyplot()
    x_values = [float(row["prompt_score"]) for row in rows]
    y_values = [float(row["java_score"]) for row in rows]
    min_value = min(x_values + y_values)
    max_value = max(x_values + y_values)

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.scatter(x_values, y_values, alpha=0.75, color=cfg.MEAN_GAP_BAR_COLOR)
    plt.plot([min_value, max_value], [min_value, max_value], linestyle="--", color="black", linewidth=1.0)
    plt.xlabel("Prompt-Based Score")
    plt.ylabel("Java Agent Score")
    plt.title("Java vs Prompt-Based Consistency")
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_metric_consistency(
    rows: list[dict[str, Any]],
    *,
    prompt_key: str,
    java_key: str,
    axis_label: str,
    title: str,
    output_path: Path,
) -> Path | None:
    """Plot one metric's prompt-vs-Java consistency with a y=x reference line."""
    plt = _import_pyplot()
    paired = [
        (row.get(prompt_key), row.get(java_key))
        for row in rows
        if row.get(prompt_key) is not None and row.get(java_key) is not None
    ]
    if not paired:
        return None

    x_values = [float(pair[0]) for pair in paired]
    y_values = [float(pair[1]) for pair in paired]
    min_value = min(x_values + y_values)
    max_value = max(x_values + y_values)

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.scatter(x_values, y_values, alpha=0.75, color=cfg.MEAN_GAP_BAR_COLOR)
    plt.plot([min_value, max_value], [min_value, max_value], linestyle="--", color="black", linewidth=1.0)
    plt.xlabel(f"Prompt-Based {axis_label}")
    plt.ylabel(f"Java {axis_label}")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_bland_altman(rows: list[dict[str, Any]], output_path: Path) -> Path:
    """Plot Bland-Altman bias and limits of agreement."""
    plt = _import_pyplot()
    means = [(float(row["prompt_score"]) + float(row["java_score"])) / 2.0 for row in rows]
    diffs = [float(row["java_score"]) - float(row["prompt_score"]) for row in rows]
    mean_bias = sum(diffs) / len(diffs)
    variance = sum((diff - mean_bias) ** 2 for diff in diffs) / len(diffs) if diffs else 0.0
    std_dev = math.sqrt(variance)
    loa_upper = mean_bias + 1.96 * std_dev
    loa_lower = mean_bias - 1.96 * std_dev

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.scatter(means, diffs, alpha=0.75, color=cfg.MEAN_GAP_BAR_COLOR)
    plt.axhline(mean_bias, color="black", linestyle="-", linewidth=1.0, label="Mean bias")
    plt.axhline(loa_upper, color="red", linestyle="--", linewidth=1.0, label="Upper LoA")
    plt.axhline(loa_lower, color="red", linestyle="--", linewidth=1.0, label="Lower LoA")
    plt.xlabel("Mean Score")
    plt.ylabel("Java - Prompt-Based")
    plt.title("Bland-Altman Plot")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_error_histogram(rows: list[dict[str, Any]], output_path: Path) -> Path:
    """Plot the absolute error distribution."""
    plt = _import_pyplot()
    errors = [abs(float(row["java_score"]) - float(row["prompt_score"])) for row in rows]

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.hist(errors, bins=min(20, max(5, len(errors) // 2)), color=cfg.MEAN_GAP_BAR_COLOR, edgecolor="black")
    plt.xlabel("Absolute Error")
    plt.ylabel("Count")
    plt.title("Absolute Error Distribution")
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_topk_overlap(overall_summary: dict[str, Any], output_path: Path) -> Path:
    """Plot top-k overlap ratios from the overall summary row."""
    plt = _import_pyplot()
    ks = list(cfg.TOP_K_VALUES)
    values = [float(overall_summary.get(f"topk_overlap_{k}") or 0.0) for k in ks]

    plt.figure(figsize=cfg.BAR_FIGSIZE)
    plt.bar([str(k) for k in ks], values, color=cfg.SAME_RESULT_BAR_COLOR)
    plt.xlabel("Top-k")
    plt.ylabel("Overlap Ratio")
    plt.ylim(0.0, 1.0)
    plt.title("Top-k Overlap")
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_behavior_comparison(rows: list[dict[str, Any]], output_path: Path) -> Path | None:
    """Plot grouped bars comparing prompt and Java behavior means."""
    plt = _import_pyplot()
    usable_rows = [row for row in rows if row.get("group_type") == "overall" and row.get("prompt_mean") is not None]
    if not usable_rows:
        return None

    metrics = [str(row["behavior_metric"]) for row in usable_rows]
    prompt_values = [float(row["prompt_mean"]) for row in usable_rows]
    java_values = [float(row["java_mean"]) for row in usable_rows]
    positions = list(range(len(metrics)))
    width = 0.38

    plt.figure(figsize=(max(10, len(metrics) * 1.2), 5))
    plt.bar([position - width / 2 for position in positions], prompt_values, width=width, label="Prompt-Based")
    plt.bar([position + width / 2 for position in positions], java_values, width=width, label="Java")
    plt.xticks(positions, metrics, rotation=30, ha="right")
    plt.ylabel("Mean Value")
    plt.title("Behavior Comparison")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path


def plot_pairwise_metric_scatter(
    rows: list[dict[str, Any]],
    *,
    prompt_x_key: str,
    prompt_y_key: str,
    java_x_key: str,
    java_y_key: str,
    x_label: str,
    y_label: str,
    title: str,
    output_path: Path,
) -> Path | None:
    """Plot one 2D metric pair for prompt-based and Java agents."""
    plt = _import_pyplot()
    prompt_points = [
        (row.get(prompt_x_key), row.get(prompt_y_key))
        for row in rows
        if row.get(prompt_x_key) is not None and row.get(prompt_y_key) is not None
    ]
    java_points = [
        (row.get(java_x_key), row.get(java_y_key))
        for row in rows
        if row.get(java_x_key) is not None and row.get(java_y_key) is not None
    ]
    if not prompt_points and not java_points:
        return None

    plt.figure(figsize=(8, 6))
    if prompt_points:
        plt.scatter(
            [float(point[0]) for point in prompt_points],
            [float(point[1]) for point in prompt_points],
            alpha=0.75,
            color=cfg.MEAN_GAP_BAR_COLOR,
            label="Prompt-Based",
        )
    if java_points:
        plt.scatter(
            [float(point[0]) for point in java_points],
            [float(point[1]) for point in java_points],
            alpha=0.75,
            color=cfg.SAME_RESULT_BAR_COLOR,
            label="Java",
        )
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=cfg.FIGURE_DPI)
    plt.close()
    return output_path
