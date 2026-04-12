"""Markdown reporting for Java-vs-prompt consistency analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import analysis_config as cfg


def _format_float(value: Any, digits: int = 4) -> str:
    """Render one optional float for markdown output."""
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Render a simple markdown table."""
    if not rows:
        return "_No rows available._"
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join([header, divider, *body])


def interpret_surrogate_validity(
    overall_summary: dict[str, Any],
    behavior_rows: list[dict[str, Any]],
    missing_behavior_metrics: list[str],
) -> list[str]:
    """Build rule-based interpretation notes for the report."""
    notes: list[str] = []
    spearman = overall_summary.get("spearman")
    pearson = overall_summary.get("pearson")
    mean_bias = overall_summary.get("mean_bias")
    top10 = overall_summary.get("topk_overlap_10")

    if spearman is None:
        notes.append("Ranking consistency could not be estimated because there were not enough aligned samples.")
    elif float(spearman) >= cfg.SPEARMAN_HIGH_THRESHOLD:
        notes.append("Ranking consistency is high because Spearman is at least 0.7.")
    elif float(spearman) >= cfg.SPEARMAN_MEDIUM_THRESHOLD:
        notes.append("Ranking consistency is moderate because Spearman falls between 0.4 and 0.7.")
    else:
        notes.append("Ranking consistency is weak because Spearman is below 0.4.")

    if top10 is not None and float(top10) >= cfg.TOPK_HIGH_THRESHOLD:
        notes.append("Top-10 overlap is high, which suggests the surrogate can preserve EA selection pressure.")

    if pearson is not None and abs(float(pearson)) >= 0.7 and mean_bias is not None and abs(float(mean_bias)) >= cfg.HIGH_BIAS_THRESHOLD:
        notes.append("The surrogate appears rank-consistent but shows systematic score bias because Pearson is high while mean bias is also large.")

    numeric_behavior_rows = [row for row in behavior_rows if row.get("mae") is not None]
    if numeric_behavior_rows and any(float(row["mae"]) >= cfg.HIGH_BEHAVIOR_GAP_THRESHOLD for row in numeric_behavior_rows):
        notes.append("Behavior metrics differ meaningfully, so end results may look similar even when strategy behavior is not.")

    if missing_behavior_metrics:
        notes.append(f"Some behavior metrics were unavailable and were skipped: {', '.join(missing_behavior_metrics)}.")

    return notes


def write_analysis_report(
    output_path: Path,
    *,
    merged_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    behavior_rows: list[dict[str, Any]],
    missing_behavior_metrics: list[str],
    largest_bias_prompts: list[dict[str, Any]],
    figures_dir: Path,
) -> Path:
    """Write the final markdown report."""
    overall_summary = next((row for row in summary_rows if row.get("group_type") == "overall"), {})
    notes = interpret_surrogate_validity(overall_summary, behavior_rows, missing_behavior_metrics)

    summary_table_rows = []
    for row in summary_rows:
        summary_table_rows.append(
            {
                "group_type": row.get("group_type"),
                "group_value": row.get("group_value"),
                "pair_count": row.get("pair_count"),
                "pearson": _format_float(row.get("pearson")),
                "spearman": _format_float(row.get("spearman")),
                "kendall_tau": _format_float(row.get("kendall_tau")),
                "mae": _format_float(row.get("mae")),
                "rmse": _format_float(row.get("rmse")),
                "mean_bias": _format_float(row.get("mean_bias")),
                "top5": _format_float(row.get("topk_overlap_5")),
                "top10": _format_float(row.get("topk_overlap_10")),
                "top20": _format_float(row.get("topk_overlap_20")),
            }
        )

    behavior_table_rows = []
    for row in behavior_rows:
        behavior_table_rows.append(
            {
                "behavior_metric": row.get("behavior_metric"),
                "prompt_mean": _format_float(row.get("prompt_mean")),
                "java_mean": _format_float(row.get("java_mean")),
                "prompt_mode": row.get("prompt_mode") or "",
                "java_mode": row.get("java_mode") or "",
                "exact_match_rate": _format_float(row.get("exact_match_rate")),
                "pearson": _format_float(row.get("pearson")),
                "mae": _format_float(row.get("mae")),
                "rmse": _format_float(row.get("rmse")),
                "mean_bias": _format_float(row.get("mean_bias")),
            }
        )

    largest_bias_rows = [
        {
            "prompt_id": row.get("prompt_id"),
            "mean_abs_gap": _format_float(row.get("mean_abs_gap")),
            "pair_count": row.get("pair_count"),
        }
        for row in largest_bias_prompts
    ]

    lines = [
        "# Consistency Analysis Report",
        "",
        "## Data Summary",
        "",
        f"- Aligned result pairs: {len(merged_rows)}",
        f"- Unique prompt_ids: {len({str(row['prompt_id']) for row in merged_rows})}",
        f"- Maps: {len({str(row['map_name']) for row in merged_rows})}",
        f"- Opponents: {len({str(row['opponent']) for row in merged_rows})}",
        f"- Behavior rows available: {len(behavior_rows)}",
        "",
        "## Metric Summary",
        "",
        _markdown_table(
            summary_table_rows,
            [
                "group_type",
                "group_value",
                "pair_count",
                "pearson",
                "spearman",
                "kendall_tau",
                "mae",
                "rmse",
                "mean_bias",
                "top5",
                "top10",
                "top20",
            ],
        ),
        "",
        "## Figures",
        "",
        f"- Scatter consistency: `{figures_dir.name}/{cfg.SCATTER_FILENAME}`",
        "  This plot shows whether Java scores track prompt-based scores along the y=x line.",
        f"- Bland-Altman: `{figures_dir.name}/{cfg.BLAND_ALTMAN_FILENAME}`",
        "  This plot highlights systematic bias and spread of Java minus prompt-based scores.",
        f"- Error histogram: `{figures_dir.name}/{cfg.ERROR_HISTOGRAM_FILENAME}`",
        "  This histogram shows how large the absolute prediction errors are across aligned samples.",
        f"- Top-k overlap: `{figures_dir.name}/{cfg.TOPK_OVERLAP_FILENAME}`",
        "  This chart shows how much Java preserves the top-ranked prompt_ids used by EA selection.",
    ]

    if behavior_rows:
        lines.append(f"- Behavior comparison: `{figures_dir.name}/{cfg.BEHAVIOR_COMPARISON_FILENAME}`")
        lines.append("  This chart compares average behavior metrics between prompt-based and Java agents.")

    lines.extend(
        [
            "",
            "## Behavior Summary",
            "",
            _markdown_table(
                behavior_table_rows,
                [
                    "behavior_metric",
                    "prompt_mean",
                    "java_mean",
                    "prompt_mode",
                    "java_mode",
                    "exact_match_rate",
                    "pearson",
                    "mae",
                    "rmse",
                    "mean_bias",
                ],
            ),
            "",
            "## Largest Prompt Bias",
            "",
            _markdown_table(largest_bias_rows, ["prompt_id", "mean_abs_gap", "pair_count"]),
            "",
            "## Surrogate Validity Interpretation",
            "",
        ]
    )

    for note in notes:
        lines.append(f"- {note}")

    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "This report summarizes whether the Java agent can preserve prompt-based performance ordering and behavior similarity well enough to act as a practical surrogate.",
        ]
    )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
